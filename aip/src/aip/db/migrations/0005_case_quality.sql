-- 0005_case_quality.sql — 判例库数据质量
-- sha256：同码同图唯一，杜绝重复录入与"同图不同结论"；
-- source / result_id / model_version_id：可追溯到来源与当时判定的版本；
-- archived_at：软删，训练集可复现；
-- conflict：同图不同结论被拒时标记，进入待裁决。

ALTER TABLE case_item ADD COLUMN sha256 TEXT;
ALTER TABLE case_item ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('manual', 'result', 'import'));
ALTER TABLE case_item ADD COLUMN result_id INTEGER REFERENCES inference_result(id);
ALTER TABLE case_item ADD COLUMN model_version_id INTEGER REFERENCES model_version(id);
ALTER TABLE case_item ADD COLUMN archived_at TEXT;
ALTER TABLE case_item ADD COLUMN conflict INTEGER NOT NULL DEFAULT 0 CHECK (conflict IN (0, 1));

CREATE UNIQUE INDEX idx_case_code_sha ON case_item (product_code_id, sha256)
    WHERE sha256 IS NOT NULL;
CREATE INDEX idx_case_conflict ON case_item (conflict, created_at);
