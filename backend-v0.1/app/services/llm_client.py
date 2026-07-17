"""LLM client (SDD v2.0-C §3).

Supports both Anthropic-compatible (`/anthropic/v1/messages`) and
OpenAI-compatible (`/v3/chat/completions`) endpoints. The concrete
protocol is chosen via env var `LLM_PROTOCOL` (default: ``anthropic``).

All I/O is async via ``httpx.AsyncClient``. Non-2xx 5xx responses are
retried at most twice with a 500 ms back-off. Default request timeout
is 60 s.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Iterable

import httpx


class LLMClient:
    """Minimal async client for Copilot v0.1.

    Parameters
    ----------
    base_url:
        Root URL of the LLM provider, e.g.
        ``https://ark.cn-beijing.volces.com/api/coding``.
    api_key:
        Bearer token.
    model:
        Default model name; overridable per call.
    protocol:
        ``"anthropic"`` or ``"openai"``.
    timeout:
        Per-request timeout in seconds.
    max_retries:
        Additional attempts on transient 5xx errors.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        model: str = "ark-code-latest",
        protocol: str = "anthropic",
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = model
        self.protocol = protocol.lower()
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _endpoint(self, streaming: bool = False) -> str:
        if self.protocol == "anthropic":
            return f"{self.base_url}/anthropic/v1/messages"
        return f"{self.base_url}/v3/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.protocol == "anthropic":
            h["anthropic-version"] = "2023-06-01"
        return h

    def _payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        stream: bool,
    ) -> dict[str, Any]:
        if self.protocol == "anthropic":
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": 2048,
                "stream": stream,
            }
            if tools:
                payload["tools"] = tools
            return payload
        # OpenAI-compatible
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def _request_with_retry(
        self, client: httpx.AsyncClient, payload: dict[str, Any], *, stream: bool
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                req = client.build_request(
                    "POST",
                    self._endpoint(streaming=stream),
                    headers=self._headers(),
                    json=payload,
                )
                resp = await client.send(req, stream=stream)
                if resp.status_code >= 500 and attempt < self.max_retries:
                    await resp.aclose()
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # non-streaming
    # ------------------------------------------------------------------
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Return the full JSON response from the LLM provider."""
        model_id = model or self.default_model
        payload = self._payload(messages, tools, model_id, stream=False)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await self._request_with_retry(client, payload, stream=False)
            try:
                return resp.json()
            finally:
                await resp.aclose()

    # ------------------------------------------------------------------
    # streaming (SSE)
    # ------------------------------------------------------------------
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield incremental text deltas as they arrive over SSE."""
        model_id = model or self.default_model
        payload = self._payload(messages, tools, model_id, stream=True)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await self._request_with_retry(client, payload, stream=True)
            try:
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = self._extract_delta(obj)
                    if delta:
                        yield delta
            finally:
                await resp.aclose()

    def _extract_delta(self, obj: dict[str, Any]) -> str | None:
        """Best-effort extract textual delta from either protocol shape."""
        if self.protocol == "anthropic":
            # content_block_delta: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
            delta = obj.get("delta")
            if isinstance(delta, dict):
                text = delta.get("text")
                if isinstance(text, str):
                    return text
            return None
        # OpenAI: {"choices":[{"delta":{"content":"..."}}]}
        choices = obj.get("choices") or []
        if choices and isinstance(choices, list):
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                return content
        return None


__all__ = ["LLMClient"]
