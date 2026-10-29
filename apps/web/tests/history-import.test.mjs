import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
const root = fileURLToPath(new URL("..", import.meta.url));
const real = readFileSync(new URL("../../../datasets/real-data/online-retail-ii/sales-history-import.json", import.meta.url), "utf8");

async function load() {
  const result = await build({ entryPoints: [root + "src/historyImport.ts"], bundle: true, write: false, format: "esm", platform: "neutral" });
  return import("data:text/javascript;base64," + Buffer.from(result.outputFiles[0].text).toString("base64"));
}

test("real UCI file aligns by whole weeks to yesterday, like the Python preparation", async () => {
  const { alignToYesterday, readHistory } = await load();
  const file = readHistory(real);
  const { file: aligned, shiftDays } = alignToYesterday(file, "2026-10-29");
  assert.equal(shiftDays, 5439); // same as mlops/real_data/online_retail.py align() for this date
  assert.equal(aligned.dateAlignment, undefined);
  const last = aligned.products.flatMap((p) => p.sales.map((s) => s.date)).sort().at(-1);
  assert.equal(last, "2026-10-28");
  assert.match(aligned.note, /5439 days \(777 whole weeks\)/);
  const before = file.products[0].sales[0], after = aligned.products[0].sales[0];
  assert.equal(new Date(before.date).getUTCDay(), new Date(after.date).getUTCDay());
  assert.equal(after.quantity, before.quantity);
});

test("import page sends the aligned file once the license is confirmed", async () => {
  const result = await build({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {StockReport} from './src/StockReport';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<StockReport/>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM('<div id="root"></div>', { url: "https://stock.test", runScripts: "dangerously" }), w = dom.window;
  w.Headers = Headers; w.STOCKLANE_CONFIG = { authMode: "local" }; const writes = [];
  w.fetch = async (url, options) => {
    if (options?.method === "POST") { writes.push({ url, key: new Headers(options.headers).get("Idempotency-Key"), body: JSON.parse(options.body) }); return new Response(JSON.stringify({ message: "Imported 1 items", trackingFrom: "2026-01-01" }), { status: 200 }); }
    if (String(url).includes("/api/forecast")) return new Response(JSON.stringify({ status: "not_trained", products: [] }), { status: 200 });
    return new Response(JSON.stringify([]), { status: 200 });
  };
  w.eval(result.outputFiles[0].text); await new Promise((r) => setTimeout(r, 60));
  const small = JSON.stringify({ source: "UCI Online Retail II", license: "CC BY 4.0", dateAlignment: "whole-weeks-to-yesterday", products: [{ sku: "UCI-1", openingDate: "2011-11-20", openingQuantity: 100, sales: Array.from({ length: 10 }, (_, i) => ({ date: `2011-11-${21 + i}`, quantity: 2 })) }] });
  const input = w.document.querySelector('input[type="file"]');
  Object.defineProperty(input, "files", { value: [{ text: async () => small }] });
  input.dispatchEvent(new w.Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 40));
  const button = [...w.document.querySelectorAll("button")].find((b) => b.textContent === "Bring in sales");
  assert.equal(button.disabled, true);
  [...w.document.querySelectorAll('input[type="checkbox"]')].find((c) => c.parentElement.textContent.includes("license")).click();
  await new Promise((r) => setTimeout(r, 20)); assert.equal(button.disabled, false);
  button.click(); await new Promise((r) => setTimeout(r, 40));
  assert.equal(writes.length, 1); assert.match(writes[0].url, /\/api\/inventory\/imports\/sales-history$/); assert.ok(writes[0].key);
  const sent = writes[0].body.products[0];
  assert.equal(writes[0].body.dateAlignment, undefined);
  assert.ok(sent.sales[0].date > "2026-01-01" && new Date(sent.sales[0].date).getUTCDay() === new Date("2011-11-21").getUTCDay() && sent.sales.length >= 4);
  assert.match(w.document.body.textContent, /Imported 1 items/);
  w.cleanup(); dom.window.close();
});
