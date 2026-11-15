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

  // 复核页首屏可用性（1440 宽时断言动作区不超出视口、页面不滚动）
  await send("Page.navigate", { url: `${APP}/admin#/quality` });
  await sleep(1800);
  const fit = await (async () => {
    const r = await send("Runtime.evaluate", {
      expression: `JSON.stringify({
        vw: innerWidth, vh: innerHeight,
        page: document.scrollingElement.scrollHeight,
        actions: document.querySelector('.review-actions')?.getBoundingClientRect().bottom ?? -1
      })`,
      returnByValue: true,
    });
    return JSON.parse(r.result?.result?.value || "{}");
  })();
  const semantics = await (async () => { const r = await send("Runtime.evaluate", { expression: `JSON.stringify({ ok: document.getElementById("rOk")?.textContent, ng: document.getElementById("rNg")?.textContent, tip: document.querySelector(".review-tip")?.textContent || "" })`, returnByValue: true }); return JSON.parse(r.result?.result?.value || "{}"); })();
  const semanticsOk = semantics.ok?.includes("OK") && semantics.ng?.includes("NG") && semantics.tip.includes("理由");
  failures.push(...(semanticsOk ? [] : [{ page: "review-semantics", snippet: JSON.stringify(semantics) }]));
  console.log(`${semanticsOk ? "ok  " : "FAIL"} review-semantics`);
  const fitOk = !fit.vw || fit.vw < 1400 || (fit.page <= fit.vh + 1 && fit.actions <= fit.vh + 1);
  failures.push(...(fitOk ? [] : [{ page: "review-fit", snippet: JSON.stringify(fit) }]));
  console.log(`${fitOk ? "ok  " : "FAIL"} review-fit (${fit.page}/${fit.vh}, actions ${fit.actions})`);

  // 参考样例弹窗（有样例时点击缩略图应打开 dialog）
  const refClick = (
    await send("Runtime.evaluate", {
      expression: `(() => { const i = document.querySelector('.ref-strip img'); if (!i) return 'none'; i.click(); return 'ok'; })()`,
      returnByValue: true,
    })
  ).result?.result?.value;
  if (refClick === "ok") {
    await sleep(500);
    const dlgOpen = (
      await send("Runtime.evaluate", {
        expression: "document.getElementById('refDlg')?.open === true",
        returnByValue: true,
      })
    ).result?.result?.value;
    failures.push(...(dlgOpen ? [] : [{ page: "refs-dialog", snippet: "dialog not open" }]));
    console.log(`${dlgOpen ? "ok  " : "FAIL"} refs-dialog`);
    await send("Runtime.evaluate", { expression: "document.getElementById('refDlg')?.close()" });
  } else {
    console.log("ok   refs-dialog (no refs)");
  }

  // 暗色模式检查
  await send("Page.navigate", { url: `${APP}/admin#/workbench` });
  await sleep(1200);
  await send("Runtime.evaluate", { expression: `localStorage.setItem("aip-theme","dark")` });
  await send("Page.reload");
  await sleep(1600);
  const darkBg =
    (
      await send("Runtime.evaluate", {
        expression: "getComputedStyle(document.body).backgroundColor",
        returnByValue: true,
      })
    ).result?.result?.value || "";
  const darkOk = darkBg === "rgb(15, 17, 21)";
  failures.push(...(darkOk ? [] : [{ page: "theme-dark", snippet: darkBg }]));
  console.log(`${darkOk ? "ok  " : "FAIL"} theme-dark (body ${darkBg})`);
  await send("Runtime.evaluate", { expression: `localStorage.removeItem("aip-theme")` });

  // 工位面板单独检查
  exceptions.length = 0;
  await send("Page.navigate", { url: `${APP}/panel` });
  await sleep(1500);
  const panelText = (
    await send("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true })
  ).result?.result?.value || "";
  const panelBad =
    exceptions.length > 0 || panelText.includes("加载失败") || !panelText.includes("AIP 工位面板");
  failures.push(...(panelBad ? [{ page: "panel", snippet: panelText.slice(0, 120) }] : []));
  console.log(`${panelBad ? "FAIL" : "ok  "} panel`);

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
