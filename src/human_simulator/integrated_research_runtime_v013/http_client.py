"""HTTP test client — urllib against a live local server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class HttpClient:
    def __init__(self, host: str, port: int) -> None:
        self.base = f"http://{host}:{port}"

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                ctype = resp.headers.get("Content-Type") or ""
                if "html" in ctype:
                    return {"status": "OK", "html": raw, "content_type": ctype, "http_status": resp.status}
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("http_status", resp.status)
                return parsed
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"status": "FAIL", "reason": raw, "http_status": e.code}
            if isinstance(parsed, dict):
                parsed.setdefault("http_status", e.code)
            return parsed
        except json.JSONDecodeError:
            return {"status": "FAIL", "reason": "INVALID_JSON"}
