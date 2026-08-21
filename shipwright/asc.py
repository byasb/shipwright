"""Thin App Store Connect REST client.

- ES256 JWT minted from the .p8 (Secret Manager in Cloud Run, file locally), re-minted every 15 min.
- Retries with exponential backoff on 429 and 5xx — Apple 500s on real endpoints (pricePoints, availability).
- Every write is gated by DRY_RUN and the app allowlist. A dry-run write returns {"dry_run": True, ...}
  so callers can keep flowing and the job log shows exactly what WOULD have been sent.
- `read_back` after writes is the caller's job: a 2xx from Apple means "stored", not "done".
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from . import config

log = logging.getLogger("shipwright.asc")
BASE = "https://api.appstoreconnect.apple.com"


class ASCError(Exception):
    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status, self.body, self.method, self.path = status, body, method, path
        super().__init__(f"{method} {path} -> {status}: {body}")

    @property
    def errors(self) -> list[dict]:
        return (self.body or {}).get("errors", []) if isinstance(self.body, dict) else []

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500


class ASC:
    def __init__(self, key_id: str | None = None, issuer: str | None = None, pem: str | None = None):
        self.key_id = key_id or config.ASC_KEY_ID
        self.issuer = issuer or config.issuer_id()
        self.pem = pem or config.private_key()
        self._tok: str | None = None
        self._tok_exp = 0.0
        self.http = httpx.Client(base_url=BASE, timeout=60)

    # --- auth -----------------------------------------------------------
    def token(self) -> str:
        now = time.time()
        if self._tok and now < self._tok_exp - 60:
            return self._tok
        exp = now + 15 * 60
        self._tok = jwt.encode(
            {"iss": self.issuer, "iat": int(now), "exp": int(exp), "aud": "appstoreconnect-v1"},
            self.pem,
            algorithm="ES256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        self._tok_exp = exp
        return self._tok

    # --- transport --------------------------------------------------------
    @retry(
        retry=retry_if_exception(lambda e: isinstance(e, ASCError) and e.retryable or isinstance(e, httpx.TransportError)),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def _req(self, method: str, path: str, **kw) -> Any:
        r = self.http.request(method, path, headers={"Authorization": f"Bearer {self.token()}"}, **kw)
        if r.status_code == 429:
            log.warning("ASC 429 on %s %s — backing off", method, path)
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise ASCError(r.status_code, body, method, path)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    def get(self, path: str, **params) -> Any:
        return self._req("GET", path, params=params or None)

    def get_all(self, path: str, **params) -> list[dict]:
        """Follow `links.next` — territories, pricePoints, equalizations all paginate."""
        out: list[dict] = []
        params.setdefault("limit", 200)
        data = self.get(path, **params)
        while True:
            out.extend(data.get("data", []))
            nxt = (data.get("links") or {}).get("next")
            if not nxt:
                return out
            data = self._req("GET", nxt.replace(BASE, ""))

    # --- writes (gated) ---------------------------------------------------
    def _write(self, method: str, path: str, body: dict | None, app_id: str | None) -> Any:
        if app_id is not None:
            config.assert_app_allowed(app_id)
        if config.DRY_RUN:
            log.info("DRY_RUN %s %s %s", method, path, body)
            return {"dry_run": True, "method": method, "path": path, "body": body}
        return self._req(method, path, json=body) if body is not None else self._req(method, path)

    def post(self, path: str, body: dict, *, app_id: str | None) -> Any:
        return self._write("POST", path, body, app_id)

    def patch(self, path: str, body: dict, *, app_id: str | None) -> Any:
        return self._write("PATCH", path, body, app_id)

    def delete(self, path: str, *, app_id: str | None) -> Any:
        return self._write("DELETE", path, None, app_id)

    # --- upload (reserve → PUT chunks → commit) ----------------------------
    def upload_asset(self, reserve_path: str, rel_type: str, rel_id: str, file_bytes: bytes,
                     file_name: str, *, app_id: str, rel_key: str | None = None) -> dict:
        """Generic ASC asset upload used for screenshots and review screenshots.

        Apple hands back `uploadOperations` (method/url/length/offset/headers); we execute them,
        then PATCH uploaded=true with the MD5 so Apple can verify.
        """
        import hashlib

        rel_key = rel_key or rel_type
        body = {
            "data": {
                "type": reserve_path.strip("/").split("/")[-1],
                "attributes": {"fileName": file_name, "fileSize": len(file_bytes)},
                "relationships": {rel_key: {"data": {"type": rel_type, "id": rel_id}}},
            }
        }
        reserved = self.post(reserve_path, body, app_id=app_id)
        if reserved.get("dry_run"):
            return reserved
        rid = reserved["data"]["id"]
        for op in reserved["data"]["attributes"]["uploadOperations"]:
            chunk = file_bytes[op["offset"]: op["offset"] + op["length"]]
            headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
            httpx.request(op["method"], op["url"], content=chunk, headers=headers, timeout=120).raise_for_status()
        self.patch(
            f"{reserve_path}/{rid}",
            {"data": {"type": body["data"]["type"], "id": rid,
                      "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(file_bytes).hexdigest()}}},
            app_id=app_id,
        )
        return self.get(f"{reserve_path}/{rid}")
