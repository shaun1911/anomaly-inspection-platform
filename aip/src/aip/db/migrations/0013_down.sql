ALTER TABLE model_version DROP COLUMN onnx_aggregate;
ALTER TABLE model_version DROP COLUMN onnx_input_range;
DELETE FROM schema_version WHERE version = 13;
