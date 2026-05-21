"""T3 — Content-address fingerprints.

record_fingerprint = sha256(canonical JSON of the record).
data_fingerprint   = sha256(arbitrary input bytes or dict).

Canonical JSON rules (C2 — deterministic, same input → identical bytes):
  - dict keys sorted recursively.
  - floats: repr() is used — Python's repr() is deterministic and round-trips.
  - No trailing whitespace; no BOM.
  - Encoding: UTF-8.

Cites: V4, C10.

Note: V6 full published fingerprint set (data/code/agent/env) is T7 — out of scope.
A clean seam is left: data_fingerprint accepts raw bytes or a dict.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def _canonical_default(obj: Any) -> Any:
    """JSON serialization fallback for non-standard scalar types.

    Plain Python floats are handled by the stdlib JSON encoder directly and never
    reach this function.  This fallback covers types that wrap a numeric value
    but are not natively JSON-serializable — specifically Decimal and numpy scalar
    types that implement __float__.  All other types raise TypeError.
    """
    if hasattr(obj, "__float__"):
        # Decimal / numpy scalar: coerce to Python float for deterministic repr.
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}")


def _nfc(s: str) -> str:
    """NFC-normalize a unicode string so NFC and NFD forms fingerprint identically."""
    return unicodedata.normalize("NFC", s)


def _nfc_normalize(data: Any) -> Any:
    """Recursively NFC-normalize all strings in a JSON-compatible structure."""
    if isinstance(data, str):
        return _nfc(data)
    if isinstance(data, dict):
        return {_nfc(k): _nfc_normalize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_nfc_normalize(item) for item in data]
    return data


def _canonical_dumps(data: Any) -> bytes:
    """Produce canonical UTF-8 JSON bytes.

    Rules:
      - Unicode strings NFC-normalized before serialization so that NFC and NFD
        representations of the same logical string produce identical bytes.
      - Keys sorted recursively (sort_keys=True propagates via json module).
      - No separators with trailing spaces (separators=(',', ':')).
      - ensure_ascii=False — preserve unicode as-is for round-trip fidelity.
      - floats: json module uses repr() internally for Python floats, which is
        deterministic in CPython 3.11+ (IEEE 754 shortest representation).
    """
    return json.dumps(
        _nfc_normalize(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_canonical_default,
        allow_nan=False,  # NaN/Inf in records is a schema bug, not a fingerprint concern
    ).encode("utf-8")


def record_fingerprint(record_dict: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of a record dict.

    The record_dict must be a plain Python dict (already serialized from pydantic).
    Returns hex string (64 chars).
    """
    canonical = _canonical_dumps(record_dict)
    return hashlib.sha256(canonical).hexdigest()


def data_fingerprint(inputs: bytes | dict[str, Any]) -> str:
    """sha256 of input data.

    inputs may be:
      - raw bytes  (e.g. parquet file contents, JSON blob)
      - dict       (will be canonical-serialized then hashed)

    Returns hex string (64 chars).
    """
    if isinstance(inputs, (bytes, bytearray)):
        raw = inputs
    else:
        raw = _canonical_dumps(inputs)
    return hashlib.sha256(raw).hexdigest()


def record_id_from_fingerprint(fp: str, prefix_len: int = 16) -> str:
    """Derive a content-addressed record id from a fingerprint hex string.

    Uses the first `prefix_len` characters of the sha256 hex digest.
    Default: 16 hex chars = 64 bits — collision-safe for realistic record volumes.
    """
    return fp[:prefix_len]
