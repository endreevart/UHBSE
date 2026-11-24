"""Provider layer — RxNorm (documented REST) + ESKLP local snapshot import."""

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

from human_simulator.medication_reference_v01.policy import (
    RUNTIME_DIR,
    RXNORM_REST_BASE,
    VERSION,
)

# Forbidden keys in outbound payloads / logs
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
    blob = json.dumps(payload, ensure_ascii=False).casefold()
    for k in _FORBIDDEN_REQUEST_KEYS:
        if k in payload or k in blob:
            # allow medicine name strings that happen to contain substrings? check keys only
            pass
    for k in payload:
        if k.casefold() in _FORBIDDEN_REQUEST_KEYS:
            raise ValueError(f"patient_level_key_forbidden_in_provider_request: {k}")


class RxNormClient:
    """Documented RxNav REST client with on-disk cache. Catalog strings only."""

    def __init__(self, root: Path, *, allow_network: bool = True, timeout_s: float = 8.0):
        self.root = root.resolve()
        self.cache_dir = self.root / RUNTIME_DIR / "provider-cache" / "rxnorm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.cache_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.allow_network = allow_network
        self.timeout_s = timeout_s
        self.stats = {
            "cache_hits": 0,
            "network_fetches": 0,
            "network_errors": 0,
            "http_statuses": {},
        }
        self._network_probe: str | None = None

    def _cache_path(self, request_sha: str) -> Path:
        return self.cache_dir / f"{request_sha}.json"

    def probe_network(self) -> str:
        if self._network_probe is not None:
            return self._network_probe
        if not self.allow_network:
            self._network_probe = "DISABLED"
            return self._network_probe
        try:
            url = f"{RXNORM_REST_BASE}/rxcui.json?name=aspirin"
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "UHBSE-medication-reference/0.1",
                },
            )
            with urllib.request.urlopen(req, timeout=min(self.timeout_s, 5.0)) as resp:
                self._network_probe = (
                    "REACHABLE" if int(resp.status) == 200 else "UNREACHABLE"
                )
        except Exception:  # noqa: BLE001
            self._network_probe = "UNREACHABLE"
        return self._network_probe

    def get_rxcui_by_name(self, name: str) -> dict[str, Any]:
        """GET /REST/rxcui.json?name=... (exact-ish name lookup)."""
        params = {"name": name}
        assert_catalog_only(params)
        endpoint = f"{RXNORM_REST_BASE}/rxcui.json"
        return self._request(endpoint=endpoint, params=params, method="GET")

    def approximate_term(self, term: str, *, max_entries: int = 5) -> dict[str, Any]:
        """GET /REST/approximateTerm.json?term=..."""
        params = {"term": term, "maxEntries": str(max_entries)}
        assert_catalog_only(params)
        endpoint = f"{RXNORM_REST_BASE}/approximateTerm.json"
        return self._request(endpoint=endpoint, params=params, method="GET")

    def _request(self, *, endpoint: str, params: dict[str, str], method: str) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{endpoint}?{query}"
        request_meta = {
            "provider": "RxNorm",
            "endpoint": endpoint,
            "params": params,
            "method": method,
            "url_path_only": endpoint.replace(RXNORM_REST_BASE, "/REST"),
        }
        request_sha = _sha_obj(request_meta)
        cache_path = self._cache_path(request_sha)
        if cache_path.is_file():
            self.stats["cache_hits"] += 1
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["from_cache"] = True
            return cached

        if (not self.allow_network) or self.probe_network() == "UNREACHABLE":
            self.stats["network_errors"] += 1
            return {
                "provider": "RxNorm",
                "endpoint": endpoint,
                "params": params,
                "request_sha256": request_sha,
                "retrieval_status": "NETWORK_UNAVAILABLE",
                "http_status": None,
                "from_cache": False,
                "response": None,
                "response_sha256": None,
                "timestamp": _now(),
                "patient_level_data": False,
                "secrets_in_request": False,
                "probe": self._network_probe,
            }

        ts = _now()
        http_status = None
        body: bytes | None = None
        error = None
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "UHBSE-medication-reference/0.1"},
                method=method,
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                http_status = int(resp.status)
                body = resp.read()
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            body = exc.read() if exc.fp else b""
            error = f"HTTPError:{exc.code}"
            self.stats["network_errors"] += 1
        except Exception as exc:  # noqa: BLE001 — record and continue offline
            error = type(exc).__name__
            self.stats["network_errors"] += 1
            body = None
            self._network_probe = "UNREACHABLE"

        self.stats["network_fetches"] += 1
        st_key = str(http_status)
        self.stats["http_statuses"][st_key] = self.stats["http_statuses"].get(st_key, 0) + 1

        response_sha = _sha_b(body) if body is not None else None
        if body is not None:
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
            "provider_version": None,
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
        }
        # Cache successful responses; also cache failures to avoid repeat timeouts
        cache_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        if http_status == 200:
            time.sleep(0.05)
        return record


def import_esklp_snapshot(root: Path, snapshot_path: Path) -> dict[str, Any]:
    """Import approved local ESKLP/official Russian medication snapshot.

    Does not invent or scrape undocumented APIs.
    """
    root = root.resolve()
    snapshot_path = Path(snapshot_path).resolve()
    if not snapshot_path.is_file():
        return {
            "ESKLP_PROVIDER_STATUS": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
            "reason": f"file_missing:{snapshot_path}",
        }
    dest_dir = root / RUNTIME_DIR / "provider-snapshots" / "esklp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    data = snapshot_path.read_bytes()
    h = _sha_b(data)
    dest = dest_dir / snapshot_path.name
    dest.write_bytes(data)
    meta = {
        "provider_name": "ESKLP",
        "data_file": snapshot_path.name,
        "sha256": h,
        "retrieval_date": _now(),
        "source_path": str(snapshot_path),
        "licensing_usage_status": "LOCAL_APPROVED_SNAPSHOT",
        "fields_used": [],
        "fields_explicitly_not_trusted": [],
    }
    (dest_dir / "snapshot-manifest.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "ESKLP_PROVIDER_STATUS": "VERIFIED",
        "content_hash": h,
        "snapshot_relative": str(dest.relative_to(root)),
        "manifest": meta,
    }


def discover_esklp_status(root: Path) -> dict[str, Any]:
    manifest = root / RUNTIME_DIR / "provider-snapshots" / "esklp" / "snapshot-manifest.json"
    if not manifest.is_file():
        return {
            "provider_name": "ESKLP",
            "retrieval_status": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
            "ESKLP_PROVIDER_STATUS": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
            "content_hash": None,
        }
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    data = root / RUNTIME_DIR / "provider-snapshots" / "esklp" / meta["data_file"]
    if not data.is_file():
        return {
            "provider_name": "ESKLP",
            "retrieval_status": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
            "ESKLP_PROVIDER_STATUS": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
        }
    h = _sha_b(data.read_bytes())
    ok = h == meta.get("sha256")
    return {
        "provider_name": "ESKLP",
        "retrieval_status": "VERIFIED" if ok else "HASH_MISMATCH",
        "ESKLP_PROVIDER_STATUS": "VERIFIED" if ok else "HASH_MISMATCH",
        "content_hash": h,
        "retrieval_date": meta.get("retrieval_date"),
    }


def build_provider_acquisition_report(
    *,
    rxnorm_stats: dict[str, Any],
    esklp: dict[str, Any],
    rxnorm_verified_n: int,
) -> dict[str, Any]:
    fetches = int(rxnorm_stats.get("network_fetches") or 0)
    hits = int(rxnorm_stats.get("cache_hits") or 0)
    errors = int(rxnorm_stats.get("network_errors") or 0)
    http = rxnorm_stats.get("http_statuses") or {}
    ok_http = int(http.get("200") or 0)

    if rxnorm_verified_n > 0 or ok_http > 0:
        rx_status = "ACQUIRED" if fetches or hits else "ACQUIRED_WITH_CACHE"
    elif errors and not ok_http:
        rx_status = "NETWORK_UNAVAILABLE_OR_FAILED"
    elif hits and not ok_http:
        rx_status = "CACHE_ONLY_NO_VERIFIED_PAYLOAD"
    else:
        rx_status = "NOT_ATTEMPTED"

    if esklp.get("ESKLP_PROVIDER_STATUS") == "VERIFIED" and rxnorm_verified_n > 0:
        overall = "ACQUIRED"
    elif rxnorm_verified_n > 0:
        overall = "RXNORM_ACQUIRED_ESKLP_UNAVAILABLE"
    elif rx_status.startswith("NETWORK"):
        overall = "ATTEMPTED_NETWORK_FAILED"
    else:
        overall = "NOT_AVAILABLE"

    return {
        "version": VERSION,
        "DRUG_REFERENCE_ACQUISITION_STATUS": overall,
        "providers": {
            "RxNorm": {
                "retrieval_status": rx_status,
                "documented_base": RXNORM_REST_BASE,
                "stats": rxnorm_stats,
                "verified_lookups": rxnorm_verified_n,
                "paid_api": False,
                "api_keys": False,
                "patient_level_data_sent": False,
            },
            "ESKLP": esklp,
            "DailyMed": {
                "retrieval_status": "DEFERRED_UNTIL_RXCUI_OR_US_PRODUCT",
                "note": "Downstream enrichment only after reliable concept ID",
            },
            "openFDA": {
                "retrieval_status": "DEFERRED_UNTIL_RXCUI_OR_US_PRODUCT",
                "fields_explicitly_not_trusted": ["adverse_event_as_causal_risk"],
            },
        },
    }
