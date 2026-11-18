-- 0014_feedback_workflow.sql — 误判上报处理闭环
-- 原 feedback 只有 (result_id, verdict, note, source)，只能记录不能处理。
ALTER TABLE feedback ADD COLUMN status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'accepted', 'rejected'));
ALTER TABLE feedback ADD COLUMN station TEXT;
ALTER TABLE feedback ADD COLUMN reported_by TEXT;
ALTER TABLE feedback ADD COLUMN reason_code TEXT;
ALTER TABLE feedback ADD COLUMN handled_by TEXT;
ALTER TABLE feedback ADD COLUMN handled_at TEXT;
ALTER TABLE feedback ADD COLUMN resolution TEXT;
