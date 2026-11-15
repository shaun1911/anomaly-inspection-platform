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

## 备份

- 需要备份的是**整个数据目录**：只拷 `aip.db` 会丢裁片，只拷 `crops/` 会丢判例关系；
- 热备份使用 sqlite backup 或先停服务，避免 WAL 半写。
