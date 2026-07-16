"""Thin HTTP client for the urbantrends.dev backend (`agent_api`).

Mica sources her real business data — catalog, prices, orders — from the host
backend (see BACKEND_APIS.md). This module is the one place that speaks HTTP to
it: stdlib urllib only (same as agent/identity.py, no new deps), a short
timeout, and a single error type so callers can distinguish a *business* outcome
(e.g. an expired quote → re-quote) from a *provider failure* (backend down →
retry/escalate).

Active only when `URBANTRENDS_API_BASE` is set; otherwise Mica runs on her
in-repo static stubs and this is never called (keyless dev/tests).

Auth: the service key is sent in `URBANTRENDS_API_KEY_HEADER` (default
"Authorization") as `URBANTRENDS_API_KEY_PREFIX` + key (default "Bearer "). For
user-scoped calls, the visitor's forwarded host `sessionid` rides on
`X-UT-Session` so the backend can resolve *who* is acting (never trusted from a
body field). Server-authored `session_ref` / `Idempotency-Key` are added by the
caller as needed.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)

# Agent endpoints live under this prefix; URBANTRENDS_API_BASE is the bare origin
# (e.g. https://urbantrends.dev), per MICA_INTEGRATION.md.
_API_PREFIX = "/api/v1/agent"


class BackendError(Exception):
    """A non-2xx from the backend (or an unreachable backend).

    `code` is the machine code from the error envelope
    (`{"error": {"code": ...}}`), or a synthetic one (`http_500`,
    `backend_unreachable`). `fields` carries per-field validation messages (422).
    """

    def __init__(self, code: str, message: str = "", fields: dict | None = None, status: int = 0):
        self.code = code
        self.fields = fields or {}
        self.status = status
        super().__init__(f"{code}: {message}" if message else code)


class BackendClient:
    def __init__(self, base: str, key: str, key_header: str, key_prefix: str, timeout: float):
        base = base.rstrip("/")
        # Tolerate a base that already carries the prefix; we add it in _request.
        if base.endswith(_API_PREFIX):
            base = base[: -len(_API_PREFIX)]
        self._base = base
        self._key = key
        self._key_header = key_header
        self._key_prefix = key_prefix
        self._timeout = timeout

    def _headers(self, session_cookie: str | None, idempotency_key: str | None) -> dict:
        headers = {"Accept": "application/json"}
        if self._key:
            headers[self._key_header] = f"{self._key_prefix}{self._key}"
        if session_cookie:  # user-scoped calls: let the backend resolve the visitor
            headers["X-UT-Session"] = session_cookie
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def get_json(self, path: str, *, session_cookie: str | None = None) -> dict:
        return self._request("GET", path, None, session_cookie, None)

    def post_json(
        self,
        path: str,
        body: dict,
        *,
        session_cookie: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        return self._request("POST", path, body, session_cookie, idempotency_key)

    def _request(self, method, path, body, session_cookie, idempotency_key) -> dict:
        url = self._base + _API_PREFIX + path
        headers = self._headers(session_cookie, idempotency_key)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise _error_from_http(exc)
        except Exception as exc:  # network hiccup, timeout, bad JSON → provider failure
            log.exception("backend %s %s failed", method, path)
            raise BackendError("backend_unreachable", str(exc))


def _error_from_http(exc: urllib.error.HTTPError) -> BackendError:
    """Turn an HTTPError into a BackendError, reading the error envelope if any."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
    except Exception:
        err = {}
    return BackendError(
        code=err.get("code") or f"http_{exc.code}",
        message=err.get("message", ""),
        fields=err.get("fields"),
        status=exc.code,
    )


def get_client() -> BackendClient:
    """Build a client from current settings (cheap; reads live config each call)."""
    return BackendClient(
        base=settings.URBANTRENDS_API_BASE,
        key=settings.URBANTRENDS_API_KEY,
        key_header=settings.URBANTRENDS_API_KEY_HEADER,
        key_prefix=settings.URBANTRENDS_API_KEY_PREFIX,
        timeout=settings.URBANTRENDS_API_TIMEOUT,
    )
