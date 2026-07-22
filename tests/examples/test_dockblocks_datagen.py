"""dockblocks_demo generator — determinism, ground truth, planted trap, parquet.

Pure pyarrow + stdlib: runs everywhere the gate runs, no hamilton needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.examples.dockblocks_demo import datagen


def test_same_seed_same_bytes() -> None:
    """generate() is bit-stable per seed — the whole point of a seeded fixture."""
    a = datagen.generate(seed=7, days=30)
    b = datagen.generate(seed=7, days=30)
    for name, table in a.tables().items():
        assert table.equals(b.tables()[name]), f"{name} differs across identical seeds"
    assert a.ground_truth == b.ground_truth


def test_different_seed_different_data() -> None:
    a = datagen.generate(seed=7, days=30)
    b = datagen.generate(seed=8, days=30)
    assert not a.orders.equals(b.orders)


def test_ground_truth_is_internally_consistent() -> None:
    """Ground truth is computed from the rows, so the identities hold exactly."""
    demo = datagen.generate(seed=42, days=60)
    gt = demo.ground_truth

    spend = sum(demo.meta_ads.column("spend_kes").to_pylist()) + sum(
        demo.google_ads.column("spend_kes").to_pylist()
    )
    new_customers = sum(
        1 for i in demo.orders.column("customer_order_index").to_pylist() if i == 1
    )
    assert gt["total_spend_kes"] == pytest.approx(spend)
    assert gt["new_customers"] == new_customers
    assert gt["cac_kes"] == pytest.approx(spend / new_customers)
    assert gt["mer"] == pytest.approx(gt["revenue_kes"] / spend)


def test_p5_trap_is_planted() -> None:
    """Returning customers exist in-window, so naive CAC lands below true CAC."""
    demo = datagen.generate(seed=42, days=60)
    gt = demo.ground_truth
    assert gt["distinct_customers"] > gt["new_customers"]  # trap material present
    assert gt["naive_cac_kes"] < gt["cac_kes"]  # and it biases CAC downward


def test_scale_grows_volume() -> None:
    small = datagen.generate(seed=1, days=20, scale=1.0)
    big = datagen.generate(seed=1, days=20, scale=3.0)
    assert len(big.orders) > len(small.orders)
    assert len(big.email_events) > len(small.email_events)


def test_write_parquet_roundtrip(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    demo = datagen.generate(seed=3, days=10)
    paths = demo.write_parquet(tmp_path / "fixture")
    assert set(paths) == set(demo.tables())
    for name, path in paths.items():
        assert path.exists()
        assert pq.read_table(path).equals(demo.tables()[name])
