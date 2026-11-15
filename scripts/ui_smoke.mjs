/**
 * 页面冒烟：用 CDP 打开每个 hash 路由，检查渲染文本与 JS 异常。
 *
 * 用法：先启动带 --remote-debugging-port=9223 的 Edge，再运行本脚本。
 *   node scripts/ui_smoke.mjs
 */

const BASE = process.env.CDP_BASE || "http://127.0.0.1:9223";
const APP = process.env.APP_BASE || "http://127.0.0.1:8100";

const PAGES = [
  ["workbench", "今日判定"],
  ["wizard", "新建向导"],
  ["catalog", "产品编码"],
  ["quality", "复核队列"],
  ["cases", "判例库"],
  ["datasets", "数据集是训练集快照"],
  ["blind", "抽检批次"],
  ["training", "训练新版本"],
  ["system", "最近操作"],
  ["settings", "设置"],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const created = await (
    await fetch(`${BASE}/json/new?about:blank`, { method: "PUT" })
  ).json();
  const ws = new WebSocket(created.webSocketDebuggerUrl);
  const pending = new Map();
  const exceptions = [];
  let seq = 0;

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
    if (msg.method === "Runtime.exceptionThrown") {
      exceptions.push(
        msg.params.exceptionDetails.exception?.description ||
          msg.params.exceptionDetails.text
      );
    }
  };

  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const id = ++seq;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });

  await new Promise((r) => (ws.onopen = r));
  await send("Runtime.enable");
  await send("Page.enable");

  const failures = [];
  for (const [name, marker] of PAGES) {
    exceptions.length = 0;
    await send("Page.navigate", { url: `${APP}/admin#/${name}` });
    await sleep(1500);
    const res = await send("Runtime.evaluate", {
      expression: "document.body.innerText",
      returnByValue: true,
    });
    const text = res.result?.result?.value || "";
    const bad =
      exceptions.length > 0 ||
      text.includes("加载失败") ||
      text.includes("页面脚本异常") ||
      !text.includes(marker);
    if (bad) {
      failures.push({
        page: name,
        marker,
        exceptions: exceptions.slice(0, 2),
        snippet: text.slice(0, 160).replace(/\s+/g, " "),
      });
    }
    console.log(`${bad ? "FAIL" : "ok  "} ${name}`);
  }

  await fetch(`${BASE}/json/close/${created.id}`, { method: "PUT" }).catch(() => {});
  if (failures.length) {
    console.error(JSON.stringify(failures, null, 2));
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 2;
});
