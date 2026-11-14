-- 0012_down.sql
ALTER TABLE dataset_item DROP COLUMN sha256_at_freeze;
ALTER TABLE dataset_item DROP COLUMN verdict_at_freeze;
DELETE FROM schema_version WHERE version = 12;
