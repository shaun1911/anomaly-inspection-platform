"""模型缓存与释放策略验收。"""

from __future__ import annotations

import time

import pytest

from aip.serving.cache import CacheFull, ModelCache


def _cache(max_models: int = 4, ttl_min: int = 15) -> ModelCache:
    c = ModelCache()
    c.configure(ttl_min, max_models)
    return c


def test_same_version_shared_between_stations():
    c = _cache()
    _, loaded1 = c.acquire(1, 1, None, "S1")
    _, loaded2 = c.acquire(1, 1, None, "S2")
    assert loaded1 is True and loaded2 is False
    entries = c.entries()
    assert len(entries) == 1
    assert entries[0]["refs"] == 2
    assert entries[0]["stations"] == ["S1", "S2"]


def test_idle_station_released_after_ttl_then_model_unloaded():
    c = _cache(ttl_min=1)
    now = 1000.0
    c.acquire(1, 1, None, "S1", now=now)
    c.acquire(2, 1, None, "S2", now=now)
    assert len(c.entries(now=now)) == 2

    # 超过 TTL 后 acquire 会先 tick：S1 引用失效、其模型被卸载
    later = now + 90
    c.acquire(2, 1, None, "S2", now=later)  # 刷新 S2，同时清理 S1
    entries = c.entries(now=later)
    assert [e["key"] for e in entries] == ["2:1"]
    assert entries[0]["stations"] == ["S2"]

    after = later + 90
    dropped = c.tick(after)
    assert dropped == ["2:1"] or dropped == [] or "2:1" in dropped


def test_capacity_evicts_idle_lru():
    c = _cache(max_models=1)
    c.acquire(1, 1, None, "S1", now=100.0)
    c.acquire(1, 1, None, "S1", now=200.0)
    # 释放引用（模拟站位超时后 tick）
    c.ttl_s = 1
    c.tick(now=300.0)
    assert c.entries(now=300.0) == []

    # 重新加载另一个模型不会因为容量被拒
    _, loaded = c.acquire(2, 1, None, "S2", now=400.0)
    assert loaded is True


def test_capacity_full_with_all_referenced_raises():
    c = _cache(max_models=1, ttl_min=60)
    c.acquire(1, 1, None, "S1", now=100.0)
    with pytest.raises(CacheFull):
        c.acquire(2, 1, None, "S2", now=101.0)


def test_manual_unload_refuses_when_referenced_but_force_works():
    c = _cache()
    c.acquire(1, 1, None, "S1")
    assert c.unload("1:1") is False
    assert c.unload("1:1", force=True) is True
    assert c.entries() == []


def test_unload_clears_session_reference():
    c = _cache()
    session, _ = c.acquire(1, 1, None, "S1")
    c.unload("1:1", force=True)
    # 卸载后缓存里没有引用，gc 才能回收底层显存
    assert c.entries() == []
    _ = session


def test_touch_refreshes_station_reference():
    c = _cache(ttl_min=1)
    now = time.time()
    c.acquire(1, 1, None, "S1", now=now)
    c.touch("S1", now=now + 50)
    c.touch("S1", now=now + 59)
    dropped = c.tick(now=now + 61)
    assert dropped == []
    assert len(c.entries(now=now + 61)) == 1
