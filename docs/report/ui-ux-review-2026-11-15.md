# 后台 UI/UX 体检报告（2026-11-15）

范围：`aip/web/admin.html`（后台 10 页），对照 `ui-ux-pro-max` 的 UX 规则库与对比度测量。
方法：设计系统查询 1 次 + UX 域查询 3 次（焦点、对比度、表单错误）+ 静态代码测量（字号、控件高度、对比度计算）。

结论：**整体结构可用，交互骨架完整**；体检发现 3 处对比度不达 WCAG AA（4.5:1）与 4 处交互/可达性缺口。

> **2026-11-15 更新：以下 5 项已全部修复**（见文末「修复记录」）。

---

## P0 · 对比度（AA 失败，低技能用户可读性直接受影响）

| 元素 | 现状 | 比率 | 建议 | 改后 |
|---|---|---|---|---|
| 主按钮文字（白字橙底） | `#FFFFFF` on `#F26522` | **3.15** ❌ | 品牌色加深到 `#C2410C`（或按钮文字改 `#16181D`） | 5.18 / 5.63 |
| 灰底上的次要文字 | `--t3 #6B7280` on `--g2 #EEF0F4` | **4.24** ❌ | `--t3` 改为 `#5B6472` | 5.24 |
| 成功标签文字 | `--ok #1B8F3A` on 浅绿底 | ~4.1 ❌ | `--ok` 改为 `#147A32` | 5.44 |
| 警告标签文字 | `--warn #A86500` on 浅黄底 | 4.64 ✅ | 不动 | — |
| 危险标签文字 | `--bad #C62828` | 5.62 ✅ | 不动 | — |

> 主按钮是最常用控件（保存、开始训练、推图），3.15:1 意味着靠墙站在 1 米外、屏幕反光时白字会糊。

---

## P1 · 交互与可达性

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| 1 | 全局搜索是 `role="combobox"`，但没有 `aria-activedescendant`、下拉项不是 `role="option"`、`aria-expanded` 只在打开时设置 | 搜索框 `role=combobox`；`#searchDrop` 内是 `div.search-item` | 补 listbox/option 语义与 `aria-activedescendant`；键盘已有 ↑↓/Enter，只差语义 |
| 2 | 切页无加载态：`render*()` 拉数据期间旧内容保持，慢请求时界面"没反应" | 无 skeleton/spinner；只有全局错误兜底 | 加 `aria-busy` + 顶部细进度条或骨架；至少按钮点击后禁用 |
| 3 | 表格行按钮 38px、搜索区按钮 34px，低于 44px 触控基线 | `td button{min-height:38px}`、`.input-with-action button{min-height:34px}` | 桌面鼠标可接受；**工位面板（触屏）必须 ≥44px**，panel 现有主按钮约 44px，行内按钮待测 |
| 4 | 无粘性表头、宽表无横向滚动容器 | `table{width:100%}`，无 `overflow-x` 包裹 | 长表（审计/判例）加 `thead{position:sticky}` + 容器 `overflow:auto` |

---

## P2 · 视觉一致性

| # | 观察 | 建议 |
|---|---|---|
| 1 | 11px 字号 8 处、12px 9 处（标签、表头、提示） | 标签提到 12px、表头 12px 保留、正文提示 ≥12px；车间强光下 11px 偏小 |
| 2 | 时间/数字未设等宽数字 | 表格与时间列加 `font-variant-numeric: tabular-nums`，避免跳动 |
| 3 | 状态主要靠颜色（绿/黄/红标签） | 标签已有文字（成功/灰区/NG），基本达标；NG 可再加图标或前缀 |
| 4 | 中文字体仅 Microsoft YaHei | 加 `system-ui` 已具备；如需数字更清晰可只对数字列用等宽字体 |

---

## 已达标（不用动）

- `:focus-visible` 3px 外环，所有控件可见（含 modal）；
- `prefers-reduced-motion` 全局关闭动画；
- Toast 用 `aria-live="polite"`；
- 原生 `<dialog>`（焦点陷阱与 Esc 由浏览器保证）；
- 17 张表都有 `<caption class="sr-only">`；
- 空状态、全局错误兜底、禁用态 `title` 说明（归档按钮）；
- 深色模式用 `light-dark()` + `color-scheme`，两套对比度均实测达标（dark: t3 5.37）。

---

## 不建议采纳的设计系统建议

`ui-ux-pro-max` 对"industrial manufacturing admin dashboard"给出的默认方向是 **Glassmorphism 深色玻璃拟态**（`#0F172A` 底 + 模糊层）。不采纳：

- 现场是明亮车间 + 反光屏，深色玻璃在强光下更糟；
- 低技能操作员需要最高对比，不是氛围；
- 现有浅色高对比更贴合"看板/检验台"场景。

其查询里**值得借用**的是 "Real-Time / Operations Landing" 的**数据新鲜度标注**：我们已有 10 秒刷新标签与轮询，符合要求。

---

## 建议修复顺序（待确认后再动代码）

1. 三个对比度 token（改 3 行 CSS，影响全站，风险低）；
2. 搜索框无障碍语义（约 20 行 JS/HTML）；
3. 表格粘性表头 + 横向滚动（CSS）；
4. 加载态（每个 `render*` 加一个 `aria-busy` 类）；
5. 数字等宽 + 字号微调。

前 1–3 项做完，这套后台在"可读性 + 键盘可达性"上就干净了。


---

## 修复记录（2026-11-15，已合入）

| # | 项 | 做法 | 验证 |
|---|---|---|---|
| 1 | 主按钮对比度 | `--brand` `#F26522` → `#C2410C`，焦点环同步 | 白字/橙底 3.15 → **5.18** |
| 1 | 灰底次要文字 | `--t3` `#6B7280` → `#5B6472` | 4.24 → **5.24** |
| 1 | 成功标签 | `--ok` `#1B8F3A` → `#147A32` | ~4.1 → **5.44** |
| 2 | 搜索框语义 | 下拉 `role=listbox`、项 `role=option` + id、`aria-activedescendant`、`aria-autocomplete=list` | CDP 实测 `ac=list`、`activedescendant=sopt-0` |
| 3 | 表格滚动 + 粘性表头 | `.table-wrap{overflow:auto;max-height}`、`thead th{position:sticky}`，渲染后自动包裹 | CDP 实测 `position:sticky`，目录页 3 张表已包裹 |
| 4 | 切页加载态 | 顶部 3px 进度条 + `#view[aria-busy]`，`finally` 收尾 | 冒烟通过，`aria-busy=false` 收尾正确 |
| 5 | 字号 + 等宽数字 | 标签/表单 label/图注 11px → 12px；`td,th` 加 `tabular-nums` | 静态检查通过 |

回归：224 个测试全绿；11 个页面（10 后台 + 工位面板）CDP 冒烟通过。

---

## 工位面板（panel.html）修复（2026-11-15，已合入）

工位面板是常亮深色触屏终端，单独体检后修了以下项：

| 项 | 改前 | 改后 | 验证 |
|---|---|---|---|
| 主按钮白字橙底 | `#F26522`，3.15 ❌ | `#C2410C`，**5.18** | CDP 计算色 `rgb(194,65,12)` |
| 次要文字 | `#6B7280` on `#1A1D23`，3.49 ❌ | `#8A929E`，**5.37** | 计算值确认 |
| 确认（OK）按钮 | `#34C759` 白字 2.22 ❌ | `#147A32`，**5.44** | — |
| 改判（NG）按钮 / 断线横幅 | `#FF3B30` 白字 3.55 ❌ | `#C62828`，**5.62** | `rgb(198,40,40)` |
| 灰区确认按钮 | 误用红色（语义错） | 新增 `button.warn` `#A86500`，4.64 | 截图确认琥珀色 |
| 键盘焦点 | 无 focus 样式 | `:focus-visible` 3px 品牌色外环 | 截图可见 |
| 表单标签 | `<label>` 无 `for`，读屏不关联 | 补 `for/id`，chip 组与理由组用 `role=group` + `aria-labelledby` | CDP 实测 5 个绑定 |
| 状态播报 | 无 | 健康/换型/推图/待复核 4 处 `role=status`/`aria-live`；断线横幅 `role=alert` | 实测 4 个 live region |
| 对话框 | 无无障碍名 | `aria-labelledby="dlgTitle"` | 实测已绑定 |
| 字号 | 标签 11px | 12px | — |

触控尺寸本就达标（按钮 56px、输入 52px），本次未改。

回归：`scripts/ui_smoke.mjs` 现在同时检查 `/panel`，共 11 个页面。
