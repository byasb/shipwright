"""Replay mode — run the whole pipeline with no Apple account and no GCP project.

Two halves:
- RecordingASC: wraps the real client, dumps every GET response to a fixtures file.
  Run once by the maintainer (scripts/record_fixtures.py) against the real app record.
- ReplayASC + MemoryFirestore: serve those recordings back so anyone can execute the
  full agent tree (LLM calls stay live — bring a free Gemini API key). Writes never
  reach Apple: replay forces DRY_RUN, and ReplayASC has no credentials to write with.

Fixture key is "METHOD path?sorted-params". Lookup falls back to the bare path so
pagination cursors and field-list drift don't break replay.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

log = logging.getLogger("shipwright.replay")

# Redact by FIELD NAME, never by pattern: a digits regex corrupts UUIDs (44a53643-1738-… looks
# like a phone number) and a broken id silently degrades replay. Contact details in ASC responses
# live under well-known keys.
REDACT_KEYS = ("phone", "email", "firstname", "lastname", "contactname")


def _key(method: str, path: str, params: dict) -> str:
    q = "&".join(f"{k}={params[k]}" for k in sorted(params)) if params else ""
    return f"{method} {path}" + (f"?{q}" if q else "")


def _redact(obj: Any) -> Any:
    """Review contact details never enter a fixture; ids and everything else pass through intact."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if any(t in k.lower() for t in REDACT_KEYS) and isinstance(v, str) else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


class RecordingASC:
    def __init__(self, real, path: pathlib.Path):
        self._real, self._path = real, path
        self._gets: dict[str, Any] = {}

    def __getattr__(self, name):  # writes, uploads, token — pass through untouched
        return getattr(self._real, name)

    def get(self, path: str, **params) -> Any:
        r = self._real.get(path, **params)
        self._gets[_key("GET", path, params)] = _redact(r)
        return r

    def get_all(self, path: str, **params) -> list[dict]:
        r = self._real.get_all(path, **params)
        self._gets[_key("GET_ALL", path, params)] = _redact(r)
        return r

    def save(self, app_facts: dict, build_id: str) -> None:
        self._path.write_text(json.dumps({"app_facts": app_facts, "build_id": build_id, "gets": self._gets}, indent=1))
        log.info("recorded %d GET responses -> %s", len(self._gets), self._path)


class ReplayASC:
    """Reads come from the fixture; writes behave exactly like the real client in DRY_RUN."""

    def __init__(self, path: pathlib.Path):
        data = json.loads(path.read_text())
        self._gets = data["gets"]
        self.app_facts = data["app_facts"]
        self.build_id = data.get("build_id", "none")

    def _lookup(self, kind: str, path: str, params: dict) -> Any:
        k = _key(kind, path, params)
        if k in self._gets:
            return self._gets[k]
        bare = [v for key, v in self._gets.items() if key.split("?")[0] == f"{kind} {path}"]
        if bare:
            return bare[0]
        raise KeyError(f"no fixture for {k} — re-record with scripts/record_fixtures.py")

    def get(self, path: str, **params) -> Any:
        return self._lookup("GET", path, params)

    def get_all(self, path: str, **params) -> list[dict]:
        return self._lookup("GET_ALL", path, params)

    def _write(self, method: str, path: str, body: dict | None, app_id: str | None) -> Any:
        from . import config
        if app_id:
            config.assert_app_allowed(app_id)
        return {"dry_run": True, "method": method, "path": path, "body": body}

    def post(self, path: str, body: dict, *, app_id: str | None) -> Any:
        return self._write("POST", path, body, app_id)

    def patch(self, path: str, body: dict, *, app_id: str | None) -> Any:
        return self._write("PATCH", path, body, app_id)

    def delete(self, path: str, *, app_id: str | None) -> Any:
        return self._write("DELETE", path, None, app_id)

    def upload_asset(self, reserve_path: str, rel_type: str, rel_id: str, file_bytes: bytes,
                     file_name: str, *, app_id: str, rel_key: str | None = None) -> dict:
        # Same shape the real client returns on its DRY_RUN branch: the reserved-post payload.
        rel_key = rel_key or rel_type
        return self.post(reserve_path, {"data": {"type": reserve_path.strip("/").split("/")[-1],
                         "attributes": {"fileName": file_name, "fileSize": len(file_bytes)},
                         "relationships": {rel_key: {"data": {"type": rel_type, "id": rel_id}}}}}, app_id=app_id)


# --- Firestore stand-in ------------------------------------------------------

def _set_dotted(doc: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        doc = doc.setdefault(p, {})
    leaf = parts[-1]
    # google.cloud.firestore ArrayUnion carries .values
    values = getattr(value, "values", None)
    if values is not None and type(value).__name__ == "ArrayUnion":
        doc[leaf] = list(doc.get(leaf, [])) + list(values)
    else:
        doc[leaf] = value


class _Doc:
    def __init__(self, coll: dict, doc_id: str):
        self._coll, self.id = coll, doc_id

    def get(self):
        return self

    @property
    def exists(self) -> bool:
        return self.id in self._coll

    def to_dict(self) -> dict | None:
        return self._coll.get(self.id)

    def set(self, data: dict) -> None:
        self._coll[self.id] = json.loads(json.dumps(data, default=str))

    def update(self, fields: dict) -> None:
        doc = self._coll.setdefault(self.id, {})
        for k, v in fields.items():
            _set_dotted(doc, k, v)


class _Coll:
    def __init__(self, docs: dict):
        self._docs = docs

    def document(self, doc_id: str) -> _Doc:
        return _Doc(self._docs, doc_id)

    def where(self, filter=None):  # noqa: A002 — mirrors the Firestore API
        field = getattr(filter, "field_path", None) or getattr(filter, "_field_path", "")
        value = getattr(filter, "value", None) or getattr(filter, "_value", None)
        matches = [d for d in self._docs.values() if d.get(field) == value]
        class _Q:
            def limit(self, n):
                self._n = n
                return self
            def stream(self):
                for d in matches[: getattr(self, "_n", len(matches))]:
                    class _Snap:
                        def to_dict(inner):  # noqa: N805
                            return d
                    yield _Snap()
        return _Q()


class MemoryFirestore:
    """Just enough of google.cloud.firestore.Client for store.py. In-memory, single-process."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    def collection(self, name: str) -> _Coll:
        return _Coll(self._data.setdefault(name, {}))
