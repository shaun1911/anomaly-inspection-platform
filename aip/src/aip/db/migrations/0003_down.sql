-- 0003_down.sql
DROP INDEX IF EXISTS idx_product_active;
ALTER TABLE product_code DROP COLUMN archived_at;
DELETE FROM schema_version WHERE version = 3;
