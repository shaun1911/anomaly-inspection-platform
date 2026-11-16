"""真实训练 worker 的阈值标定与切分不变量。"""

from __future__ import annotations

from aip.training.anomalib_worker import pick_thresholds


def test_thresholds_prefer_recall_under_overkill():
    ok = [0.10, 0.15, 0.20, 0.25, 0.30]
    ng = [0.55, 0.60, 0.70, 0.90]
    out = pick_thresholds(ok, ng, max_overkill=0.05)
    assert out["recall"] == 1.0
    assert out["overkill"] == 0.0
    assert out["th_lo"] < out["th_hi"]
    assert out["rule"] == "max_recall_under_overkill"


def test_thresholds_fallback_when_budget_impossible():
    ok = [0.90, 0.91, 0.92]
    ng = [0.10, 0.20]
    out = pick_thresholds(ok, ng, max_overkill=0.0)
    assert out["rule"] == "best_f1_fallback"
    assert 0.0 <= out["th_lo"] < out["th_hi"] <= 1.0
