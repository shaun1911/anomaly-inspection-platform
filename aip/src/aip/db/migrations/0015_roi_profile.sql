-- 0015_roi_profile.sql — ROI 按“编码 + 站位”管理
-- station_id = 0 表示该编码的默认 ROI；具体站位优先。
CREATE TABLE roi_profile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code_id INTEGER NOT NULL REFERENCES product_code(id),
    station_id      INTEGER NOT NULL DEFAULT 0,
    roi_rect        TEXT    NOT NULL,
    rev             INTEGER NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    note            TEXT,
    updated_by      TEXT,
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (product_code_id, station_id, rev)
);
CREATE UNIQUE INDEX idx_roi_profile_active
    ON roi_profile (product_code_id, station_id) WHERE active = 1;
