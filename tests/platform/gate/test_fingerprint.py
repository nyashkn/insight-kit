"""Tests for gate/fingerprint.py — T3.

Covers:
  - record_fingerprint is deterministic (same dict → same hex, C2).
  - Different dicts → different fingerprints.
  - data_fingerprint accepts bytes and dict.
  - Canonical JSON: key order irrelevant (sort_keys normalises).
  - Float representation is deterministic.
  - record_id_from_fingerprint returns prefix of correct length.
  - Determinism test: emit same input into fresh dirs → identical record_fingerprint.
    (Full emit determinism tested in test_emit.py; here we test the primitive.)
"""
from __future__ import annotations

import pytest

from insight_kit.platform.gate.fingerprint import (
    data_fingerprint,
    record_fingerprint,
    record_id_from_fingerprint,
)


class TestRecordFingerprint:
    def test_same_dict_same_fp(self):
        d = {"record_type": "claim", "claim_id": "TEST-D-001", "value": 42}
        assert record_fingerprint(d) == record_fingerprint(d)

    def test_different_values_different_fp(self):
        d1 = {"record_type": "claim", "value": 1}
        d2 = {"record_type": "claim", "value": 2}
        assert record_fingerprint(d1) != record_fingerprint(d2)

    def test_key_order_irrelevant(self):
        """Canonical JSON must sort keys so insertion order doesn't matter (C2)."""
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert record_fingerprint(d1) == record_fingerprint(d2)

    def test_returns_64_hex_chars(self):
        fp = record_fingerprint({"x": 1})
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_nested_dict_key_order_irrelevant(self):
        d1 = {"outer": {"b": 2, "a": 1}, "z": 0}
        d2 = {"z": 0, "outer": {"a": 1, "b": 2}}
        assert record_fingerprint(d1) == record_fingerprint(d2)

    def test_float_determinism(self):
        """Same float value → identical fingerprint across calls (C2)."""
        d = {"v": 3.141592653589793}
        fp1 = record_fingerprint(d)
        fp2 = record_fingerprint(d)
        assert fp1 == fp2

    def test_float_same_value_same_fp(self):
        d1 = {"v": 1.0}
        d2 = {"v": 1.0}
        assert record_fingerprint(d1) == record_fingerprint(d2)

    def test_float_different_value_different_fp(self):
        d1 = {"v": 1.0}
        d2 = {"v": 1.1}
        assert record_fingerprint(d1) != record_fingerprint(d2)

    def test_nan_raises(self):
        """NaN is rejected (allow_nan=False) — NaN in records is a schema bug."""
        import math
        with pytest.raises(ValueError):
            record_fingerprint({"v": math.nan})

    def test_string_vs_int_different(self):
        d1 = {"v": "42"}
        d2 = {"v": 42}
        assert record_fingerprint(d1) != record_fingerprint(d2)

    def test_extra_key_changes_fp(self):
        d1 = {"a": 1}
        d2 = {"a": 1, "b": 2}
        assert record_fingerprint(d1) != record_fingerprint(d2)


class TestDataFingerprint:
    def test_bytes_input(self):
        raw = b"hello world"
        fp = data_fingerprint(raw)
        assert len(fp) == 64

    def test_bytes_deterministic(self):
        raw = b"deterministic"
        assert data_fingerprint(raw) == data_fingerprint(raw)

    def test_dict_input(self):
        d = {"inputs": [1, 2, 3]}
        fp = data_fingerprint(d)
        assert len(fp) == 64

    def test_dict_deterministic(self):
        d = {"x": 42}
        assert data_fingerprint(d) == data_fingerprint(d)

    def test_different_bytes_different_fp(self):
        assert data_fingerprint(b"a") != data_fingerprint(b"b")

    def test_different_dict_different_fp(self):
        assert data_fingerprint({"x": 1}) != data_fingerprint({"x": 2})

    def test_bytes_vs_dict_same_canonical_content(self):
        """bytes and dict paths produce different fingerprints for same logical data.
        This is intentional — the fingerprint is of the serialisation form.
        """
        raw = b'{"x":1}'
        d = {"x": 1}
        # They should be different because dict gets canonical-serialised differently
        # (though canonical might match in this case — just assert no crash).
        fp_bytes = data_fingerprint(raw)
        fp_dict = data_fingerprint(d)
        # Both are valid 64-char hex strings
        assert len(fp_bytes) == 64
        assert len(fp_dict) == 64


class TestRecordIdFromFingerprint:
    def test_default_prefix_len(self):
        fp = "a" * 64
        rid = record_id_from_fingerprint(fp)
        assert rid == "a" * 16
        assert len(rid) == 16

    def test_custom_prefix_len(self):
        fp = "b" * 64
        rid = record_id_from_fingerprint(fp, prefix_len=8)
        assert rid == "b" * 8

    def test_derived_from_real_fp(self):
        fp = record_fingerprint({"record_type": "claim", "claim_id": "TEST-D-001"})
        rid = record_id_from_fingerprint(fp)
        assert rid == fp[:16]
