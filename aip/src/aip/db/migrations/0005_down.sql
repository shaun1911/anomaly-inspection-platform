-- 0005_down.sql
DROP INDEX IF EXISTS idx_case_conflict;
DROP INDEX IF EXISTS idx_case_code_sha;
ALTER TABLE case_item DROP COLUMN conflict;
ALTER TABLE case_item DROP COLUMN archived_at;
ALTER TABLE case_item DROP COLUMN model_version_id;
ALTER TABLE case_item DROP COLUMN result_id;
ALTER TABLE case_item DROP COLUMN source;
ALTER TABLE case_item DROP COLUMN sha256;
DELETE FROM schema_version WHERE version = 5;
