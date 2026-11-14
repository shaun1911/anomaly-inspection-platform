-- 0009_dataset.sql — L3 数据集容器
-- 数据集是训练集快照：一个族、一个模型、一组冻结的判例。
-- 冻结后不可增删，checksum = 有序 (case_id:sha256) 的哈希，用于训练复现。

DROP TABLE IF EXISTS dataset_item;

CREATE TABLE dataset (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    family_id   INTEGER REFERENCES family(id),
    model_id    INTEGER NOT NULL REFERENCES model(id),
    status      TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'frozen')),
    note        TEXT,
    checksum    TEXT,
    frozen_at   TEXT,
    created_by  TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE dataset_item (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES dataset(id),
    case_id    INTEGER NOT NULL REFERENCES case_item(id),
    split      TEXT    NOT NULL DEFAULT 'train' CHECK (split IN ('train', 'frozen_val')),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (dataset_id, case_id)
);

CREATE INDEX idx_dataset_status ON dataset (status, created_at);
CREATE INDEX idx_dataset_item_case ON dataset_item (case_id);

ALTER TABLE train_job ADD COLUMN dataset_id INTEGER REFERENCES dataset(id);
ALTER TABLE model_version ADD COLUMN dataset_id INTEGER REFERENCES dataset(id);

-- 外部图片导入清单（原 dataset_item 的职责，与 L3 数据集解耦）
CREATE TABLE import_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER NOT NULL REFERENCES model(id),
    source_type TEXT    NOT NULL CHECK (source_type IN ('case', 'result', 'import')),
    source_id   TEXT,
    split       TEXT    NOT NULL CHECK (split IN ('train', 'frozen_val')),
    sha256      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (model_id, sha256)
);
