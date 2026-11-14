-- 0004_down.sql
DROP INDEX IF EXISTS idx_review_state;
ALTER TABLE inference_result DROP COLUMN claimed_at;
ALTER TABLE inference_result DROP COLUMN claimed_by;
ALTER TABLE inference_result DROP COLUMN review_status;
DELETE FROM schema_version WHERE version = 4;
