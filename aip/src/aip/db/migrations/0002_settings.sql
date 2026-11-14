-- 0002_settings.sql — 运行时配置
-- 只存"运行时可改"的项；启动级（端口/路径/白名单）不放这里。

CREATE TABLE setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,          -- JSON 编码，读时按声明类型解析
    updated_by  TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
