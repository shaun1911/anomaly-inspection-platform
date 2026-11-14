-- 0007_family.sql — 产品族升级为实体
-- 编码必须能回答"属于哪个族"；族名唯一，杜绝"支架/支架 /ZJ"这类变体。
-- 旧 family 文本迁入 family 表后删除，避免两个事实来源。

CREATE TABLE family (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

ALTER TABLE product_code ADD COLUMN family_id INTEGER REFERENCES family(id);

INSERT INTO family (name)
SELECT DISTINCT trim(family) FROM product_code
WHERE family IS NOT NULL AND trim(family) <> '';

UPDATE product_code
SET family_id = (SELECT f.id FROM family f WHERE f.name = trim(product_code.family))
WHERE family IS NOT NULL AND trim(family) <> '';

ALTER TABLE product_code DROP COLUMN family;

CREATE INDEX idx_product_family ON product_code (family_id);
