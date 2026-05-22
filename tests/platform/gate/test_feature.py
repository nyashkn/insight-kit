"""T14 — ik_feature_get provisional-feature return on catalog miss (V18).

V18: on catalog miss, ik_feature_get returns a provisional in-session feature
tagged provenance: provisional. Claims built on a provisional feature are forced
to draft and cannot promote to published until the feature is merged +
data_eng-certified. The loop never stalls on a human PR.

Cites: V18.
"""
from __future__ import annotations

import pytest

from insight_kit.gate import ProvisionalFeature, ik_feature_get

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KNOWN_FEATURE_CATALOG: dict = {
    "active_users": {"dtype": "int64", "source": "h_dlt", "certified": True},
    "revenue_usd": {"dtype": "float64", "source": "h_dlt", "certified": True},
}


# ---------------------------------------------------------------------------
# Miss path — provisional return
# ---------------------------------------------------------------------------


class TestFeatureGetMiss:
    def test_miss_returns_provisional_feature(self):
        """Catalog miss → returns a ProvisionalFeature, not None/raises."""
        result = ik_feature_get("unknown_metric", catalog=KNOWN_FEATURE_CATALOG)
        assert isinstance(result, ProvisionalFeature)

    def test_provisional_tagged_provenance_provisional(self):
        """Returned feature has provenance: provisional tag (V18)."""
        result = ik_feature_get("mystery_col", catalog=KNOWN_FEATURE_CATALOG)
        assert result.provenance == "provisional"

    def test_provisional_carries_feature_name(self):
        """Provisional feature retains the requested name."""
        result = ik_feature_get("my_new_metric", catalog=KNOWN_FEATURE_CATALOG)
        assert result.name == "my_new_metric"

    def test_miss_on_empty_catalog(self):
        """Empty catalog → miss → provisional."""
        result = ik_feature_get("anything", catalog={})
        assert isinstance(result, ProvisionalFeature)
        assert result.provenance == "provisional"

    def test_miss_on_none_catalog(self):
        """None catalog (default) → miss → provisional."""
        result = ik_feature_get("some_metric")
        assert isinstance(result, ProvisionalFeature)


# ---------------------------------------------------------------------------
# Hit path — certified feature returned
# ---------------------------------------------------------------------------


class TestFeatureGetHit:
    def test_hit_returns_non_provisional(self):
        """Catalog hit → returned object is NOT a provisional."""
        result = ik_feature_get("active_users", catalog=KNOWN_FEATURE_CATALOG)
        # Must not be ProvisionalFeature on a hit
        assert not isinstance(result, ProvisionalFeature)

    def test_hit_carries_catalog_data(self):
        """Catalog hit → returned feature reflects catalog metadata."""
        result = ik_feature_get("revenue_usd", catalog=KNOWN_FEATURE_CATALOG)
        assert result.name == "revenue_usd"

    def test_hit_does_not_set_provisional_provenance(self):
        """Catalog hit → provenance is NOT 'provisional'."""
        result = ik_feature_get("active_users", catalog=KNOWN_FEATURE_CATALOG)
        assert result.provenance != "provisional"


# ---------------------------------------------------------------------------
# Draft-lock — claims on provisional must stay draft (V18)
# ---------------------------------------------------------------------------


class TestDraftLock:
    def test_provisional_is_draft_locked(self):
        """ProvisionalFeature.draft_locked is True — signals claim must stay draft."""
        feat = ik_feature_get("unregistered_kpi", catalog={})
        assert feat.draft_locked is True

    def test_non_provisional_is_not_draft_locked(self):
        """Certified catalog feature is NOT draft-locked."""
        feat = ik_feature_get("active_users", catalog=KNOWN_FEATURE_CATALOG)
        assert feat.draft_locked is False

    def test_provisional_cannot_promote_to_published(self):
        """ProvisionalFeature.can_publish() returns False."""
        feat = ik_feature_get("draft_metric", catalog={})
        assert feat.can_publish() is False

    def test_certified_feature_can_publish(self):
        """Certified feature.can_publish() returns True."""
        feat = ik_feature_get("active_users", catalog=KNOWN_FEATURE_CATALOG)
        assert feat.can_publish() is True


# ---------------------------------------------------------------------------
# Certification check — data_eng_certified (V18)
# ---------------------------------------------------------------------------


class TestCertification:
    def test_provisional_not_certified(self):
        """ProvisionalFeature.data_eng_certified is False."""
        feat = ik_feature_get("new_col", catalog={})
        assert feat.data_eng_certified is False

    def test_catalog_hit_is_certified(self):
        """Known certified catalog feature has data_eng_certified True."""
        feat = ik_feature_get("active_users", catalog=KNOWN_FEATURE_CATALOG)
        assert feat.data_eng_certified is True

    def test_uncertified_catalog_feature_is_draft_locked(self):
        """A catalog feature with certified=False → draft_locked."""
        catalog = {"beta_metric": {"dtype": "float64", "source": "manual", "certified": False}}
        feat = ik_feature_get("beta_metric", catalog=catalog)
        assert feat.draft_locked is True
        assert feat.can_publish() is False


# ---------------------------------------------------------------------------
# Loop-never-stalls (V18) — miss must not raise, must not block
# ---------------------------------------------------------------------------


class TestLoopNeverStalls:
    def test_miss_never_raises(self):
        """ik_feature_get must never raise on a catalog miss (loop-never-stalls)."""
        try:
            result = ik_feature_get("nonexistent_feature", catalog={})
        except Exception as exc:
            pytest.fail(f"ik_feature_get raised on catalog miss: {exc}")
        assert result is not None

    def test_multiple_misses_each_return_provisional(self):
        """Multiple misses each independently return a provisional (no shared state)."""
        r1 = ik_feature_get("feat_a", catalog={})
        r2 = ik_feature_get("feat_b", catalog={})
        assert r1.name == "feat_a"
        assert r2.name == "feat_b"
        assert r1 is not r2

    def test_provisional_in_session_tag(self):
        """ProvisionalFeature carries in_session=True — valid only for current run."""
        feat = ik_feature_get("session_only_metric", catalog={})
        assert feat.in_session is True
