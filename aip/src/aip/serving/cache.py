"""模型缓存与资源释放（按需加载 + 引用计数 + 空闲回收）。

策略：
1. 扫码换型/推图时 acquire：同一 (model, version) 只加载一次，多个站位共享；
2. 引用计数：每个站位对条目持有一个引用，重复使用刷新该站位的最后使用时间；
3. 空闲回收：站位引用超过 TTL 未刷新则释放；条目无引用且空闲超 TTL → 卸载；
4. 容量保护：条目数达到上限时，优先卸载"无引用且最久未用"的；全被引用则拒绝加载；
5. 手动卸载：管理页可强制卸载并留审计；
6. 卸载 = 丢弃 session 引用并 gc，让底层（ONNX arena / torch）释放显存。
"""

from __future__ import annotations

import gc
import threading
import time
from dataclasses import dataclass, field

from ..audit import record
from ..store import tx


@dataclass
class Entry:
    key: str
    model_id: int
    version_no: int
    onnx_path: str | None
    session: object
    loaded_at: float
    last_used: float
    stations: dict[str, float] = field(default_factory=dict)


class CacheFull(Exception):
    pass


def _default_loader(onnx_path: str | None):
    if not onnx_path:
        return None
    from ..inference.onnx import load_session

    return load_session(onnx_path)


class ModelCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        self.ttl_s: float = 900
        self.max_models: int = 4
        self.loader = _default_loader
        self.loads = 0
        self.unloads = 0

    def configure(self, ttl_minutes: int, max_models: int) -> None:
        self.ttl_s = max(1, int(ttl_minutes)) * 60
        self.max_models = max(1, int(max_models))

    def _drop_stale_stations(self, entry: Entry, now: float) -> None:
        stale = [s for s, ts in entry.stations.items() if now - ts > self.ttl_s]
        for s in stale:
            entry.stations.pop(s, None)

    def _unload(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        entry.session = None
        self.unloads += 1
        gc.collect()

    def tick(self, now: float | None = None) -> list[str]:
        """释放过期站位引用，卸载无引用且空闲超 TTL 的条目。返回被卸载的 key。"""
        now = time.time() if now is None else now
        dropped: list[str] = []
        with self._lock:
            for key, entry in list(self._entries.items()):
                self._drop_stale_stations(entry, now)
                if not entry.stations and now - entry.last_used > self.ttl_s:
                    self._unload(key)
                    dropped.append(key)
        return dropped

    def acquire(self, model_id: int, version_no: int, onnx_path: str | None, station: str,
                now: float | None = None) -> tuple[object, bool]:
        now = time.time() if now is None else now
        self.tick(now)
        key = f"{model_id}:{version_no}"
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.stations[station] = now
                entry.last_used = now
                return entry.session, False

            if len(self._entries) >= self.max_models:
                idle = [e for e in self._entries.values() if not e.stations]
                if not idle:
                    raise CacheFull(
                        f"模型缓存已满（{self.max_models} 个），且全部被站位引用"
                    )
                victim = min(idle, key=lambda e: e.last_used)
                self._unload(victim.key)

            session = self.loader(onnx_path) if self.loader else None
            entry = Entry(
                key=key, model_id=model_id, version_no=version_no, onnx_path=onnx_path,
                session=session, loaded_at=now, last_used=now, stations={station: now},
            )
            self._entries[key] = entry
            self.loads += 1
            return session, True

    def touch(self, station: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            for entry in self._entries.values():
                if station in entry.stations:
                    entry.stations[station] = now
                    entry.last_used = now

    def unload(self, key: str, force: bool = False) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.stations and not force:
                return False
            self._unload(key)
            return True

    def entries(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        with self._lock:
            return [
                {
                    "key": e.key,
                    "model_id": e.model_id,
                    "version_no": e.version_no,
                    "onnx_path": e.onnx_path,
                    "stations": sorted(e.stations),
                    "refs": len(e.stations),
                    "loaded_at": e.loaded_at,
                    "idle_s": round(now - e.last_used, 1),
                }
                for e in self._entries.values()
            ]


cache = ModelCache()


def acquire_and_audit(conn, model_id: int, version_no: int, onnx_path: str | None,
                      station: str) -> tuple[object, bool]:
    """加载/复用模型，并在真正新加载时留审计。"""
    session, loaded = cache.acquire(model_id, version_no, onnx_path, station)
    if loaded:
        with tx(conn):
            record(conn, actor=station, action="model.load", entity="model_version",
                   entity_id=f"{model_id}:{version_no}",
                   payload={"onnx": bool(onnx_path), "stations": [station]})
    return session, loaded


def unload_and_audit(conn, key: str, actor: str = "web", force: bool = False) -> bool:
    ok = cache.unload(key, force=force)
    if ok:
        with tx(conn):
            record(conn, actor=actor, action="model.unload", entity="model_version",
                   entity_id=key, payload={"force": force})
    return ok
