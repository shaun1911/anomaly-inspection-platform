-- 0011_blind_signoff.sql — 抽检批次的批次级签字与指标
-- 签字是"这批抽检有效"的凭据：质量 / 产线 / 技术三方，缺一不闭环。
-- 指标冻结在 metrics_json，事后不随判例变化而改写。

ALTER TABLE blind_batch ADD COLUMN signed_quality TEXT;
ALTER TABLE blind_batch ADD COLUMN signed_line TEXT;
ALTER TABLE blind_batch ADD COLUMN signed_tech TEXT;
ALTER TABLE blind_batch ADD COLUMN metrics_json TEXT;
ALTER TABLE blind_batch ADD COLUMN note TEXT;
