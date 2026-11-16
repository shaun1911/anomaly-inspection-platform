-- 0013_model_onnx_meta.sql — 每版本 ONNX 输入/聚合方式
-- 不同训练后端导出的模型输入尺度不同（stub=pm1，anomalib=0~1），
-- 必须跟版本走，不能只靠全局设置。

ALTER TABLE model_version ADD COLUMN onnx_input_range TEXT;
ALTER TABLE model_version ADD COLUMN onnx_aggregate TEXT;
