-- 0003_product_archive.sql — 产品编码归档
-- 停用（active=0）：不再接受推图，但仍在列表里，可随时启用。
-- 归档（archived_at 非空）：从默认列表与选择器消失，只能显式查看；有活跃绑定时禁止归档。

ALTER TABLE product_code ADD COLUMN archived_at TEXT;

CREATE INDEX idx_product_active ON product_code (active, archived_at);
