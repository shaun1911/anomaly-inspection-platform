"""历史图导入（T0-3）。

落地目录结构（Gate 0 交付物，约定好就不再变）::

    data/landing/<code>/ok/<part_no>_<n>.jpg
    data/landing/<code>/ng/<part_no>_<n>.jpg

规则：
- ``code`` 必须是已存在且启用的 ``product_code``，否则整条拒绝；
- 只收 ``.jpg/.jpeg/.png``，单文件 < 20 MB，且能被 PIL 打开；
- 按 sha256 去重：同一模型内重复的跳过，不覆盖；
- 切分用 sha256 的确定性规则（同一张图永远落同一边），保证可复现；
- 导入不写图片副本，只写元数据；文件留在落地目录，由存储层按需搬运。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .store import tx

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_BYTES = 20 * 1024 * 1024

# 设计文档：正常品 20% 进冻结验收集，缺陷图 50%
DEFAULT_VAL_RATIO = {"ok": 0.2, "ng": 0.5}


@dataclass
class ImportReport:
    imported_train: int = 0
    imported_val: int = 0
    skipped_duplicate: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_imported(self) -> int:
        return self.imported_train + self.imported_val


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_for(sha: str, label: str, ratios: dict[str, float]) -> str:
    bucket = int(sha[:8], 16) % 100
    return "frozen_val" if bucket < ratios[label] * 100 else "train"


def _validate(path: Path) -> str | None:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return "unsupported_extension"
    if path.stat().st_size > MAX_BYTES:
        return "too_large"
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception:  # noqa: BLE001 - 任何解码失败都算坏图
        return "unreadable_image"
    return None


def import_landing(
    conn,
    landing: Path,
    model_id: int,
    ratios: dict[str, float] | None = None,
) -> ImportReport:
    """扫描落地目录并写入 dataset_item。重复调用安全。"""
    ratios = ratios or DEFAULT_VAL_RATIO
    report = ImportReport()
    landing = Path(landing)
    if not landing.is_dir():
        raise FileNotFoundError(f"落地目录不存在: {landing}")

    for code_dir in sorted(p for p in landing.iterdir() if p.is_dir()):
        code = code_dir.name
        row = conn.execute(
            "SELECT id, active FROM product_code WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            report.rejected.append((str(code_dir), "unknown_code"))
            continue
        if not row["active"]:
            report.rejected.append((str(code_dir), "inactive_code"))
            continue

        for label_dir in sorted(p for p in code_dir.iterdir() if p.is_dir()):
            label = label_dir.name.lower()
            if label not in ("ok", "ng"):
                report.rejected.append((str(label_dir), "unknown_label"))
                continue

            for path in sorted(p for p in label_dir.iterdir() if p.is_file()):
                reason = _validate(path)
                if reason is not None:
                    report.rejected.append((str(path), reason))
                    continue

                sha = _sha256(path)
                split = _split_for(sha, label, ratios)
                try:
                    with tx(conn):
                        conn.execute(
                            "INSERT INTO import_item"
                            " (model_id, source_type, source_id, split, sha256)"
                            " VALUES (?, 'import', ?, ?, ?)",
                            (model_id, str(path), split, sha),
                        )
                except Exception as exc:  # noqa: BLE001 - 唯一约束即重复
                    if "UNIQUE" in str(exc):
                        report.skipped_duplicate += 1
                        continue
                    raise

                if split == "frozen_val":
                    report.imported_val += 1
                else:
                    report.imported_train += 1

    return report
