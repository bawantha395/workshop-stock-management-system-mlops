import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
const root = fileURLToPath(new URL("..", import.meta.url));
const P = "11111111-1111-1111-1111-111111111111", PART = "22222222-2222-2222-2222-222222222222";
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));

async function mount(mode) {
  const result = await build({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {Counter} from './src/Counter';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<Counter owner={false} initialMode="${mode}" onChanged={()=>{}} items={[{id:'${PART}',sku:'OF-112',name:'Oil filter OF-112',category:'Filters',brand:'Toyota',grade:'',capacity:'',barcode:null,unit:'UNIT',quantity:9,selling_price:0,reorder_level:2,image_id:null}]}/>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM('<div id="root"></div>', { url: "https://stock.test", runScripts: "dangerously" }), w = dom.window;
  w.Headers = Headers; w.STOCKLANE_CONFIG = { authMode: "local" }; w.crypto.randomUUID = () => "abcdefabcdefabcdefab";
  const writes = [];
  w.fetch = async (url, options) => {
    if (options?.method === "POST") { writes.push({ url, key: new Headers(options.headers).get("Idempotency-Key"), body: JSON.parse(options.body) }); return new Response("{}", { status: 200 }); }
    if (String(url).endsWith("/handovers")) return new Response(JSON.stringify([{ id: "h1", product_id: PART, sku: "OF-112", name: "Oil filter OF-112", unit: "UNIT", quantity: 3, outstanding: 2, created_at: "2026-10-28T06:00:00Z" }]), { status: 200 });
    return new Response(JSON.stringify([{ id: P, name: "Nimal" }]), { status: 200 });
  };
  w.eval(result.outputFiles[0].text); await tick(60);
  const button = (text) => [...w.document.querySelectorAll("button")].find((b) => b.textContent.includes(text));
  return { w, dom, writes, button };
}

test("giving a part takes a search or scan, a quantity and one tap on a name", async () => {
  const { w, dom, writes, button } = await mount("give");
  const search = w.document.querySelector(".counter-search input");
  const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
  setter.call(search, "oil"); search.dispatchEvent(new w.Event("input", { bubbles: true })); await tick();
  button("Oil filter OF-112").click(); await tick();
  w.document.querySelector('[aria-label="One more"]').click(); await tick();
  button("Nimal").click(); await tick();
  const confirm = button("Give 2 × Oil filter OF-112 to Nimal");
  assert.ok(confirm); confirm.click(); await tick(60);
  assert.equal(writes.length, 1);
  assert.deepEqual({ ...writes[0].body, note: undefined }, { kind: "STOCK_OUT", productId: PART, quantity: 2, receiverId: P, note: undefined });
  assert.ok(writes[0].key);
  assert.match(w.document.body.textContent, /Recorded: 2 × Oil filter OF-112 given to Nimal/);
  w.cleanup(); dom.window.close();
});

test("taking a part back lists what the person still has out", async () => {
  const { w, dom, writes, button } = await mount("back");
  button("Nimal").click(); await tick(60);
  assert.match(w.document.body.textContent, /2 still out/);
  button("Oil filter OF-112").click(); await tick();
  button("Take back 1 × Oil filter OF-112").click(); await tick(60);
  assert.equal(writes[0].body.kind, "RETURN"); assert.equal(writes[0].body.issueId, "h1"); assert.equal(writes[0].body.quantity, 1);
  w.cleanup(); dom.window.close();
});

test("cards and labels are recognised from their QR values", async () => {
  const result = await build({ stdin: { contents: `export {personFromCard,partFromCode} from './src/Counter';`, resolveDir: root, loader: "ts" }, bundle: true, write: false, format: "iife", globalName: "C", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM("", { runScripts: "dangerously" }); dom.window.STOCKLANE_CONFIG = { authMode: "local" }; dom.window.eval(result.outputFiles[0].text);
  const { personFromCard, partFromCode } = dom.window.C;
  assert.equal(personFromCard("stocklane:person:v1:" + P, [{ id: P, name: "Nimal" }]).name, "Nimal");
  assert.equal(personFromCard("stocklane:v1:" + P, [{ id: P, name: "Nimal" }]), null);
  assert.equal(partFromCode("stocklane:v1:" + PART, [{ id: PART, name: "Oil filter" }]).name, "Oil filter");
  dom.window.close();
});
