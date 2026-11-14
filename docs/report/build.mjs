/**
 * 生成《AIP 工业异常检测平台 · 项目介绍》PDF 源文件（report.html）。
 * 图片全部 base64 内嵌，保证 PDF 打印时无外部依赖。
 *
 *   node docs/report/build.mjs
 *   msedge --headless=new --print-to-pdf=... docs/report/report.html
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.join(here, 'shots');

const img = (name) => {
  const file = path.join(shots, `${name}.png`);
  const b64 = fs.readFileSync(file).toString('base64');
  return `data:image/png;base64,${b64}`;
};

const CSS = `
  @page { size: A4; margin: 0; }
  @page land { size: A4 landscape; margin: 0; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #fff; color: #1A1A1A;
    font: 10.5pt/1.72 "Microsoft YaHei", system-ui, sans-serif;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  .page {
    width: 210mm; height: 297mm; padding: 16mm 17mm 14mm;
    position: relative; page-break-after: always; overflow: hidden;
  }
  .page:last-child { page-break-after: auto; }
  .page.land { page: land; width: 297mm; height: 210mm; padding: 12mm 14mm 10mm; }
  .foot {
    position: absolute; left: 17mm; right: 17mm; bottom: 7mm;
    display: flex; justify-content: space-between;
    font-size: 7.6pt; color: #9E9E9E; border-top: 1px solid #EEE; padding-top: 2mm;
  }
  h2 {
    font-size: 15pt; line-height: 1.4; margin: 0 0 3mm; font-weight: 700;
    padding-left: 3mm; border-left: 4px solid #F26522;
  }
  h3 { font-size: 11pt; margin: 5mm 0 2mm; color: #1A1A1A; }
  p { margin: 0 0 3mm; color: #333; }
  .lead { font-size: 10.5pt; color: #444; }
  .mut { color: #666; }
  .small { font-size: 9pt; color: #666; }
  .tiny { font-size: 8pt; color: #888; }
  ul { margin: 0 0 3mm; padding-left: 5mm; }
  li { margin-bottom: 1.2mm; }
  strong { color: #1A1A1A; }
  em { font-style: normal; color: #D5541D; font-weight: 600; }

  .cover { background: #FFF4EE; }
  .cover .bar { height: 9mm; background: #F26522; margin: -16mm -17mm 0; }
  .cover .kicker { margin-top: 46mm; font-size: 10pt; letter-spacing: 3px; color: #D5541D; font-weight: 600; }
  .cover h1 { font-size: 32pt; line-height: 1.25; margin: 4mm 0 0; letter-spacing: -0.5pt; }
  .cover .sub { font-size: 13pt; color: #666; margin-top: 5mm; }
  .cover .rule { width: 24mm; height: 3px; background: #F26522; margin: 9mm 0; }
  .cover .meta { font-size: 9.5pt; color: #666; line-height: 2; }
  .cover .note {
    position: absolute; left: 17mm; right: 17mm; bottom: 22mm;
    font-size: 8.5pt; color: #8a6a58; border-left: 3px solid #FFC9B0; padding-left: 4mm; line-height: 1.8;
  }

  .kpis { display: flex; gap: 4mm; margin: 5mm 0; }
  .kpi { flex: 1; border: 1px solid #EEE; border-radius: 3mm; padding: 4mm; background: #FAFAFA; }
  .kpi .n { font-size: 19pt; font-weight: 700; color: #F26522; line-height: 1.2; }
  .kpi .t { font-size: 8pt; color: #666; margin-top: 1mm; }
  .kpi .u { font-size: 9pt; color: #999; font-weight: 400; }

  .cards { display: flex; flex-wrap: wrap; gap: 4mm; }
  .card2 { width: calc(50% - 2mm); border: 1px solid #EEE; border-radius: 3mm; padding: 4mm; }
  .card2 b { display: block; font-size: 10pt; margin-bottom: 1.5mm; }
  .card2 span { font-size: 8.6pt; color: #666; line-height: 1.7; }
  .num { display: inline-block; width: 5mm; height: 5mm; line-height: 5mm; text-align: center;
         background: #F26522; color: #fff; border-radius: 1.5mm; font-size: 7.5pt; margin-right: 1.5mm; }

  figure { margin: 0 0 3mm; }
  figure img { width: 100%; border: 1px solid #E0E0E0; border-radius: 2.5mm; display: block; }
  figcaption { font-size: 8pt; color: #777; margin-top: 1.5mm; line-height: 1.6; }
  .full img { border-radius: 2mm; }

  table { width: 100%; border-collapse: collapse; font-size: 8.8pt; margin: 2mm 0 3mm; }
  th { background: #FAFAFA; color: #666; font-weight: 600; text-align: left; padding: 2mm 2.5mm;
       border-bottom: 1px solid #E0E0E0; font-size: 8.4pt; }
  td { padding: 1.8mm 2.5mm; border-bottom: 1px solid #F0F0F0; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  td.mono, .mono { font-family: Consolas, monospace; font-size: 8.4pt; }
  .tag { display: inline-block; font-size: 7.6pt; padding: 0.4mm 2mm; border-radius: 2mm;
         background: #FFF4EE; color: #D5541D; border: 1px solid #FFE6D9; }
  .tag.g { background: #E8F8EE; color: #1B8F45; border-color: #BFE9CD; }
  .tag.b { background: #E8F2FF; color: #0063CC; border-color: #B9D6FF; }

  .callout { border-left: 3px solid #F26522; background: #FFF8F4; padding: 3mm 4mm; border-radius: 0 2mm 2mm 0;
             font-size: 9.2pt; color: #4a3a32; margin: 3mm 0; }
  .quote { font-size: 9pt; color: #555; background: #FAFAFA; border: 1px solid #EEE; border-radius: 2mm;
           padding: 3mm 4mm; margin: 3mm 0; }
`;

const page = (body, no, total = 16, land = false) => `
  <section class="page${land ? ' land' : ''}">
    ${body}
    ${no ? `<div class="foot"><span>AIP 工业异常检测平台 · 项目介绍</span><span>${no} / ${total}</span></div>` : ''}
  </section>`;

const cover = `
  <div class="cover" style="margin:-16mm -17mm; padding:16mm 17mm; height:297mm; position:relative;">
    <div class="bar"></div>
    <div class="kicker">项 目 介 绍</div>
    <h1>AIP 工业异常检测平台</h1>
    <div class="sub">远程推理服务 · 多模型路由 · 数据飞轮 · 纯内网离线部署</div>
    <div class="rule"></div>
    <div class="meta">
      版本：v0.3 方案 · 原型同步<br>
      日期：2026 年 11 月<br>
      场景：汽车零部件表面缺陷检测（划伤 / 脏污 / 压伤 / 凹坑）<br>
      部署：Windows 11 Pro + NVIDIA RTX 5090 · 单机 · 完全离线
    </div>
    <div class="note">
      本文档中的所有界面与流程图，均由同一套可交互原型真实渲染后截取，
      与方案文档同源；界面为模拟数据，逻辑与交互为真实设计。
    </div>
  </div>`;

const p2 = `
  <h2>一页摘要</h2>
  <p class="lead">AIP 是一套面向工业视觉的异常检测平台：现场设备把 2K 图片推到中心服务，
  服务按产品编码选对应模型判 OK/NG 并给出缺陷位置；判定结果自动回流，按策略抽样、
  自动训练出候选模型，由人确认后热切换上线。</p>

  <div class="kpis">
    <div class="kpi"><div class="n">1.9<span class="u"> ms</span></div><div class="t">单图推理（wrn50 · batch=8 · 5080 实测）</div></div>
    <div class="kpi"><div class="n">122<span class="u"> MB</span></div><div class="t">单模型显存占用（40 张训练库）</div></div>
    <div class="kpi"><div class="n">80<span class="u"> 张/天</span></div><div class="t">默认抽样量（人工 40 + 自动 40）</div></div>
    <div class="kpi"><div class="n">35<span class="u"> 个</span></div><div class="t">可选算法（基于 anomalib 模型库）</div></div>
  </div>

  <h3>三个必须解决的问题</h3>
  <table>
    <tr><th style="width:30%">现状</th><th>平台的做法</th></tr>
    <tr><td>每条产线一套脚本，换线就要重写</td><td>配方驱动：一条线一份配置；产品编码与模型解耦，现场只认编码</td></tr>
    <tr><td>模型上线后不会再变好</td><td>数据飞轮：抽样 → 复核 → 自动训练 → 人工发布，闭环可审计</td></tr>
    <tr><td>说不清"这批货是谁判的"</td><td>每张图可追溯：产品编码 → 模型 → 版本 → 分数 → 阈值</td></tr>
  </table>

  <h3>交付形态</h3>
  <div class="cards">
    <div class="card2"><b>一套服务</b><span>Windows 原生服务（NSSM 托管），
      推理与训练两个进程隔离；离线安装包约 5 GB，拔网线可用。</span></div>
    <div class="card2"><b>一个工件</b><span>模型以 bundle 交付：元数据 + ONNX + 权重 +
      配方。换机器只拷目录，热切换 30 秒内可回滚。</span></div>
  </div>`;

const p3 = `
  <h2>背景与目标</h2>
  <p class="lead">表面缺陷检测的难点不在"算法"，而在"能不能长期稳定地跑在产线上"。
  平台的设计目标，是把这三件事从人身上挪到系统里。</p>

  <h3>四个反复出现的现场问题</h3>
  <table>
    <tr><th style="width:26%">问题</th><th>表现</th><th style="width:30%">根因</th></tr>
    <tr><td>换型靠人记</td><td>换产品后忘了切模型，用上一个件的模型判，且不报错</td><td>模型选择依赖人的记忆</td></tr>
    <tr><td>模型不迭代</td><td>上线即巅峰，后面分布漂移只能靠人发现</td><td>没有数据回流与再训练机制</td></tr>
    <tr><td>误判无人认领</td><td>过杀堆在复检台，漏检流向客户</td><td>现场反馈没有入口，无法归因</td></tr>
    <tr><td>追溯断链</td><td>客户投诉时说不清哪批、哪个模型判的</td><td>结果没落库，或没记录模型版本</td></tr>
  </table>

  <h3>对应的四个设计决定</h3>
  <div class="cards">
    <div class="card2"><b><span class="num">1</span>编码即路由</b><span>推图带产品编码，服务按编码选模型；
      编码被人占用时禁止重复绑定——路由必须唯一，否则错判不会报错。</span></div>
    <div class="card2"><b><span class="num">2</span>绑定模型，不绑版本</b><span>版本在模型内各自成线；
      发布新版本时，绑定该模型的所有编码自动跟随，无需逐条改绑定。</span></div>
    <div class="card2"><b><span class="num">3</span>抽样配额可配</b><span>抽选时间、每日总量、比例、各分层上限全部可配，
      按模型分配，避免热点模型吃满人工预算。</span></div>
    <div class="card2"><b><span class="num">4</span>发布必须有人</b><span>自动训练只产出候选，
      冒烟集校验通过才允许发布；发布与回滚均写审计。</span></div>
  </div>

  <div class="callout">
    <strong>一条贯穿全局的原则：</strong>凡是"静默出错"的设计一律不做。
    编码未知返回 422、编码停用返回 410、模型未就绪返回 503、错绑由冒烟集拦截——
    宁可让产线停一秒，也不要让错判流出去。
  </div>`;

const p4 = `
  <h2>平台四大能力</h2>
  <p class="lead">四个能力分别对应"选对模型、快速换型、越用越准、说得清楚"。</p>

  <h3>① 多模型路由</h3>
  <p>一个服务同时提供多个模型。产品编码（现场助记符）→ 模型 → 当前生效版本，
  三层解耦；一个模型可服务多个编码，一个编码只能绑一个模型。</p>

  <h3>② 配置单 · 一键加载</h3>
  <p>技术人员把"这批要用的编码"定义成配置单；操作工换型时单击一次，
  系统把它们对应的模型全部预热进显存，全绿即可开工。配置单只影响预加载，
  不影响路由——忘了切配置单也不会判错。</p>

  <h3>③ 数据飞轮</h3>
  <p>现场反馈 + 分层抽样 → 高置信自动入库、低置信进人工队列 → 样本够量自动训练
  → 候选模型 → 人工发布。全程可配、可审计。</p>

  <h3>④ 归档与追溯</h3>
  <p>NG 原图热存 30 天后打包归档 12 个月，OK 图 7 天后只留缩略图；
  被数据集引用、被法务锁定的数据永不自动删除。</p>

  <table style="margin-top:4mm">
    <tr><th>能力</th><th>解决什么</th><th>关键指标</th></tr>
    <tr><td>多模型路由</td><td>一条服务支撑多条产品线</td><td class="mono">路由延迟 &lt; 1 ms</td></tr>
    <tr><td>配置单加载</td><td>换型不依赖人的记忆</td><td class="mono">4 个模型预热 ≈ 2.4 s</td></tr>
    <tr><td>数据飞轮</td><td>模型随产线分布一起演进</td><td class="mono">人工 10 分钟/天</td></tr>
    <tr><td>归档追溯</td><td>争议时能自证</td><td class="mono">包内 sha256 校验</td></tr>
  </table>`;

const p5 = `<!--land-->
  <h2>使用流程</h2>
  <p class="lead" style="margin-bottom:2mm">四条泳道对应四类参与者：技术人员、操作工、系统、模型与训练；
  横向四段是生命周期：建模 → 换型 → 生产 → 飞轮。实线为主路径，虚线为回路。</p>
  <figure class="full">
    <img src="${img('usage-crop')}" alt="使用流程图">
    <figcaption>图 1　使用流程图（Archify 生成，可交互版本见 docs/diagrams/usage.html）。
      "复核与发布"是唯一能改变线上模型的动作；"模型常驻"是所有推理的落点。</figcaption>
  </figure>`;

const p6 = `
  <h2>流程解读：三段时间 + 一条回路</h2>

  <h3>一次性：建模</h3>
  <p>技术人员用五步向导建模型：填名称 → 勾编码（已被占用会置灰）→ 传正常品/缺陷图
  → 选训练配置（按数据量给推荐值）→ 确认。创建后自动切分并锁定冻结验收集，
  可选立即训练。这一步决定"模型叫什么、管哪些编码"。</p>

  <h3>每次换型：一次点击</h3>
  <p>操作工不选模型，只点配置单上的「一键加载」。系统解析编码 → 去重成模型 →
  并发预热（4 路）→ 逐项就绪。全绿显示「可以开工」，有失败会指出具体是哪个模型。
  设计上刻意不做"全局卸载"：显存便宜，增量加载即可，超限时按 LRU 淘汰不在配置单里的模型。</p>

  <h3>每件产品：推图即判</h3>
  <p>上料推图（2K JPEG，带编码）→ 编码路由 → 批推理 → 返回判级、分数、缺陷框；
  结果落库并记录模型版本。判得不对，操作工点一次「实际 OK / 实际 NG」即可反馈。</p>

  <h3>每日回路：抽样到发布</h3>
  <p>系统按配置的时间抽样（默认 02:00，80 张/天），分三层：低置信送人工、
  高置信 OK 自动入训练集、高置信 NG 只进验收集（不参与 one-class 训练）。
  样本累计到阈值自动训练，产出候选；通过冒烟集校验后由人点「发布」，热切换生效。</p>

  <div class="callout">
    <strong>为什么高置信 NG 不进训练集：</strong>模型判 NG 的样本里混着大量过杀，
    把它们当缺陷喂回去，等于教模型把正常纹理学成缺陷——几轮之后模型就废了。
    训练集只吃人工确认过的正常品 + 高置信 OK。
  </div>

  <div class="quote">
    <strong>三道闸：</strong>① 抽样分层（不是所有样本都找人，也不是全都自动收）
    ② 冒烟集校验（错绑模型直接拦下）③ 人工发布（自动训练只出候选）。
  </div>`;

const p7 = `<!--land-->
  <h2>系统架构</h2>
  <p class="lead" style="margin-bottom:2mm">纯内网单机部署：设备经反向代理到应用，应用调度推理引擎与常驻模型；
  训练走独立进程，与在线推理隔离。外框是部署边界，虚框是资源边界（GPU 显存池 29 GB）。</p>
  <figure class="full">
    <img src="${img('system-crop')}" alt="系统流程图">
    <figcaption>图 2　系统流程图（Archify 生成，可交互版本见 docs/diagrams/system.html）。
      推理引擎、常驻模型、训练 Worker 同处一个显存池——这是单卡部署最需要调度的位置。</figcaption>
  </figure>`;

const p8 = `
  <h2>架构说明与容量预算</h2>

  <h3>分层</h3>
  <table>
    <tr><th style="width:22%">层</th><th>选型</th><th style="width:34%">理由</th></tr>
    <tr><td>接入</td><td>Caddy（内部 CA / 限流 / 体积上限）</td><td>内网无公网证书，自签 + 一次信任</td></tr>
    <tr><td>应用</td><td>FastAPI（推理 API + 管理页面）</td><td>与 anomalib 生态一致，页面服务端渲染</td></tr>
    <tr><td>推理</td><td>torch 2.10 + cu130；PatChCore 系列</td><td>Blackwell 直通；单图 1.9 ms（batch=8）</td></tr>
    <tr><td>训练</td><td>anomalib Engine + 独立 Worker 进程</td><td>训练 OOM 不影响在线推理</td></tr>
    <tr><td>存储</td><td>SQLite(WAL) + 文件目录</td><td>单机零运维；元数据与图片分离</td></tr>
  </table>

  <h3>显存预算：能同时加载多少个模型</h3>
  <p class="small">单模型显存 ≈ 主干权重 + 记忆库；记忆库随训练张数线性增长。</p>
  <table>
    <tr><th>训练集规模</th><th>单模型显存</th><th>32 GB 理论上限</th><th>16 GB（5080）</th></tr>
    <tr><td>40 张</td><td class="mono">~122 MB</td><td class="mono">~239 个</td><td class="mono">~106 个</td></tr>
    <tr><td>200 张</td><td class="mono">~200 MB</td><td class="mono">~146 个</td><td class="mono">~64 个</td></tr>
    <tr><td>500 张</td><td class="mono">~434 MB</td><td class="mono">~67 个</td><td class="mono">~30 个</td></tr>
    <tr><td>1000 张</td><td class="mono">~800 MB</td><td class="mono">~36 个</td><td class="mono">~16 个</td></tr>
  </table>
  <div class="callout">
    <strong>建议运行上限 24 个模型。</strong>当班配置单通常 5~15 个，留 3 倍余量给换型与 LRU 波动；
    硬上限由「可用显存 ÷ 单模型显存」动态计算，超过就淘汰不在配置单里的模型。
  </div>`;

const shotPage = (title, lead, a, b) => `
  <h2>${title}</h2>
  <p class="lead" style="margin-bottom:3mm">${lead}</p>
  <figure><img src="${img(a.src)}" alt="${a.alt}"><figcaption>${a.cap}</figcaption></figure>
  <figure style="margin-top:4mm"><img src="${img(b.src)}" alt="${b.alt}"><figcaption>${b.cap}</figcaption></figure>`;

const pages = [
  cover,
  p2,
  p3,
  p4,
  p5,
  p6,
  p7,
  p8,

  shotPage('概览与配置单', '概览回答"现在怎么样"，配置单回答"开工前要准备什么"。',
    { src: 'dashboard', alt: '概览', cap: '图 3　概览：线级 KPI（检测量 / NG 率 / 过杀率 / 延迟）+ 模型健康度。模型间指标不可平均，每个模型只在自己的冻结验收集上算。' },
    { src: 'workorder', alt: '配置单', cap: '图 4　配置单：一组产品编码 → 自动去重成模型；操作工单击「一键加载」，逐项预热到就绪。' }),

  shotPage('推理与路由', '现场只做两件事：看结果、判错了点一下。',
    { src: 'infer', alt: '推理检测', cap: '图 5　推理检测：编码 → 模型 → 版本全链路可见；解码 11 ms、推理 6 ms 拆分展示——2K 图的真正成本在解码。' },
    { src: 'models', alt: '模型与版本', cap: '图 6　模型与版本：每个模型一条版本线（M-BR-01 到 v4，M-CP-01 才 v2），发布/回滚只影响本模型。' }),

  shotPage('新建模型与复核', '平台的两个入口：建新任务、校准旧任务。',
    { src: 'create', alt: '新建模型向导', cap: '图 7　五步向导：编码冲突拦截、按数据量给推荐配置（<100 张用 resnet18，>500 张用 384 输入）。' },
    { src: 'review', alt: '复核队列', cap: '图 8　复核队列：按模型分组、配额可见；每天 10 分钟、约 40 张，快捷键 1/2/空格。' }),

  shotPage('归档与接口', '既要能追溯，也要能被现场集成。',
    { src: 'archive', alt: '归档与清理', cap: '图 9　归档与清理：NG 30 天热存 + 12 个月归档、OK 7 天；法务锁定与数据集引用永不自动删除。' },
    { src: 'api', alt: 'API 说明', cap: '图 10　API 说明：26 个接口 + 请求/响应样例；错误码额外标注"现场怎么处理"，410 与 422 分开。' }),
];

const p14 = `
  <h2>数据飞轮：抽样、训练、发布</h2>

  <h3>抽样分层（默认，可按模型覆盖）</h3>
  <table>
    <tr><th style="width:18%">分层</th><th style="width:26%">条件</th><th>去向</th><th style="width:16%">每日上限</th></tr>
    <tr><td>现场反馈</td><td>设备上报（过杀 / 漏检）</td><td>直接入池，不占配额</td><td class="mono">不限</td></tr>
    <tr><td>低置信</td><td class="mono">0.35 ≤ score ≤ 0.65</td><td>人工确认队列</td><td class="mono">40</td></tr>
    <tr><td>高置信 OK</td><td class="mono">score ≤ 0.20</td><td>训练集 normal</td><td class="mono">20</td></tr>
    <tr><td>高置信 NG</td><td class="mono">score ≥ 0.90</td><td>仅验收集（不进 one-class 训练）</td><td class="mono">10</td></tr>
    <tr><td>随机对照</td><td>全区间等概率</td><td>抽样偏差监控</td><td class="mono">10</td></tr>
  </table>
  <p class="small">合计 80 张/天；其中需人工的 40 张，按 6 秒/张 ≈ 4 分钟，留 6 分钟余量。</p>

  <h3>自动训练的门槛</h3>
  <table>
    <tr><th style="width:34%">检查项</th><th>不通过时</th></tr>
    <tr><td>冻结验收集指纹未变</td><td>拒绝启动训练（数据集被动过）</td></tr>
    <tr><td>召回不下降</td><td>标记 candidate_rejected，只告警</td></tr>
    <tr><td>过杀率上升 ≤ 2pt</td><td>同上，不打扰人</td></tr>
    <tr><td>冒烟集逐产品通过</td><td>禁止发布（错绑模型的最大来源）</td></tr>
  </table>

  <div class="callout">
    <strong>为什么"发布"不能自动：</strong>自动训练只会在历史上表现好，它不知道
    明天要换的产品、也不知道这批货的客户要求。把最后一公里留给人，是有意为之。
  </div>`;

const p15 = `
  <h2>部署与运维</h2>

  <h3>形态</h3>
  <p>Windows 11 Pro 工作站，两个 NSSM 服务：<span class="mono">AIP-Web</span>（推理 + 页面）与
  <span class="mono">AIP-Worker</span>（训练队列）。拆开是为了让训练 OOM 不带走在线推理。</p>

  <table>
    <tr><th style="width:24%">项</th><th>做法</th></tr>
    <tr><td>安装</td><td>离线包约 5 GB（Python 3.12 + wheelhouse + 内置主干权重 + 服务脚本），拔网线可用</td></tr>
    <tr><td>自愈</td><td>看门狗每 2 分钟健康检查，连续 3 次失败重启服务；开机自启</td></tr>
    <tr><td>路径</td><td>数据 / 模型 / 日志 / 归档 / 备份 可配；只接受绝对路径且目录需已存在；改动需重启生效</td></tr>
    <tr><td>备份</td><td>每日 SQLite .backup + artifacts 增量同步，保留 14 天</td></tr>
    <tr><td>升级</td><td>替换代码目录重启（中断 &lt; 30 s）；模型升级走页面发布，不重启进程</td></tr>
  </table>

  <h3>Windows 上必须提前处理的四件事</h3>
  <table>
    <tr><th style="width:26%">设置</th><th>不做会怎样</th></tr>
    <tr><td>关闭睡眠 / 快速启动</td><td>机器睡着，产线推图全部超时</td></tr>
    <tr><td>Defender 排除数据目录</td><td>模型加载与训练 IO 慢 2~5 倍，SQLite 频繁锁冲突</td></tr>
    <tr><td>控制台强制 UTF-8</td><td>Rich 进度条打 emoji 直接崩溃（已在实际环境中踩到）</td></tr>
    <tr><td>设满活动时间</td><td>夜里 Windows 更新重启，打断训练</td></tr>
  </table>`;

const p16 = `
  <h2>实施计划与边界</h2>

  <h3>12 周 / 约 58.5 人日（1 人）</h3>
  <table>
    <tr><th style="width:14%">周</th><th>交付</th><th style="width:30%">门禁</th></tr>
    <tr><td>W1–W2</td><td>服务骨架（Windows 服务 + 离线包）、异步推理、结果落库</td><td>推 2K 图 3 秒内出判级</td></tr>
    <tr><td>W3–W4</td><td>产品/绑定/配置单、预热与 resolve 接口、上传与冻结验收集</td><td>编码 → 模型 → 加载状态可查</td></tr>
    <tr><td>W5–W6</td><td>训练队列、模型版本、发布/回滚、冒烟集校验</td><td>发布生效 / 回滚 30 s / 错绑被拦</td></tr>
    <tr><td>W7–W8</td><td>抽样与反馈、CSV 复核、自动训练与候选门槛</td><td>池满自动出候选，未达标不上线</td></tr>
    <tr><td>W9–W10</td><td>压测、故障演练、备份恢复、部署演练</td><td>新机器 ≤30 分钟跑通</td></tr>
    <tr><td>W11–W12</td><td>页面收口、文档、演示脚本、缓冲</td><td>—</td></tr>
  </table>

  <h3>v1 明确不做（进二期）</h3>
  <div class="cards">
    <div class="card2"><b>掩膜标注工具</b><span>当前无掩膜数据；表结构已预留，二期补 UI。</span></div>
    <div class="card2"><b>统计大屏</b><span>数据接口已打底（/api/stats/daily），二期做可视化。</span></div>
    <div class="card2"><b>多产线 / 细粒度权限</b><span>单线试点，先"一线一 token + 一个管理员"。</span></div>
    <div class="card2"><b>TensorRT / 多卡</b><span>当前延迟已达标；有节拍压力再上。</span></div>
  </div>

  <div class="callout">
    <strong>范围提醒：</strong>需求从最初的 47 人日增长到 58.5 人日，八轮追加后
    12 周的缓冲只剩约 1.5 天。建议在此冻结 v1，后续需求统一进二期 backlog。
  </div>`;

const p17 = `
  <h2>附录</h2>

  <h3>A. 交付物清单</h3>
  <table>
    <tr><th style="width:30%">产物</th><th>说明</th></tr>
    <tr><td class="mono">方案文档</td><td>docs/设计方案-异常检测平台.md（26 节，含 15 处多模型审视）</td></tr>
    <tr><td class="mono">可交互原型</td><td>docs/mockup/index.html（13 个页面，单文件离线）</td></tr>
    <tr><td class="mono">使用流程图</td><td>docs/diagrams/usage.html（Typed JSON 可改）</td></tr>
    <tr><td class="mono">系统流程图</td><td>docs/diagrams/system.html（Typed JSON 可改）</td></tr>
    <tr><td class="mono">实施计划</td><td>tasks/plan.md + tasks/todo.md</td></tr>
    <tr><td class="mono">主题规范</td><td>docs/mockup/theme.css（橙色主题 token 层）</td></tr>
  </table>

  <h3>B. 术语</h3>
  <table>
    <tr><td style="width:22%"><b>产品编码</b></td><td>现场助记符，例如 AB-1234-02。一个编码绑一个模型，一个模型可绑多个编码；编码创建后不可改。</td></tr>
    <tr><td><b>模型</b></td><td>一个检测任务，拥有独立数据集、版本线与阈值。</td></tr>
    <tr><td><b>版本</b></td><td>模型内递增（v1、v2…），发布只切换"该模型"的生效版本。</td></tr>
    <tr><td><b>配置单</b></td><td>技术人员预置的一组编码，操作工单击一次加载其中全部模型。</td></tr>
    <tr><td><b>bundle</b></td><td>模型交付包：元数据 + ONNX + 权重 + 配方，可拷贝、可回滚。</td></tr>
    <tr><td><b>冻结验收集</b></td><td>创建时切分并锁定指纹的验证集，永不参与训练，用于判断模型是否退化。</td></tr>
    <tr><td><b>冒烟集</b></td><td>每个产品 3~5 张已知结果，发布前校验绑定是否正确。</td></tr>
  </table>

  <div class="quote" style="margin-top:6mm">
    本文档描述的是 v1 方案。界面为模拟数据的原型；算法指标（1.9 ms、122 MB）
    为本机实测值，迁移到 5090 后需重新标定。
  </div>`;

const inner = [...pages.slice(1), p14, p15, p16, p17];
const TOTAL = inner.length + 1;

const coverSection = `<section class="page" style="padding:0">
  ${cover.replace('style="margin:-16mm -17mm; padding:16mm 17mm; height:297mm; position:relative;"',
                  'style="height:297mm; padding:16mm 17mm; position:relative;"')}
</section>`;

const body = coverSection + inner.map((b, i) => {
  const land = b.startsWith('<!--land-->');
  return page(land ? b.replace('<!--land-->', '') : b, i + 2, TOTAL, land);
}).join('\n');

const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>AIP 工业异常检测平台 · 项目介绍</title>
<style>${CSS}</style></head>
<body>${body}</body></html>`;

fs.writeFileSync(path.join(here, 'report.html'), html, 'utf8');
console.log('report.html written:', (html.length / 1024 / 1024).toFixed(2), 'MB');
