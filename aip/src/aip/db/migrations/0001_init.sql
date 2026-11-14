-- 0001_init.sql — AIP v1 初始 schema
-- 约定：
--   * 时间列一律 UTC ISO8601 文本（'YYYY-MM-DDTHH:MM:SS.sssZ'）
--   * 枚举用 CHECK 约束，不用整数
--   * 外键默认不级联删除；删除一律走软删或状态位
--   * 金额/分数用 REAL；计数用 INTEGER

PRAGMA foreign_keys = ON;

-- 产品编码：现场助记符，不可改，只能停用
CREATE TABLE product_code (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    family      TEXT,
    part        TEXT,
    seq         TEXT,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- 模型实体
CREATE TABLE model (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT,
    archived_at TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- 模型版本：阈值不在此表，见 threshold_rev
CREATE TABLE model_version (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER NOT NULL REFERENCES model(id),
    version_no  INTEGER NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'candidate'
                CHECK (status IN ('candidate', 'shadow', 'assist', 'disabled')),
    onnx_path   TEXT,
    metrics_json TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (model_id, version_no)
);

-- 绑定：一个编码同时只有一个生效行（active_to IS NULL）
CREATE TABLE binding (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code_id INTEGER NOT NULL REFERENCES product_code(id),
    model_id       INTEGER NOT NULL REFERENCES model(id),
    stage          TEXT    NOT NULL DEFAULT 'candidate'
                   CHECK (stage IN ('candidate', 'shadow', 'assist', 'disabled')),
    active_from    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    active_to      TEXT,
    bound_by       TEXT,
    note           TEXT
);
CREATE INDEX idx_binding_code_open ON binding (product_code_id, active_to);

-- 配置版本：ROI 与预处理，随版本成对下发
CREATE TABLE config_rev (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version_id INTEGER NOT NULL REFERENCES model_version(id),
    rev              INTEGER NOT NULL,
    roi_rect         TEXT    NOT NULL,          -- JSON [x1,y1,x2,y2]，原图像素
    preprocessing_json TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (model_version_id, rev)
);

-- 阈值版本：与 (model_version, roi_rev) 成对
CREATE TABLE threshold_rev (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version_id INTEGER NOT NULL REFERENCES model_version(id),
    roi_rev          INTEGER NOT NULL,
    rev              INTEGER NOT NULL,
    th_lo            REAL    NOT NULL,
    th_hi            REAL    NOT NULL,
    mode             TEXT    NOT NULL DEFAULT 'normal'
                     CHECK (mode IN ('normal', 'high_overkill')),
    reason           TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (model_version_id, roi_rev, rev),
    CHECK (th_hi >= th_lo OR mode = 'high_overkill')
);

-- 站位
CREATE TABLE station (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    last_config_rev TEXT,                        -- '{"model_version_id":3,"rev":2}'
    health          TEXT    NOT NULL DEFAULT 'ok'
                    CHECK (health IN ('ok', 'degraded', 'manual')),
    last_seen_at    TEXT
);

-- 判定任务
CREATE TABLE inference_job (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    part_no         TEXT,
    station_id      INTEGER REFERENCES station(id),
    idempotency_key TEXT    NOT NULL UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'done', 'failed', 'missed')),
    error_code      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    claimed_at      TEXT,
    done_at         TEXT
);
CREATE INDEX idx_job_status ON inference_job (status, created_at);

-- 判定结果
CREATE TABLE inference_result (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER NOT NULL UNIQUE REFERENCES inference_job(id),
    model_version_id INTEGER NOT NULL REFERENCES model_version(id),
    score            REAL    NOT NULL,
    label            TEXT    NOT NULL CHECK (label IN ('ok', 'gray', 'ng')),
    boxes_json       TEXT,
    roi_json         TEXT,
    crop_path        TEXT,
    thumb_path       TEXT,
    original_w       INTEGER,
    original_h       INTEGER,
    decode_ms        REAL,
    latency_ms       REAL,
    source           TEXT    NOT NULL DEFAULT 'system' CHECK (source IN ('system', 'legacy')),
    confirmed_by     TEXT,
    confirmed_at     TEXT,
    confirm_note     TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_result_created ON inference_result (created_at);
CREATE INDEX idx_result_version ON inference_result (model_version_id);

-- 现场反馈
CREATE TABLE feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id   INTEGER REFERENCES inference_result(id),
    verdict     TEXT    NOT NULL CHECK (verdict IN ('ok', 'ng')),
    note        TEXT,
    source      TEXT    NOT NULL DEFAULT 'online' CHECK (source IN ('online', 'late')),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX idx_feedback_online ON feedback (result_id) WHERE source = 'online';

-- 判例库（v1 只存判例，不做判据结构化）
CREATE TABLE case_item (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code_id INTEGER NOT NULL REFERENCES product_code(id),
    crop_path       TEXT    NOT NULL,
    verdict         TEXT    NOT NULL CHECK (verdict IN ('ok', 'ng')),
    reason          TEXT,
    adjudicator     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_case_code ON case_item (product_code_id, created_at);

-- 训练样本：来源可以是判例、结果或导入
CREATE TABLE dataset_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER NOT NULL REFERENCES model(id),
    source_type TEXT    NOT NULL CHECK (source_type IN ('case', 'result', 'import')),
    source_id   TEXT,
    split       TEXT    NOT NULL CHECK (split IN ('train', 'frozen_val')),
    sha256      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (model_id, sha256)
);

-- 训练任务
CREATE TABLE train_job (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER NOT NULL REFERENCES model(id),
    status      TEXT    NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    error_code  TEXT,
    metrics_json TEXT,
    started_at  TEXT,
    finished_at TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_train_status ON train_job (status);

-- 抽检批次与条目
CREATE TABLE blind_batch (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week        TEXT    NOT NULL UNIQUE,          -- '2026-W46'
    seed        TEXT    NOT NULL,
    sampled_by  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    signed_at   TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE blind_item (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES blind_batch(id),
    result_id     INTEGER NOT NULL REFERENCES inference_result(id),
    part_no       TEXT,
    system_label  TEXT    NOT NULL CHECK (system_label IN ('ok', 'gray', 'ng')),
    human_label   TEXT    CHECK (human_label IN ('ok', 'gray', 'ng')),
    judged_by     TEXT,
    signed_quality TEXT,
    signed_line   TEXT,
    signed_tech   TEXT,
    UNIQUE (batch_id, result_id)
);

-- 审计
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    entity      TEXT    NOT NULL,
    entity_id   TEXT,
    payload     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_audit_entity ON audit_log (entity, entity_id);
