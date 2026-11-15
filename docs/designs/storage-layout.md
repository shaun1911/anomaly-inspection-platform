# 存储目录结构

> 所有可写数据都在**一个数据目录**下；服务端只认这个根，换目录走迁移流程（见文末）。

## 目录树

```
<data-dir>/
├─ aip.db                  SQLite 主库（WAL 模式）
├─ aip.db-wal              WAL 日志（运行时存在）
├─ aip.db-shm              共享内存索引（运行时存在）
├─ crops/                  判定裁片，按图片 sha256 命名
│   └─ <sha256>.png
├─ cases/                  判例上传原图（手工/复核补录）
│   └─ <sha256>.png
└─ smoke/                  冒烟试判图（发布前验证用）
    └─ <sha256>.png
```

默认位置：仓库内 `data/`；可用 `--data-dir` 或环境变量 `AIP_DATA_DIR` 指定。

## 谁写、谁读

| 目录 | 写入方 | 读取方 | 生命周期 |
|---|---|---|---|
| `aip.db` | 全部业务写接口 | 全部读接口 | 长期；迁移时 sqlite backup |
| `crops/` | `POST /infer`（按 sha 去重） | `/results/{id}/image`、`/api/blind/items/{id}/image` | 判例引用/待复核**永不删**；其余按 `retention.crop_days` |
| `cases/` | `POST /api/cases/upload` | `/api/cases/{id}/image` | 随判例长期保留 |
| `smoke/` | 冒烟接口 | 仅试判时读取 | 按 `retention.smoke_days`（默认 7 天） |

同一个 sha256 的图片只落一份；文件名即内容指纹，便于对账。

## 保留与清理

- 设置 → 存储：`retention.crop_days`（默认 30）、`retention.smoke_days`（默认 7）。
- 清理入口：系统 → 存储维护（先预览、再执行）、`scripts/retention.py`。
- **不删**：判例引用的裁片、待复核判定的裁片、`cases/` 目录。
- 每次执行写审计 `storage.retention`。

## 迁移（换盘/扩容）

1. 设置 → 存储 → 目标空目录 → **预检**（嵌套、占用、磁盘空间）；
2. **执行迁移**：迁移期间服务端加**写入锁**，`/infer`、判例上传、存储清理返回 503 `maintenance`，保证复制期间没有新文件写入；
3. DB 用 `sqlite3.backup()` 做一致性快照，随后复制 `crops/cases/smoke`；
4. 校验文件数与 DB `integrity_check`，写审计 `storage.move`；
5. 用新目录重启：`python scripts/dev_server.py --data-dir "<新目录>"`；
6. 确认后手工删除旧目录（程序不自动删）。

''## 审计归档

审计日志按 `audit.retention_days`（默认 180 天，最少 30 天）归档：

1. 系统 → 「归档 N 天前」先查数量与最早时间，确认后执行；
2. 旧记录导出为 `<data-dir>/audit-archive/audit-<时间>.csv`（带 BOM，Excel 直接打开）；
3. 导出成功后从 `audit_log` 删除；归档动作本身写一条 `audit.archive` 审计；
4. 也可用 CLI：`python scripts/archive_audit.py [--days 90] [--apply]`。

''归档是删库前先落盘，所以 CSV 就是事后追溯的唯一副本——要长期保存请把 `audit-archive/` 一并备份。

### 自动维护（开关）

设置 → 存储：

| 项 | 默认 | 说明 |
|---|---|---|
| `maintenance.auto_hour` | 3 | 每天几点执行（UTC 小时 0-23） |
| `maintenance.auto_audit` | 关 | 每天按审计保留天数归档 |
| `maintenance.auto_retention` | 关 | 每天按证据保留天数清理裁片/冒烟图 |

服务启动时拉起守护线程；**存储迁移期间自动跳过**（写锁生效），每次执行写一条 `maintenance.auto` 审计。
两个开关默认关闭——自动删数据必须显式打开。'

**导回**：系统 → 「导入归档」或 `python scripts/archive_audit.py --import-csv <文件> [--apply]`。
按 `(actor, action, entity, entity_id, created_at)` 去重，重复导入不会翻倍；预检不写库。'

## 备份与还原'

**备份**（设置 → 存储 → 立即备份，或 `POST /api/maintenance/backup`）：

- 加写锁后执行，避免复制期间出现新文件；
- `aip.db` 用 sqlite backup 出一致性快照；
- 打包为 zip，结构：

```
aip-backup-<date>.zip
├─ manifest.json   format_version / created_at / files / bytes / schema_version
├─ aip.db
├─ crops/...
├─ cases/...
└─ smoke/...
```

**还原**（设置 → 存储 → 还原）：

1. 预检：校验 manifest、`aip.db` 的 `integrity_check`、压缩包路径穿越；
2. 只解到**空目录**，不覆盖当前数据；
3. 还原后复核文件数与数据库完整性，写审计 `storage.restore`；
4. 用新目录重启：`python scripts/dev_server.py --data-dir "<还原目录>"`。

**为什么必须整目录备份**：只拷 `aip.db` 会丢裁片，只拷 `crops/` 会丢判例关系。'
