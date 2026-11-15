# Hallmark 审计 · 复核队列页（2026-11-15）

目标：`aip/web/admin.html`（`#/quality`），app screen 范围。
方式：`sloplint --genre modern-minimal --scope app` + 截图人工判断。**本次未改任何项目文件。**

## 四行读解

1. **这页是干什么的**：质检复核员在一屏内判定单件（判 OK/NG、暂缓、领取），核心是"看裁片 + 下结论"。
2. **留下什么**：主图与参考样例并排、OK/NG 分组、结果导向按钮、键帽提示、首屏不滚——结构成立，不改。
3. **哪里像生成的**：竖向节奏碎（2/4/6/10px 混用）、导航分组标签用了 0.14em 字距、颜色常量散落在规则里、分数区间用了 en dash（`0.45–0.45`）。
4. **哪里是坏的**：没有功能性损坏；Floor 15 项失败全属工艺层。

## 直接回答：下面的文字要加间隔

是。图片以下到按钮之间的文字区，间距混用了 **2 / 4 / 6 / 10px**，没有节奏，读起来像挤在一张表里：

| 位置 | 现状 | 问题 | 建议 |
|---|---|---|---|
| `.kv` 元信息行距（:266） | `gap: 2px 12px` | 行距 2px，低于 4px 基线；四行两列挤成表格 | `gap: 4px 12px`，`line-height: 1.5` |
| `.reasons` 理由区（:282） | `margin: 4px 0; gap: 6px` | 与上方按钮/下方动作贴太近 | `margin: 8px 0`，按钮 `gap: 8px` |
| `.review-tip` 规则提示（:283） | `margin-top: 4px` | 紧贴动作按钮，像按钮的一部分 | `margin-top: 8px` |
| `#rshots` 结果号（内联） | `margin-top: 6px` | 与参考样例区粘连 | `margin-top: 8px` |
| `.shot` 图下边距（:264） | `margin-bottom: 10px` | 10 不在 4px 基线 | `margin-bottom: 12px` |

合计约 **+18～22px** 竖向空间。

**空间从哪来**：样例缩略图当前 `clamp(108px, 15vh, 156px)`，1440×900 下 121px、主图 356px。把系数降到 `13vh`（1440 约 105px），两行样例省约 16px，正好抵消；1920 下不受影响。

## 其他层级发现（供排期）

### Floor（15 FAIL，工艺层）

- `:16` 文案使用 en dash（分数区间 `0.45–0.45`）→ 改 `~` 或 `至`；
- `:73` aside + header + 表头三处 `sticky top:0` 叠加，需层级偏移；
- `:67` 导航分组标签 0.14em 字距（Hallmark 禁止 label 加字距）→ 去字距、降一档字号；
- `:111/:159/:249/:257/:290/:294/:299` 颜色字面量（`#fff`、rgba 阴影）未走 token；
- `:387` `<img id="shot">` 初始无 `src` → 给占位或加载前隐藏；
- `overflow-x: clip` 缺失；CSS 首行无 stamp（审计目标，非 Hallmark 构建，记录在案）。

### Reflex（68，可豁免但建议修）

- `24b` 4px 基线大量偏离（本次报告的间距项同源）；
- `26b` 全站无 `:active` / `:disabled` 态；
- `38iii` `h2 .pill` 在标题内构成强调词；
- `F6` `.todo-count` 未用等宽数字；
- `F3` 标题缺 `text-wrap: balance`；
- `F24` 搜索下拉同时用细边框和宽阴影。

## 最轻修复路径

| 问题 | 最轻深度 |
|---|---|
| 文字区间距、4px 基线 | **polish**（只修被 gate 点名的项） |
| 颜色字面量进 token、导航标签去字距 | **restyle**（动系统） |
| 分区层级、标签字体体系 | **full**（动构图，不建议） |

本次审计只出报告。要按 **polish** 把上面 5 处间距 + en dash + 无源 img 一并修掉吗？改动约 12 行 CSS/文案，不动结构。
---

## 修复记录（polish，2026-11-15）

已按最轻深度修掉：

| 项 | 改动 | 验证 |
|---|---|---|
| 元信息行距 | gap 2→4、line-height 1.45→1.5 | CDP 
owGap: 4px |
| 理由区 | margin 4→8、gap 6→8 | — |
| 规则提示 / 结果号 | margin-top 4/6→8 | — |
| 图下边距 | 10→12 | — |
| en dash | 分数区间与快捷键说明改 ~ | 页面文本不再含 – |
| 无源 img | #shot 加透明占位 src | sloplint FAIL 76 消失 |
| overflow-x | html,body{overflow-x:clip} | FAIL 34 消失 |

为保住 1440×900 首屏，@media (max-height:900px) 下样例缩略图降到 13vh（105px）；1920×1080 仍为 148px。

sloplint：**15 FAIL → 13 FAIL**。剩余为 token 字面量（48）、导航标签字距（67）、sticky 层级（56）、CSS stamp（审计目标固有），归 **restyle**，本次未动。

回归：235 测试、16 项冒烟全过；页面 805/805，动作区 710。

---

## 修复记录（restyle，2026-11-15）

| 项 | 改动 |
|---|---|
| 颜色字面量（7 处） | 新增 token：`--on-brand`、`--row-hover`、`--shadow-pop`、`--shadow-bar`、`--backdrop`；规则全部改走 token |
| 导航分组字距 | 去掉 `letter-spacing:.14em`（label 不加字距） |
| 表头 sticky | `top:0 → 1px`，归入 `.table-wrap` 自己的滚动容器 |
| 无源 img | `#shotDlgImg` 补透明占位 |
| CSS stamp | 首行加 Hallmark stamp（restyle、无 deal），附 56 说明 |
| savebar 阴影 | 改用 `--shadow-bar` |

sloplint 结果：**15 FAIL → 1 FAIL**。

剩余 1 项：`56 两个 sticky top:0（aside + header）`。这是静态检查的误报——侧栏与顶栏在同一网格的不同列，不重叠；真实运行时二者各自粘住，没有遮挡。已按事实保留，不为了过 linter 改掉可用行为。

67 项 Reflex 与 5 项 WARN（4px 基线、`:active` 态、`text-wrap:balance`、搜索下拉边框+阴影等）属于下一步 polish 批次，不在本次 restyle 范围。
