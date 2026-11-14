-- 0002_down.sql
DROP TABLE IF EXISTS setting;
DELETE FROM schema_version WHERE version = 2;
