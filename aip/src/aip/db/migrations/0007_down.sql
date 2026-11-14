-- 0007_down.sql
ALTER TABLE product_code ADD COLUMN family TEXT;
UPDATE product_code
SET family = (SELECT f.name FROM family f WHERE f.id = product_code.family_id);
DROP INDEX IF EXISTS idx_product_family;
ALTER TABLE product_code DROP COLUMN family_id;
DROP TABLE IF EXISTS family;
DELETE FROM schema_version WHERE version = 7;
