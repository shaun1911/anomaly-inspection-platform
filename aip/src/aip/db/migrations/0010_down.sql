-- 0010_down.sql
ALTER TABLE case_item DROP COLUMN batch_source;
ALTER TABLE inference_job DROP COLUMN batch_source;
DELETE FROM schema_version WHERE version = 10;
