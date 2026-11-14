-- 0006_down.sql
DROP INDEX IF EXISTS idx_case_code_part;
ALTER TABLE case_item DROP COLUMN part_no;
DELETE FROM schema_version WHERE version = 6;
