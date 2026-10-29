import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
const root = fileURLToPath(new URL("..", import.meta.url));
const P = "11111111-1111-1111-1111-111111111111", PART = "22222222-2222-2222-2222-222222222222";
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));

async function mount(mode, extra = "") {
  const result = await build({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {Counter} from './src/Counter';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<Counter owner={false} initialMode="${mode}" onChanged={()=>{}} onNewItem={(id)=>{window.newItem=id}} ${extra} items={[{id:'${PART}',sku:'OF-112',name:'Oil filter OF-112',category:'Filters',brand:'Toyota',grade:'',capacity:'',barcode:null,unit:'UNIT',quantity:9,selling_price:0,reorder_level:2,image_id:null}]}/>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM('<div id="root"></div>', { url: "https://stock.test", runScripts: "dangerously" }), w = dom.window;
  w.Headers = Headers; w.STOCKLANE_CONFIG = { authMode: "local" }; w.crypto.randomUUID = () => "abcdefabcdefabcdefab";
  const writes = [];
  w.fetch = async (url, options) => {
    if (String(url).endsWith("/api/vision/qr")) return new Response(JSON.stringify({ value: null }), { status: 200 });
    if (String(url).endsWith("/api/vision/match")) return new Response(JSON.stringify({ imageId: "img-1", candidates: [], state: "UNKNOWN", modelVersion: "m", message: "" }), { status: 200 });
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

test("a part's QR label is recognised, and a person's card no longer exists", async () => {
  const result = await build({ stdin: { contents: `export {partFromCode} from './src/Counter';`, resolveDir: root, loader: "ts" }, bundle: true, write: false, format: "iife", globalName: "C", platform: "browser", define: { "process.env.NODE_ENV": '"production"' } });
  const dom = new JSDOM("", { runScripts: "dangerously" }); dom.window.STOCKLANE_CONFIG = { authMode: "local" }; dom.window.eval(result.outputFiles[0].text);
  const { partFromCode } = dom.window.C;
  assert.equal(partFromCode("stocklane:v1:" + PART, [{ id: PART, name: "Oil filter" }]).name, "Oil filter");
  assert.equal(partFromCode("stocklane:person:v1:" + P, [{ id: P, name: "Nimal" }]), null);
  dom.window.close();
});

test("used up or damaged parts go out without naming a person", async () => {
  const { w, dom, writes, button } = await mount("give");
  const search = w.document.querySelector(".counter-search input");
  const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
  setter.call(search, "oil"); search.dispatchEvent(new w.Event("input", { bubbles: true })); await tick();
  button("Oil filter OF-112").click(); await tick();
  button("Used up / damaged").click(); await tick();
  button("Give 1 × Oil filter OF-112 (used up / damaged)").click(); await tick(60);
  assert.equal(writes[0].body.kind, "STOCK_OUT"); assert.equal(writes[0].body.receiverId, undefined);
  assert.equal(button("Print card"), undefined); assert.equal(button("Scan card"), undefined);
  w.cleanup(); dom.window.close();
});

test("receiving needs only the part and a quantity, and an unknown photo becomes a new item", async () => {
  const { w, dom, writes, button } = await mount("receive");
  const search = w.document.querySelector(".counter-search input");
  const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
  setter.call(search, "oil"); search.dispatchEvent(new w.Event("input", { bubbles: true })); await tick();
  button("Oil filter OF-112").click(); await tick();
  assert.equal(button("Nimal"), undefined); // no person step when stock comes in
  button("Add 1 × Oil filter OF-112 to stock").click(); await tick(60);
  assert.equal(writes[0].body.kind, "RECEIPT"); assert.equal(writes[0].body.productId, PART);
  button("Open camera").click(); await tick(600);
  const input = w.document.querySelector('input[type="file"]');
  assert.ok(input); // no camera in the test browser: the device photo picker is the fallback
  Object.defineProperty(input, "files", { value: [new w.File(["x"], "photo.jpg", { type: "image/jpeg" })] });
  input.dispatchEvent(new w.Event("change", { bubbles: true })); await tick(120);
  assert.match(w.document.body.textContent, /add it as a new item/);
  button("Add as a new item").click(); await tick();
  assert.equal(w.newItem, "img-1");
  w.cleanup(); dom.window.close();
});
