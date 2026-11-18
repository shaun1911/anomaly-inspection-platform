-- 0015_down.sql
DROP INDEX IF EXISTS idx_roi_profile_active;
DROP TABLE IF EXISTS roi_profile;
DELETE FROM schema_version WHERE version = 15;
