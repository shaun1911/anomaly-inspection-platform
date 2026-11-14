-- 0012_dataset_snapshot.sql — 数据集成员快照
-- checksum 只覆盖 (case_id, sha256)。要回答"冻结后哪条被改判"，
-- 还得在冻结时把每条的 verdict 与 sha256 一起存下来。

ALTER TABLE dataset_item ADD COLUMN verdict_at_freeze TEXT
    CHECK (verdict_at_freeze IN ('ok', 'ng'));
ALTER TABLE dataset_item ADD COLUMN sha256_at_freeze TEXT;
