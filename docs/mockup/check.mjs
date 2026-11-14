#!/usr/bin/env node
/**
 * 原型冒烟检查：把 index.html 里的脚本抽出来，在 stub DOM 里跑一遍所有页面，
 * 任何一个视图抛异常就退出码 1。
 *
 * 用法：node docs/mockup/check.mjs
 *
 * 为什么需要它：原型是纯前端单文件，一个未定义的辅助函数就会整页白屏，
 * 而且只有点到那一页才会发现。这个脚本 0.2 秒就能把所有页面过一遍。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, 'index.html'), 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) {
  console.error('未找到 <script> 块');
  process.exit(1);
}
const source = match[1];

/** 最小 DOM stub：够 render() 跑完即可。 */
const stub = () => ({
  innerHTML: '', textContent: '', style: {}, value: '', disabled: false,
  appendChild() {}, remove() {}, replaceWith() {},
  querySelector() { return stub(); }, querySelectorAll() { return []; }, addEventListener() {},
  getContext() {
    return new Proxy({}, { get: (_t, k) => {
      if (k === 'createLinearGradient' || k === 'createRadialGradient') return () => ({ addColorStop() {} });
      return () => {};
    }, set: () => true });
  },
  width: 100, height: 100,
});

const sandbox = {
  console,
  document: {
    querySelector: () => stub(), getElementById: () => stub(), createElement: () => stub(),
    addEventListener() {}, body: { appendChild() {} },
  },
  window: { scrollTo() {} },
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
  confirm: () => true,
  prompt: () => '8900',
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
// 让脚本把内部对象挂到 sandbox 上，便于外部遍历
vm.runInContext(source + '\n;globalThis.__mock = { VIEWS, NAV_ICONS, API_SPEC, API_GROUPS, S, go, review, setFilter, wizSet, wizNext, wizToggle, wizCount, createModel, openBind, bindSet, saveBind, toggleActive, deleteBind, bindSearch, bindFilter, openModal, modalSet, saveModal, deleteEntity, samplingSet, samplingCap, validateSampling, resetSampling, apiSelect };', sandbox, { filename: 'mockup.js' });

const { VIEWS } = sandbox.__mock;
if (!VIEWS) {
  console.error('脚本没有暴露 VIEWS，检查末尾的 __mock 导出是否被删掉');
  process.exit(1);
}

let failures = 0;
for (const [key, view] of Object.entries(VIEWS)) {
  try {
    const out = view.r();
    if (typeof out !== 'string' || out.length < 50) throw new Error('输出为空或过短');
    console.log(`  ✓ ${key.padEnd(10)} ${String(out.length).padStart(5)} chars`);
  } catch (error) {
    failures++;
    console.error(`  ✗ ${key.padEnd(10)} ${error.message}`);
  }
}

// 关键交互也过一遍（它们会改状态并重渲染）
const actions = [
  ['go(review)', () => sandbox.__mock.go('review')],
  ['review(1)', () => sandbox.__mock.review(1)],
  ['setFilter(all)', () => sandbox.__mock.setFilter('all')],
];
for (const [name, fn] of actions) {
  try { fn(); console.log(`  ✓ ${name}`); }
  catch (error) { failures++; console.error(`  ✗ ${name} ${error.message}`); }
}

// 新建模型向导走一遍：填名 → 选产品 → 填数据 → 走到确认 → 创建
const wizardWalk = [
  ['wizard: 填名称', () => sandbox.__mock.wizSet('name', '冒烟测试模型')],
  ['wizard: 下一步(1→2)', () => sandbox.__mock.wizNext()],
  ['wizard: 选产品', () => sandbox.__mock.wizToggle('GH-9001-01')],
  ['wizard: 下一步(2→3)', () => sandbox.__mock.wizNext()],
  ['wizard: 加正常品', () => sandbox.__mock.wizCount('train', 200)],
  ['wizard: 加缺陷图', () => sandbox.__mock.wizCount('defect', 20)],
  ['wizard: 下一步(3→4)', () => sandbox.__mock.wizNext()],
  ['wizard: 下一步(4→5)', () => sandbox.__mock.wizNext()],
  ['wizard: 创建', () => sandbox.__mock.createModel()],
];
const before = sandbox.__mock.S.models.length;
for (const [name, fn] of wizardWalk) {
  try { fn(); console.log(`  ✓ ${name}`); }
  catch (error) { failures++; console.error(`  ✗ ${name} ${error.message}`); }
}
if (sandbox.__mock.S.models.length !== before + 1) {
  failures++;
  console.error('  ✗ 向导创建后模型数量没有增加');
}

// 绑定关系 CRUD：新建 → 改绑 → 停用 → 删除
const beforeBind = sandbox.__mock.S.products.length;
const crudWalk = [
  ['CRUD: 新建绑定', () => {
    sandbox.__mock.openBind('create');
    sandbox.__mock.bindSet('code', 'ZZ-0001-01');
    sandbox.__mock.bindSet('desc', '冒烟测试编码');
    sandbox.__mock.bindSet('model', sandbox.__mock.S.models[0].id);
    sandbox.__mock.saveBind();
  }],
  ['CRUD: 搜索', () => sandbox.__mock.bindSearch('ZZ')],
  ['CRUD: 改绑模型', () => {
    sandbox.__mock.openBind('edit', 'ZZ-0001-01');
    sandbox.__mock.bindSet('model', sandbox.__mock.S.models[1].id);
    sandbox.__mock.saveBind();
  }],
  ['CRUD: 停用', () => sandbox.__mock.toggleActive('ZZ-0001-01')],
  ['CRUD: 删除', () => sandbox.__mock.deleteBind('ZZ-0001-01')],
];
for (const [name, fn] of crudWalk) {
  try { fn(); console.log(`  ✓ ${name}`); }
  catch (error) { failures++; console.error(`  ✗ ${name} ${error.message}`); }
}
if (sandbox.__mock.S.products.length !== beforeBind) {
  failures++;
  console.error(`  ✗ CRUD 后编码数量应回到 ${beforeBind}，实际 ${sandbox.__mock.S.products.length}`);
}

// 各实体的 CRUD：新建 → 改 → 删（最终数量应回到初值）
const S = sandbox.__mock.S;
const p0 = {presets: S.presets.length, datasets: S.datasets.length, legal: S.legalHolds.length};
const entityWalk = [
  ['CRUD: 配置单 新建', () => { sandbox.__mock.openModal('preset'); sandbox.__mock.modalSet('name','冒烟配置单'); sandbox.__mock.modalSet('codes','AB-1234-01 CD-5566-01'); sandbox.__mock.saveModal(); }],
  ['CRUD: 配置单 编辑', () => { sandbox.__mock.openModal('preset', S.presets[S.presets.length-1].id); sandbox.__mock.modalSet('note','改过'); sandbox.__mock.saveModal(); }],
  ['CRUD: 配置单 删除', () => sandbox.__mock.deleteEntity('preset', S.presets[S.presets.length-1].id)],
  ['CRUD: 数据集 新建', () => { sandbox.__mock.openModal('dataset'); sandbox.__mock.modalSet('name','冒烟数据集'); sandbox.__mock.saveModal(); }],
  ['CRUD: 数据集 删除', () => sandbox.__mock.deleteEntity('dataset', S.datasets[S.datasets.length-1].id)],
  ['CRUD: 法务锁定 新增', () => { sandbox.__mock.openModal('legal'); sandbox.__mock.modalSet('reason','冒烟锁定'); sandbox.__mock.modalSet('scope','AB-1234-01'); sandbox.__mock.saveModal(); }],
  ['CRUD: 法务锁定 解除', () => sandbox.__mock.deleteEntity('legal', S.legalHolds[S.legalHolds.length-1].id)],
  ['CRUD: 模型 重命名', () => { sandbox.__mock.openModal('model', S.models[0].id); sandbox.__mock.modalSet('name','冒烟改名'); sandbox.__mock.saveModal(); }],
];
for (const [name, fn] of entityWalk) {
  try { fn(); console.log(`  ✓ ${name}`); }
  catch (error) { failures++; console.error(`  ✗ ${name} ${error.message}`); }
}
if (S.presets.length !== p0.presets || S.datasets.length !== p0.datasets || S.legalHolds.length !== p0.legal) {
  failures++;
  console.error(`  ✗ 实体 CRUD 后数量没回到初值（presets ${S.presets.length}/${p0.presets}，datasets ${S.datasets.length}/${p0.datasets}，legal ${S.legalHolds.length}/${p0.legal}）`);
}
if (S.models[0].name !== '冒烟改名') {
  failures++;
  console.error('  ✗ 模型重命名没有生效');
}

// 抽样配置校验：默认合法 → 改坏要拦住 → 恢复后重新合法
const samplingWalk = [
  ['配置: 默认合法', () => {
    const errs = sandbox.__mock.validateSampling();
    if (errs.length) throw new Error('默认配置不应报错：' + errs.join('；'));
  }],
  ['配置: 总量小于分层之和应被拦', () => {
    sandbox.__mock.samplingSet('dailyCap', 20);
    if (!sandbox.__mock.validateSampling().length) throw new Error('未拦截');
    sandbox.__mock.resetSampling();
  }],
  ['配置: 超人工预算应被拦', () => {
    sandbox.__mock.samplingCap('low', 200);
    if (!sandbox.__mock.validateSampling().length) throw new Error('未拦截超预算');
    sandbox.__mock.resetSampling();
  }],
  ['配置: 恢复默认后合法', () => {
    if (sandbox.__mock.validateSampling().length) throw new Error('恢复默认后仍报错');
  }],
];
for (const [name, fn] of samplingWalk) {
  try { fn(); console.log(`  ✓ ${name}`); }
  catch (error) { failures++; console.error(`  ✗ ${name} ${error.message}`); }
}

// 每个页面都必须有图标，否则左侧菜单会渲染出 "undefined"
const missingIcons = Object.keys(VIEWS).filter((k) => !sandbox.__mock.NAV_ICONS[k]);
if (missingIcons.length) {
  failures++;
  console.error(`  ✗ 缺少导航图标：${missingIcons.join(', ')}`);
} else {
  console.log(`  ✓ 导航图标齐全（${Object.keys(VIEWS).length} 个）`);
}

// API 说明页：清单与分组必须一致，且每个接口都要有响应样例
const apiProblems = [];
const grouped = new Set();
for (const g of sandbox.__mock.API_GROUPS) {
  for (const id of g.ids) {
    grouped.add(id);
    if (!sandbox.__mock.API_SPEC[id]) apiProblems.push(`分组 ${g.name} 引用了不存在的接口 ${id}`);
  }
}
for (const [id, spec] of Object.entries(sandbox.__mock.API_SPEC)) {
  if (!grouped.has(id)) apiProblems.push(`接口 ${id} 不在任何分组里（页面上看不到）`);
  if (!spec.m || !spec.p || !spec.d || !spec.res) apiProblems.push(`接口 ${id} 字段不全`);
}
if (apiProblems.length) {
  failures++;
  console.error('  ✗ API 清单：' + apiProblems.join('；'));
} else {
  console.log(`  ✓ API 清单一致（${Object.keys(sandbox.__mock.API_SPEC).length} 个接口）`);
}

if (failures) {
  console.error(`\n${failures} 项失败`);
  process.exit(1);
}
console.log(`\n全部通过（${Object.keys(VIEWS).length} 个页面）`);
