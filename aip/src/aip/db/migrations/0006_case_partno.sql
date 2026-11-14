-- 0006_case_partno.sql — 判例按件聚合
-- 同一件可能被拍多张，判例应以"件"为粒度：part_no 唯一（同编码下）。
-- sha256 仍保留，处理"没有件号但图重复"的场景。

ALTER TABLE case_item ADD COLUMN part_no TEXT;

CREATE UNIQUE INDEX idx_case_code_part ON case_item (product_code_id, part_no)
    WHERE part_no IS NOT NULL;
