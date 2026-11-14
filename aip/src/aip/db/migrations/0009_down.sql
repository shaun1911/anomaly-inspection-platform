-- 0009_down.sql
ALTER TABLE model_version DROP COLUMN dataset_id;
ALTER TABLE train_job DROP COLUMN dataset_id;
DROP INDEX IF EXISTS idx_dataset_item_case;
DROP INDEX IF EXISTS idx_dataset_status;
DROP TABLE IF EXISTS dataset_item;
DROP TABLE IF EXISTS dataset;

DROP TABLE IF EXISTS import_item;

-- 恢复 0001 的旧表结构
CREATE TABLE dataset_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER NOT NULL REFERENCES model(id),
    source_type TEXT    NOT NULL CHECK (source_type IN ('case', 'result', 'import')),
    source_id   TEXT,
    split       TEXT    NOT NULL CHECK (split IN ('train', 'frozen_val')),
    sha256      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (model_id, sha256)
);
DELETE FROM schema_version WHERE version = 9;
