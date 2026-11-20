"""Application configuration via Pydantic BaseSettings."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SkyMaster v0.1 runtime settings — loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Storage / infra --------------------------------------------------
    database_url: str = (
        "postgresql+asyncpg://skymaster:skymaster@localhost:5432/skymaster"
    )
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"

    # --- Auth (JWT HS256, short access token) -----------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 15
    # If true, /sim, /uom, /geofence accept anonymous requests as an
    # in-memory 'operator' user. Only for local demo/tests.
    auth_optional: bool = True

    # --- MAVLink ----------------------------------------------------------
    mavlink_endpoint: str = "udpin:0.0.0.0:14550"
    telemetry_publish_ms: int = 500

    # --- DJI Cloud API v2 -------------------------------------------------
    # mode: "mock" (default, no hardware) or "cloud" (real Dock/Pilot MQTT).
    # Credentials come from DJI developer portal — set via env, never hard-code.
    dji_mode: str = "mock"
    dji_gateway_sn: str = "MOCKDOCK001"
    dji_broker_host: str = "127.0.0.1"
    dji_broker_port: int = 1883
    dji_client_id: str = ""
    dji_username: str = ""
    dji_password: str = ""
    dji_mock_start_lat: float = 22.8167
    dji_mock_start_lng: float = 108.3167
    dji_mock_drones: int = 1
    # Empty = use backend/config/dji_calibration.json and backend/data/dji_rc_calibration.json
    dji_calibration_config: str = ""
    dji_rc_calibration_file: str = ""
    # Empty = use backend/config/dji_control.json
    dji_control_config: str = ""

    # --- MediaMTX (video streaming) --------------------------------------
    mediamtx_api_url: str = "http://mediamtx:9997"
    mediamtx_hls_url_base: str = "http://mediamtx:8888"
    mediamtx_rtsp_url_base: str = "rtsp://mediamtx:8554"

    # --- LLM / Copilot (Track C v0.1) -------------------------------------
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/coding"
    llm_api_key: str = ""
    llm_model: str = "ark-code-latest"
    llm_protocol: str = "anthropic"  # "anthropic" | "openai"

    # --- Misc -------------------------------------------------------------
    debug: bool = False
    cors_origins: list[str] = ["*"]

    # --- 国密 / Compliance (v2.0 R18) -------------------------------------
    # Master switch — off by default to keep zero perf overhead on latency-
    # critical paths (telemetry, live streams). Turn on per-tenant or per-
    # deployment when 等保 2.0 三级 review requires it.
    gm_crypto_enabled: bool = False
    # "off"  — no encryption/digest (fast path)
    # "hash" — only SM3 hash-chain on audit logs (~µs overhead)
    # "full" — SM3 hash-chain + SM4 payload encryption on audit logs
    gm_crypto_mode: str = "off"
    # Hex-encoded 16-byte SM4 master key. If blank, auto-derived from
    # jwt_secret via SM3 (dev/demo only — production MUST provide a real
    # KMS-managed key).
    gm_sm4_key_hex: str = ""
    # Modules to protect. Comma-separated list of any of:
    # {"audit_log", "session", "flight_approval", "transcription"}.
    gm_protect_modules: str = "audit_log"

    # --- Vision AI Edge Runtime (v2.0 R20 Track B) -----------------------
    # "mock" (default) | "onnx" | "triton" | "jetson"
    vision_runtime: str = "mock"
    vision_model_tag: str = ""
    # Persist detection into DB only if confidence >= threshold — otherwise
    # returned to the caller but dropped, keeping storage bounded.
    vision_persist_threshold: float = 0.65

    # --- Copilot LLM fallback (v2.0 R21 Step C) --------------------------
    # When rule-based intent parser returns confidence < threshold, optionally
    # invoke the LLM classifier to disambiguate. Default OFF — the platform
    # stays fully deterministic unless explicitly enabled.
    copilot_llm_fallback: bool = False
    copilot_llm_fallback_threshold: float = 0.6


settings = Settings()
