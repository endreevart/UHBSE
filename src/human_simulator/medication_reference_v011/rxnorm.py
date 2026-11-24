"""RxNorm client with corrected network accounting (no per-drug failure cache on outage)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.policy import RUNTIME_DIR, RXNORM_REST_BASE, VERSION

_FORBIDDEN_REQUEST_KEYS = frozenset(
    {
        "patient_id",
        "opaque_subject_key",
        "episode_id",
        "appointment_date",
        "lab",
        "post_value",
        "pre_value",
    }
)


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_obj(obj: Any) -> str:
    return _sha_b(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode())


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def assert_catalog_only(payload: dict[str, Any]) -> None:
    for k in payload:
        if k.casefold() in _FORBIDDEN_REQUEST_KEYS:
            raise ValueError(f"patient_level_key_forbidden_in_provider_request: {k}")


class NetworkAccounting:
    """Separated counters — one failed probe must not look like N HTTP attempts."""

    def __init__(self) -> None:
        self.network_probe_attempts = 0
        self.actual_http_requests = 0
        self.successful_http_responses = 0
        self.http_errors = 0
        self.timeouts = 0
        self.short_circuited_requests = 0
        self.cache_hits = 0
        self.cached_failures = 0
        # Legacy mis-accounting annotation from v0.1
        self.v01_logical_request_failures_after_single_failed_probe = (
            "LOGICAL_REQUEST_FAILURES_AFTER_SINGLE_FAILED_PROBE"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "network_probe_attempts": self.network_probe_attempts,
            "actual_http_requests": self.actual_http_requests,
            "successful_http_responses": self.successful_http_responses,
            "http_errors": self.http_errors,
            "timeouts": self.timeouts,
            "short_circuited_requests": self.short_circuited_requests,
            "cache_hits": self.cache_hits,
            "cached_failures": self.cached_failures,
            "v01_defect_label": self.v01_logical_request_failures_after_single_failed_probe,
            "v01_defect_note": (
                "Prior release reported network_errors≈974 with network_fetches=0 "
                "after a single failed probe; those were short-circuited logical "
                "failures, not HTTP attempts."
            ),
        }


class RxNormClient:
    def __init__(
        self,
        root: Path,
        *,
        allow_network: bool = False,
        timeout_s: float = 8.0,
        cache_failures: bool = False,
    ):
        self.root = root.resolve()
        self.cache_dir = self.root / RUNTIME_DIR / "provider-cache" / "rxnorm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.cache_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.allow_network = allow_network
        self.timeout_s = timeout_s
        self.cache_failures = cache_failures
        self.stats = NetworkAccounting()
        self._network_probe: str | None = None

    def _cache_path(self, request_sha: str) -> Path:
        return self.cache_dir / f"{request_sha}.json"

    def probe_network(self) -> str:
        if self._network_probe is not None:
            return self._network_probe
        if not self.allow_network:
            self._network_probe = "DISABLED"
            return self._network_probe
        self.stats.network_probe_attempts += 1
        try:
            url = f"{RXNORM_REST_BASE}/rxcui.json?name=aspirin"
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "UHBSE-medication-reference/0.1.1",
                },
            )
            with urllib.request.urlopen(req, timeout=min(self.timeout_s, 5.0)) as resp:
                self.stats.actual_http_requests += 1
                if int(resp.status) == 200:
                    self.stats.successful_http_responses += 1
                    self._network_probe = "REACHABLE"
                else:
                    self.stats.http_errors += 1
                    self._network_probe = "UNREACHABLE"
        except TimeoutError:
            self.stats.timeouts += 1
            self._network_probe = "UNREACHABLE"
        except Exception:  # noqa: BLE001
            self.stats.timeouts += 1
            self._network_probe = "UNREACHABLE"
        return self._network_probe

    def get_rxcui_by_name(self, name: str) -> dict[str, Any]:
        params = {"name": name}
        assert_catalog_only(params)
        return self._request(f"{RXNORM_REST_BASE}/rxcui.json", params)

    def get_properties(self, rxcui: str) -> dict[str, Any]:
        params = {"rxcui": str(rxcui)}
        assert_catalog_only(params)
        return self._request(f"{RXNORM_REST_BASE}/rxcui/{rxcui}/properties.json", {})

    def get_related_ingredients(self, rxcui: str) -> dict[str, Any]:
        # Documented related API
        return self._request(
            f"{RXNORM_REST_BASE}/rxcui/{rxcui}/related.json",
            {"tty": "IN+MIN"},
        )

    def approximate_term(self, term: str, *, max_entries: int = 5) -> dict[str, Any]:
        params = {"term": term, "maxEntries": str(max_entries)}
        assert_catalog_only(params)
        return self._request(f"{RXNORM_REST_BASE}/approximateTerm.json", params)

    def _request(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params) if params else ""
        url = f"{endpoint}?{query}" if query else endpoint
        request_meta = {
            "provider": "RxNorm",
            "endpoint": endpoint,
            "params": params,
            "method": "GET",
        }
        request_sha = _sha_obj(request_meta)
        cache_path = self._cache_path(request_sha)
        if cache_path.is_file():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("retrieval_status") in {
                "NETWORK_UNAVAILABLE",
                "NETWORK_ERROR",
                "PROBE_SHORT_CIRCUIT",
            }:
                self.stats.cached_failures += 1
            else:
                self.stats.cache_hits += 1
            cached["from_cache"] = True
            return cached

        probe = self.probe_network()
        if (not self.allow_network) or probe != "REACHABLE":
            self.stats.short_circuited_requests += 1
            record = {
                "provider": "RxNorm",
                "endpoint": endpoint,
                "params": params,
                "request_sha256": request_sha,
                "retrieval_status": "PROBE_SHORT_CIRCUIT",
                "http_status": None,
                "from_cache": False,
                "response": None,
                "response_sha256": None,
                "timestamp": _now(),
                "patient_level_data": False,
                "secrets_in_request": False,
                "probe": probe,
                "version": VERSION,
            }
            # Do NOT write a cache entry per drug after provider outage
            return record

        ts = _now()
        http_status = None
        body: bytes | None = None
        error = None
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "UHBSE-medication-reference/0.1.1",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                http_status = int(resp.status)
                body = resp.read()
            self.stats.actual_http_requests += 1
            if http_status == 200:
                self.stats.successful_http_responses += 1
            else:
                self.stats.http_errors += 1
        except TimeoutError as exc:
            error = type(exc).__name__
            self.stats.timeouts += 1
            self.stats.actual_http_requests += 1
            self._network_probe = "UNREACHABLE"
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            body = exc.read() if exc.fp else b""
            error = f"HTTPError:{exc.code}"
            self.stats.actual_http_requests += 1
            self.stats.http_errors += 1
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
            self.stats.actual_http_requests += 1
            self.stats.timeouts += 1
            self._network_probe = "UNREACHABLE"

        response_sha = _sha_b(body) if body is not None else None
        if body is not None and http_status == 200:
            (self.raw_dir / f"{request_sha}.bin").write_bytes(body)

        parsed = None
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                parsed = {"_raw_text_truncated": body[:500].decode("utf-8", errors="replace")}

        record = {
            "provider": "RxNorm",
            "endpoint": endpoint,
            "params": params,
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            "http_status": http_status,
            "timestamp": ts,
            "retrieval_status": (
                "VERIFIED"
                if http_status == 200 and parsed is not None
                else ("HTTP_ERROR" if http_status else "NETWORK_ERROR")
            ),
            "error": error,
            "response": parsed,
            "from_cache": False,
            "secrets_in_request": False,
            "patient_level_data": False,
            "version": VERSION,
        }
        # Cache only successful verified payloads by default
        if http_status == 200 or self.cache_failures:
            cache_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        if http_status == 200:
            time.sleep(0.05)
        return record


def enrich_rxcui_evidence(client: RxNormClient, rxcui: str) -> dict[str, Any]:
    """RxCUI alone is insufficient — fetch properties + related ingredients."""
    props = client.get_properties(rxcui)
    related = client.get_related_ingredients(rxcui)
    prop_group = ((props.get("response") or {}).get("properties") or {}) if props else {}
    return {
        "rxcui": str(rxcui),
        "name": prop_group.get("name"),
        "tty": prop_group.get("tty"),
        "synonym": prop_group.get("synonym"),
        "properties_status": props.get("retrieval_status"),
        "properties_evidence_hash": props.get("response_sha256"),
        "related_status": related.get("retrieval_status"),
        "related_evidence_hash": related.get("response_sha256"),
        "related_response": related.get("response"),
        "single_rxcui_insufficient": True,
    }
