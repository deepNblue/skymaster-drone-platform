"""Vision AI Edge Runtime — pluggable inference backend.

Backends
========

* **mock**   — synthesizes plausible detections for CI/dev (default).
* **onnx**   — real ONNX Runtime YOLO backend (v5/v8/v9 family output shape).
* **triton** — remote NVIDIA Triton Inference Server (large fleets, TODO).
* **jetson** — on-drone Jetson w/ TensorRT (edge-native, no upstream, TODO).

The active backend is selected by ``settings.vision_runtime`` (env
``VISION_RUNTIME``), defaulting to "mock" so the platform starts with no GPU
and no model files.

Zero-cost when unused: heavy modules are only imported inside the backend
that needs them.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DetectionBox:
    """Normalized [0,1] bbox + label + confidence."""

    label: str
    confidence: float
    bbox: list[float]  # [x0, y0, x1, y1] in [0,1]
    track_id: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionFrame:
    """Result of running the model on one frame."""

    detections: list[DetectionBox]
    model_tag: str
    runtime: str
    latency_ms: float
    frame_idx: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base class + registry
# ---------------------------------------------------------------------------


class VisionRuntime(ABC):
    """Abstract vision inference runtime."""

    name: str = "abstract"
    model_tag: str = "unknown"

    @abstractmethod
    async def infer(
        self,
        image_bytes: bytes | None = None,
        *,
        frame_idx: int | None = None,
        hint: str | None = None,
    ) -> DetectionFrame:
        """Run inference and return detections."""
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover
        """Release any GPU/network resources."""


_registry: dict[str, Callable[[], VisionRuntime]] = {}
_active: VisionRuntime | None = None


def register_runtime(name: str) -> Callable[[type[VisionRuntime]], type[VisionRuntime]]:
    def deco(cls: type[VisionRuntime]) -> type[VisionRuntime]:
        _registry[name] = cls
        return cls
    return deco


def list_runtimes() -> list[str]:
    return sorted(_registry.keys())


def get_active_runtime() -> VisionRuntime:
    """Return the current process-wide vision runtime (lazy init)."""
    global _active
    if _active is None:
        name = (settings.vision_runtime or "mock").lower()
        factory = _registry.get(name)
        if factory is None:
            factory = _registry["mock"]
        try:
            _active = factory()  # type: ignore[operator]
        except Exception as exc:  # pragma: no cover
            log.warning("vision runtime %s failed to init: %s — falling back to mock", name, exc)
            _active = _registry["mock"]()  # type: ignore[operator]
    return _active


def reset_active_runtime() -> None:
    """Test hook — force re-selection on next call."""
    global _active
    _active = None


# ---------------------------------------------------------------------------
# Mock backend — always available, no deps
# ---------------------------------------------------------------------------


_MOCK_LABELS = (
    "person", "vehicle", "vessel", "solar_panel", "power_line",
    "fire", "smoke", "crack", "helmet", "unknown_object",
)


@register_runtime("mock")
class MockVisionRuntime(VisionRuntime):
    """Deterministic synthetic detector for CI / demos.

    Same image → same detections (via SHA1 seed).
    """

    name = "mock"
    model_tag = "mock-yolov9-s"

    async def infer(
        self,
        image_bytes: bytes | None = None,
        *,
        frame_idx: int | None = None,
        hint: str | None = None,
    ) -> DetectionFrame:
        t0 = time.monotonic()
        seed_material = (image_bytes or b"") + (hint or "").encode() + str(frame_idx or 0).encode()
        seed = int.from_bytes(hashlib.sha1(seed_material).digest()[:8], "big")
        rnd = random.Random(seed)

        n = rnd.randint(0, 3)
        detections: list[DetectionBox] = []
        for _ in range(n):
            if hint and rnd.random() < 0.6:
                label = hint
            else:
                label = rnd.choice(_MOCK_LABELS)
            x0 = rnd.uniform(0.0, 0.7)
            y0 = rnd.uniform(0.0, 0.7)
            x1 = min(1.0, x0 + rnd.uniform(0.08, 0.3))
            y1 = min(1.0, y0 + rnd.uniform(0.08, 0.3))
            detections.append(DetectionBox(
                label=label,
                confidence=round(rnd.uniform(0.55, 0.99), 3),
                bbox=[round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                track_id=rnd.randint(1, 999),
                attrs={"synthesizer": "mock"},
            ))
        await asyncio.sleep(0)
        return DetectionFrame(
            detections=detections,
            model_tag=self.model_tag,
            runtime=self.name,
            latency_ms=round((time.monotonic() - t0) * 1000, 3),
            frame_idx=frame_idx,
            meta={"deterministic": True},
        )


# ---------------------------------------------------------------------------
# COCO labels — YOLO family default output classes
# ---------------------------------------------------------------------------

_COCO_LABELS: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)


# ---------------------------------------------------------------------------
# ONNX backend — real inference (YOLOv5 / v8 / v9 shape)
# ---------------------------------------------------------------------------


@register_runtime("onnx")
class OnnxVisionRuntime(VisionRuntime):
    """ONNX Runtime YOLO backend.

    Contract with the model file:
      * Single input tensor, shape ``(1, 3, H, W)``, dtype float32, RGB, /255.
      * Single output tensor with **one of** these shapes:
          - ``(1, N, 4+1+C)``   YOLOv5-style (xywh + obj + class probs)
          - ``(1, 4+C, N)``     YOLOv8/v9-style (xywh, C class probs) [transpose]
          - ``(1, N, 4+C)``     YOLOv8 already transposed

    Config (env / settings):
      * ``VISION_ONNX_MODEL_PATH``  — path to .onnx file
      * ``VISION_MODEL_TAG``        — display name (default: file stem)
      * ``VISION_ONNX_LABELS_PATH`` — optional newline-delimited class names;
        falls back to COCO-80 if absent.
      * ``VISION_ONNX_CONF_THR``    — score threshold (default 0.25)
      * ``VISION_ONNX_IOU_THR``     — NMS IoU threshold (default 0.45)
      * ``VISION_ONNX_IMGSZ``       — input resolution (default 640)

    Graceful degradation:
      * Import failure → falls back to mock at call time.
      * Model file missing → falls back to mock at init time.
      * Output shape unknown → falls back to mock for that frame.
    """

    name = "onnx"

    def __init__(self) -> None:
        self.model_tag = settings.vision_model_tag or "yolov-onnx"
        self._degraded = False
        self._session = None
        self._input_name: str | None = None
        self._imgsz: int = int(os.environ.get("VISION_ONNX_IMGSZ", "640"))
        self._conf_thr: float = float(os.environ.get("VISION_ONNX_CONF_THR", "0.25"))
        self._iou_thr: float = float(os.environ.get("VISION_ONNX_IOU_THR", "0.45"))
        self._labels: tuple[str, ...] = _COCO_LABELS

        model_path = os.environ.get("VISION_ONNX_MODEL_PATH", "").strip()
        labels_path = os.environ.get("VISION_ONNX_LABELS_PATH", "").strip()

        if not model_path or not Path(model_path).is_file():
            log.warning(
                "onnx backend: model file not found (VISION_ONNX_MODEL_PATH=%r) — will degrade to mock",
                model_path,
            )
            self._degraded = True
            return

        try:
            import onnxruntime as ort  # noqa: WPS433
            self.model_tag = settings.vision_model_tag or Path(model_path).stem
            providers = ["CPUExecutionProvider"]
            # Prefer CUDA when available.
            if "CUDAExecutionProvider" in ort.get_available_providers():
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            self._session = ort.InferenceSession(model_path, providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            log.info("onnx backend ready — model=%s providers=%s", self.model_tag, providers)
        except Exception as exc:
            log.warning("onnx backend init failed: %s — degrading to mock", exc)
            self._degraded = True
            return

        if labels_path and Path(labels_path).is_file():
            try:
                self._labels = tuple(
                    line.strip() for line in Path(labels_path).read_text().splitlines()
                    if line.strip()
                )
            except Exception as exc:
                log.warning("failed to read labels file %s: %s — using COCO", labels_path, exc)

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, image_bytes: bytes) -> tuple[Any, tuple[int, int, float, int, int]]:
        """Letterbox → RGB → CHW float32 /255.

        Returns (tensor, meta) where meta = (orig_w, orig_h, scale, pad_x, pad_y).
        """
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        orig_w, orig_h = img.size

        # Letterbox to imgsz x imgsz.
        s = min(self._imgsz / orig_w, self._imgsz / orig_h)
        new_w, new_h = int(round(orig_w * s)), int(round(orig_h * s))
        img_resized = img.resize((new_w, new_h), Image.BILINEAR)
        pad_x = (self._imgsz - new_w) // 2
        pad_y = (self._imgsz - new_h) // 2

        canvas = Image.new("RGB", (self._imgsz, self._imgsz), (114, 114, 114))
        canvas.paste(img_resized, (pad_x, pad_y))

        arr = np.asarray(canvas, dtype=np.float32) / 255.0
        arr = arr.transpose(2, 0, 1)[None, ...]  # (1,3,H,W)
        return arr, (orig_w, orig_h, s, pad_x, pad_y)

    # ------------------------------------------------------------------
    # Post-processing — shape-agnostic YOLO decoder
    # ------------------------------------------------------------------

    def _postprocess(self, output: Any, meta: tuple[int, int, float, int, int]) -> list[DetectionBox]:
        import numpy as np
        arr = np.asarray(output)
        if arr.ndim == 3:
            arr = arr[0]  # drop batch dim → (?, ?)

        # Detect layout — YOLOv8/v9 raw is (4+C, N), YOLOv5 raw is (N, 4+1+C),
        # already-transposed YOLOv8 is (N, 4+C). We disambiguate on the *first*
        # axis: if it equals 4+C the tensor is (4+C, N) and needs a transpose;
        # otherwise the *second* axis tells us the format.
        num_classes = len(self._labels)
        h, w = arr.shape
        if h == (4 + num_classes):
            arr = arr.T
            has_obj = False
        elif w == (5 + num_classes):
            has_obj = True
        elif w == (4 + num_classes):
            has_obj = False
        else:
            log.debug("onnx output shape %s doesn't match known YOLO layouts", arr.shape)
            return []

        boxes_xywh = arr[:, :4]
        if has_obj:
            obj_conf = arr[:, 4:5]
            class_scores = arr[:, 5:] * obj_conf
        else:
            class_scores = arr[:, 4:]

        cls_ids = class_scores.argmax(axis=1)
        cls_conf = class_scores.max(axis=1)

        mask = cls_conf >= self._conf_thr
        if not mask.any():
            return []
        boxes_xywh = boxes_xywh[mask]
        cls_ids = cls_ids[mask]
        cls_conf = cls_conf[mask]

        # xywh → xyxy in letterbox coords
        x, y, bw, bh = boxes_xywh.T
        x0 = x - bw / 2
        y0 = y - bh / 2
        x1 = x + bw / 2
        y1 = y + bh / 2
        boxes_xyxy = np.stack([x0, y0, x1, y1], axis=1)

        # De-letterbox → original image coords
        orig_w, orig_h, scale, pad_x, pad_y = meta
        boxes_xyxy[:, [0, 2]] -= pad_x
        boxes_xyxy[:, [1, 3]] -= pad_y
        boxes_xyxy /= scale
        boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, orig_w)
        boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, orig_h)

        # Simple class-aware greedy NMS.
        keep = self._nms(boxes_xyxy, cls_conf, cls_ids, self._iou_thr)

        results: list[DetectionBox] = []
        for i in keep[:300]:  # cap
            x0, y0, x1, y1 = boxes_xyxy[i]
            label = self._labels[int(cls_ids[i])] if int(cls_ids[i]) < len(self._labels) else "unknown"
            results.append(DetectionBox(
                label=label,
                confidence=float(cls_conf[i]),
                bbox=[
                    round(float(x0) / max(orig_w, 1), 4),
                    round(float(y0) / max(orig_h, 1), 4),
                    round(float(x1) / max(orig_w, 1), 4),
                    round(float(y1) / max(orig_h, 1), 4),
                ],
                attrs={"cls_id": int(cls_ids[i])},
            ))
        return results

    @staticmethod
    def _nms(boxes: Any, scores: Any, cls_ids: Any, iou_thr: float) -> list[int]:
        """Vectorised class-aware NMS (small numpy impl to avoid extra deps)."""
        import numpy as np
        keep: list[int] = []
        for c in np.unique(cls_ids):
            idx = np.where(cls_ids == c)[0]
            b = boxes[idx]
            s = scores[idx]
            order = s.argsort()[::-1]
            while order.size > 0:
                i = order[0]
                keep.append(int(idx[i]))
                if order.size == 1:
                    break
                xx1 = np.maximum(b[i, 0], b[order[1:], 0])
                yy1 = np.maximum(b[i, 1], b[order[1:], 1])
                xx2 = np.minimum(b[i, 2], b[order[1:], 2])
                yy2 = np.minimum(b[i, 3], b[order[1:], 3])
                inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
                area_i = (b[i, 2] - b[i, 0]) * (b[i, 3] - b[i, 1])
                area_o = (b[order[1:], 2] - b[order[1:], 0]) * (b[order[1:], 3] - b[order[1:], 1])
                iou = inter / (area_i + area_o - inter + 1e-9)
                order = order[1:][iou <= iou_thr]
        return keep

    # ------------------------------------------------------------------
    # Inference entry point
    # ------------------------------------------------------------------

    async def infer(
        self,
        image_bytes: bytes | None = None,
        *,
        frame_idx: int | None = None,
        hint: str | None = None,
    ) -> DetectionFrame:
        # Degrade → mock if model unavailable or no image supplied.
        if self._degraded or self._session is None or not image_bytes:
            fallback = await MockVisionRuntime().infer(image_bytes, frame_idx=frame_idx, hint=hint)
            fallback.runtime = "onnx-degraded" if self._degraded else "onnx-noimage"
            fallback.meta.setdefault("degraded_from", "onnx")
            return fallback

        t0 = time.monotonic()
        # Run ONNX inference off the event loop to avoid blocking.
        loop = asyncio.get_running_loop()
        detections = await loop.run_in_executor(
            None, self._infer_sync, image_bytes,
        )
        return DetectionFrame(
            detections=detections,
            model_tag=self.model_tag,
            runtime=self.name,
            latency_ms=round((time.monotonic() - t0) * 1000, 3),
            frame_idx=frame_idx,
            meta={"imgsz": self._imgsz, "conf_thr": self._conf_thr},
        )

    def _infer_sync(self, image_bytes: bytes) -> list[DetectionBox]:
        try:
            tensor, meta = self._preprocess(image_bytes)
            outputs = self._session.run(None, {self._input_name: tensor})
            return self._postprocess(outputs[0], meta)
        except Exception as exc:
            log.warning("onnx infer failed on frame: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Helpers used by the API
# ---------------------------------------------------------------------------


def decode_base64_image(b64: str) -> bytes:
    """Accept ``data:image/...;base64,xxxx`` or bare base64."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)
