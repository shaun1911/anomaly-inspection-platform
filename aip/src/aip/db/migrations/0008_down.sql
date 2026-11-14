-- 0008_down.sql
DROP INDEX IF EXISTS idx_case_batch;
DROP INDEX IF EXISTS idx_job_batch;
ALTER TABLE case_item DROP COLUMN batch_no;
ALTER TABLE inference_job DROP COLUMN batch_no;
DELETE FROM schema_version WHERE version = 8;
