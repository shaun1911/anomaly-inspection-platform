-- 0011_down.sql
ALTER TABLE blind_batch DROP COLUMN note;
ALTER TABLE blind_batch DROP COLUMN metrics_json;
ALTER TABLE blind_batch DROP COLUMN signed_tech;
ALTER TABLE blind_batch DROP COLUMN signed_line;
ALTER TABLE blind_batch DROP COLUMN signed_quality;
DELETE FROM schema_version WHERE version = 11;
