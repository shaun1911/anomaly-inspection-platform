-- 0008_batch.sql — 批次贯通
-- 批次 = 来料/生产/送检批次。判定时确定，判例继承，用于按批追溯与"旧光照数据不进训练"。

ALTER TABLE inference_job ADD COLUMN batch_no TEXT;
ALTER TABLE case_item ADD COLUMN batch_no TEXT;

CREATE INDEX idx_job_batch ON inference_job (code, batch_no, created_at);
CREATE INDEX idx_case_batch ON case_item (batch_no, created_at);
