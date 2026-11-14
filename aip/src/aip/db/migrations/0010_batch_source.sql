-- 0010_batch_source.sql — 批次来源
-- station：判定时由工位提交；backfill：事后补录。补录必须可识别，否则按批统计分不清真伪。

ALTER TABLE inference_job ADD COLUMN batch_source TEXT
    CHECK (batch_source IN ('station', 'backfill', 'manual'));
ALTER TABLE case_item ADD COLUMN batch_source TEXT
    CHECK (batch_source IN ('station', 'backfill', 'manual'));

UPDATE inference_job SET batch_source = 'station' WHERE batch_no IS NOT NULL;
UPDATE case_item SET batch_source = 'station' WHERE batch_no IS NOT NULL;
