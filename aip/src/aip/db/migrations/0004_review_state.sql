-- 0004_review_state.sql — 复核状态机
-- pending：待处理；claimed：已领取（有超时）；done：已确认；skipped：暂缓。
-- claimed_at 超过 15 分钟视为释放，避免有人领了不处理把件锁死。

ALTER TABLE inference_result ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE inference_result ADD COLUMN claimed_by TEXT;
ALTER TABLE inference_result ADD COLUMN claimed_at TEXT;

CREATE INDEX idx_review_state ON inference_result (review_status, created_at);
