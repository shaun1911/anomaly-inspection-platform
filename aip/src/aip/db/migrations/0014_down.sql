-- 0014_down.sql
-- SQLite 不支持按约束逐列删除，按表重建回 v13 形态。
CREATE TABLE feedback_old (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id   INTEGER REFERENCES inference_result(id),
    verdict     TEXT    NOT NULL CHECK (verdict IN ('ok', 'ng')),
    note        TEXT,
    source      TEXT    NOT NULL DEFAULT 'online' CHECK (source IN ('online', 'late')),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
INSERT INTO feedback_old (id, result_id, verdict, note, source, created_at)
SELECT id, result_id, verdict, note, source, created_at FROM feedback;
DROP TABLE feedback;
ALTER TABLE feedback_old RENAME TO feedback;
CREATE UNIQUE INDEX idx_feedback_online ON feedback (result_id) WHERE source = 'online';
DELETE FROM schema_version WHERE version = 14;
