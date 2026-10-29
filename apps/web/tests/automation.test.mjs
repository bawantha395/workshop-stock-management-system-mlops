import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
const root = fileURLToPath(new URL("..", import.meta.url));
async function load(file) {
  const result = await build({ entryPoints: [root + file], bundle: true, write: false, format: "esm", platform: "neutral" });
  return import("data:text/javascript;base64," + Buffer.from(result.outputFiles[0].text).toString("base64"));
}

test("new-item suggestions fill only empty fields, from AI and from similar stocked items", async () => {
  const { suggestFields } = await load("src/suggestions.ts");
  const stocked = [
    { name: "Castrol GTX 20W-50 4L", brand: "Castrol", category: "Engine oil", location: "Rack B", unit: "UNIT" },
    { name: "Castrol Magnatec 5W-30", brand: "castrol", category: "Engine oil", location: "Rack B", unit: "UNIT" },
    { name: "Bosch spark plug", brand: "Bosch", category: "Spark plugs", location: "Drawer 3", unit: "UNIT" },
  ];
  const s = suggestFields({ brand: "Castrol", grade: "10W-40", capacity: "1L" }, { brand: "Ignored", partNumber: "GTX-1" }, stocked);
  assert.equal(s.brand, undefined); // label text is never replaced
  assert.equal(s.partNumber.value, "GTX-1");
  assert.equal(s.category.value, "Engine oil");
  assert.equal(s.location.value, "Rack B");
  assert.equal(s.name.value, "Castrol 10W-40 1L");
  assert.deepEqual(suggestFields({}, {}, stocked), {});
});

test("reorder suggestions use the forecast where there is one and the reorder level everywhere else", async () => {
  const { reorderSuggestions, runsOut, why } = await load("src/reorder.ts");
  const { reorder, soon, idle } = reorderSuggestions([
    { id: "a", sku: "A", name: "Oil", unit: "UNIT", availableNow: 10, reorderLevel: 5, status: "forecast", next7: 14, next30: 60, suggestedTopUp7: 4 },
    { id: "b", sku: "B", name: "Filter", unit: "UNIT", availableNow: 1, reorderLevel: 5, status: "forecast", next7: 7, next30: 30, suggestedTopUp7: 6 },
    { id: "c", sku: "C", name: "Old part", unit: "UNIT", availableNow: 5, reorderLevel: 5, status: "not_moving", next7: 0, next30: 0, suggestedTopUp7: 0 },
    { id: "d", sku: "D", name: "New part", unit: "UNIT", availableNow: 0, reorderLevel: 5, status: "no_forecast" },
    { id: "e", sku: "E", name: "Gasket", unit: "UNIT", availableNow: 4, reorderLevel: 5, status: "needs_more_history" },
    { id: "f", sku: "F", name: "Bolt", unit: "UNIT", availableNow: 9, reorderLevel: 5, status: "unreliable" },
    { id: "g", sku: "G", name: "No level set", unit: "UNIT", availableNow: 3, reorderLevel: 0, status: "no_forecast" },
  ]);
  assert.deepEqual(reorder.map((r) => r.sku), ["D", "B", "A", "E"]);
  assert.deepEqual(reorder.map((r) => r.order), [10, 6, 4, 6]);
  assert.equal(soon, 3); assert.equal(idle, 1);
  assert.equal(runsOut(reorder[1].daysLeft), "Runs out in ~1 day");
  assert.equal(why(reorder[0]), "Out of stock"); assert.equal(why(reorder[3]), "Order soon");
});

test("owner home shows the reorder card without any click", async () => {
  const result = await build({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {ReorderCard} from './src/ReorderCard';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<ReorderCard/>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM('<div id="root"></div>', { url: "https://stock.test", runScripts: "dangerously" }), w = dom.window;
  w.Headers = Headers; w.STOCKLANE_CONFIG = { authMode: "local" };
  w.fetch = async () => new Response(JSON.stringify({ status: "ready", forecast: "fresh", historyUntil: "2026-10-29", products: [{ id: "a", sku: "MOB", name: "Mobil 5W-30 4L", unit: "UNIT", availableNow: 2, reorderLevel: 5, status: "forecast", next7: 14, next30: 60, suggestedTopUp7: 12 }] }), { status: 200 });
  w.eval(result.outputFiles[0].text); await new Promise((r) => setTimeout(r, 60));
  const text = w.document.body.textContent;
  assert.match(text, /1 item to order/); assert.match(text, /Mobil 5W-30 4L/); assert.match(text, /Order 12/); assert.match(text, /Runs out in ~1 day/);
  assert.ok([...w.document.querySelectorAll("button")].some((b) => b.textContent === "Download purchase list"));
  w.cleanup(); dom.window.close();
});
