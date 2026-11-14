-- 0001_down.sql — 回退 0001 初始 schema
-- 顺序与创建相反，避免外键依赖报错。

DROP TABLE IF EXISTS blind_item;
DROP TABLE IF EXISTS blind_batch;
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS dataset_item;
DROP TABLE IF EXISTS train_job;
DROP TABLE IF EXISTS case_item;
DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS inference_result;
DROP TABLE IF EXISTS inference_job;
DROP TABLE IF EXISTS station;
DROP TABLE IF EXISTS threshold_rev;
DROP TABLE IF EXISTS config_rev;
DROP TABLE IF EXISTS binding;
DROP TABLE IF EXISTS model_version;
DROP TABLE IF EXISTS model;
DROP TABLE IF EXISTS product_code;
DELETE FROM schema_version WHERE version = 1;
