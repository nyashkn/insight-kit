"""T14 — ik_feature_get: provisional-feature return on catalog miss (V18).

On a catalog miss, ik_feature_get returns a ProvisionalFeature tagged
provenance: provisional.  Claims built on a provisional feature are forced to
draft and cannot promote to published until the feature is merged and
data_eng-certified.  The loop never stalls on a human PR.

A certified catalog hit returns a CertifiedFeature (provenance != "provisional",
draft_locked = False, can_publish() = True).

This module imports NO hamilton, NO pi.  Pure Python stdlib + dataclasses.

Cites: V18, C1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Feature result types
# ---------------------------------------------------------------------------


@dataclass
class ProvisionalFeature:
    """A provisional in-session feature returned on a catalog miss (V18).

    provenance: always "provisional".
    draft_locked: always True — any claim built on this feature must stay draft.
    data_eng_certified: always False — not yet registered in the catalog.
    in_session: always True — valid only for the current run session.

    can_publish() → False — the loop never stalls: the claim proceeds as draft,
    but promotion to published requires the feature to be merged + certified.
    """

    name: str
    provenance: str = field(default="provisional", init=False)
    draft_locked: bool = field(default=True, init=False)
    data_eng_certified: bool = field(default=False, init=False)
    in_session: bool = field(default=True, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_publish(self) -> bool:
        """Provisional features cannot be published (V18 draft-lock).

        Returns False always — the claim is draft-locked until the feature
        is merged into the catalog and data_eng-certified.
        """
        return False


@dataclass
class CertifiedFeature:
    """A certified feature found in the catalog.

    provenance: "catalog".
    draft_locked: False unless certified=False in the catalog entry.
    data_eng_certified: reflects the catalog entry's certified flag.
    in_session: False — this is a persistent catalog feature.
    """

    name: str
    provenance: str = field(default="catalog", init=False)
    in_session: bool = field(default=False, init=False)
    data_eng_certified: bool = True
    draft_locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_publish(self) -> bool:
        """Certified + not draft-locked features may be published.

        Returns True iff data_eng_certified and not draft_locked.
        """
        return self.data_eng_certified and not self.draft_locked


# ---------------------------------------------------------------------------
# ik_feature_get — catalog lookup with provisional fallback
# ---------------------------------------------------------------------------


def ik_feature_get(
    name: str,
    catalog: dict[str, Any] | None = None,
) -> ProvisionalFeature | CertifiedFeature:
    """Look up a feature by name; return provisional on miss (V18).

    Args:
        name:    feature name to look up.
        catalog: optional dict mapping feature name → metadata dict with keys:
                   - "certified": bool — whether data_eng has certified this feature.
                   - (any other metadata keys are stored verbatim).
                 If None or empty, every lookup is a miss → ProvisionalFeature.

    Returns:
        CertifiedFeature  if name found in catalog and certified=True.
        ProvisionalFeature (draft_locked, provenance="provisional") on any miss,
          or if catalog entry has certified=False.

    Never raises on a miss — V18 "loop never stalls on a human PR".
    The caller may proceed with the provisional feature immediately.
    """
    if catalog is not None and name in catalog:
        entry = catalog[name]
        certified = bool(entry.get("certified", False))
        meta = {k: v for k, v in entry.items() if k != "certified"}

        if certified:
            return CertifiedFeature(
                name=name,
                data_eng_certified=True,
                draft_locked=False,
                metadata=meta,
            )
        else:
            # In catalog but not certified — treat as provisional (draft-locked)
            feat = ProvisionalFeature(name=name, metadata=meta)
            return feat

    # Catalog miss → provisional (V18)
    return ProvisionalFeature(name=name)
