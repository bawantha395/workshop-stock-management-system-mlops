import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
test("receive and issue drafts survive partial failure and reload without duplicate stock", async () => {
  const source = fileURLToPath(new URL("../src/main.tsx", import.meta.url));
  const bundled = await build({
    entryPoints: [source],
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    loader: { ".css": "empty", ".woff2": "empty" },
    define: { "process.env.NODE_ENV": '"production"' },
  });
  const dom = new JSDOM('<div id="root"></div>', {
    url: "https://stock.test",
    runScripts: "dangerously",
  });
  let w = dom.window;
  w.STOCKLANE_CONFIG = {
    authMode: "local",
    authority: "",
    clientId: "",
    scope: "",
  };
  w.Headers = Headers;
  w.confirm = () => true;
  const id = "12345678-1234-4234-8234-123456789012",
    other = "22345678-1234-4234-8234-123456789012";
  let qty = 10,
    requests = [],
    fail = false;
  const saved = new Map();
  const item = (p = id) => ({
    id: p,
    sku: p === id ? "FILTER" : "BELT",
    name: p === id ? "Cabin air filter" : "Drive belt",
    brand: "Example",
    category: "Parts",
    part_number: p === id ? "AC-123" : "BELT-2",
    location: "Shelf A",
    unit: "UNIT",
    quantity: p === id ? qty : 10,
    reorder_level: 2,
    grade: "",
    capacity: "",
    archived: false,
  });
  w.fetch = async (path, options = {}) => {
    let data = [];
    if (path.endsWith("/session"))
      data = { name: "owner", roles: ["ROLE_OWNER"] };
    else if (path.endsWith("/status"))
      data = { modelReady: true, bedrockConfigured: false };
    else if (path.endsWith("/products")) data = [item(), item(other)];
    else if (path.endsWith("/movements") && options.method === "POST") {
      const body = JSON.parse(options.body),
        key = options.headers.get("Idempotency-Key");
      requests.push({ body, key });
      if (body.productId === other && fail) {
        fail = false;
        throw Error("Temporary connection failure");
      }
      if (saved.has(key)) data = saved.get(key);
      else {
        data = { id: "m" + saved.size };
        saved.set(key, data);
        if (body.productId === id)
          qty += body.kind === "RECEIPT" ? body.quantity : -body.quantity;
      }
    }
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  w.eval(bundled.outputFiles[0].text);
  const delay = () => new Promise((r) => setTimeout(r, 20));
  const wait = async (fn) => {
    for (let i = 0; i < 150; i++) {
      if (fn()) return;
      await delay();
    }
    throw Error(
      "Timed out: " +
        fn.toString() +
        "\n" +
        w.document.body.textContent.slice(-1700),
    );
  };
  const click = async (text) => {
    const el = [...w.document.querySelectorAll("button")].find(
      (e) => e.textContent.trim() === text,
    );
    assert.ok(el, "Missing button " + text);
    assert.equal(el.disabled, false, "Button disabled " + text);
    el.click();
    await delay();
  };
  const fill = async (selector, value) => {
    const el = w.document.querySelector(selector);
    assert.ok(el, selector);
    Object.getOwnPropertyDescriptor(
      w.HTMLInputElement.prototype,
      "value",
    ).set.call(el, value);
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
    await delay();
  };
  const scan = async (pid, amount) => {
    await fill('[aria-label="QR value"]', "stocklane:v1:" + pid);
    await click("Find");
    await fill("#movement-quantity", String(amount));
    await click("Add to receipt");
  };
  await wait(
    () =>
      w.document.querySelector(".receive-tile") &&
      !w.document.querySelector(".receive-tile").disabled,
  );
  w.document.querySelector(".receive-tile").click();
  await delay();
  await wait(() => w.document.querySelector('[aria-label="Close scanner"]'));
  w.document.querySelector('[aria-label="Close scanner"]').click();
  await delay();
  await scan(id, 5);
  assert.equal(requests.length, 0);
  await click("Workspace");
  assert.ok(w.document.body.textContent.includes("Receipt · 1 lines"));
  w.document.querySelector(".resume-row").click();
  await delay();
  assert.equal(w.document.querySelectorAll(".draft-line").length, 1);
  await scan(other, 2);
  fail = true;
  await click("Confirm receipt");
  await wait(() =>
    w.document.body.textContent.includes("Retry unfinished lines"),
  );
  assert.equal(qty, 15);
  assert.equal(saved.size, 1);
  assert.ok(
    w.document
      .querySelector('[role="alert"]')
      .textContent.includes("Some lines may already be recorded"),
  );
  const persisted = JSON.parse(
    w.sessionStorage.getItem("stocklane.tasks.v2.owner"),
  );
  assert.equal(persisted.IN.lines[0].movementId, "m0");
  assert.equal(persisted.IN.lines[1].attempted, true);
  const state = w.sessionStorage.getItem("stocklane.tasks.v2.owner");
  const fetchStub = w.fetch;
  const reloaded = new JSDOM('<div id="root"></div>', {
    url: "https://stock.test",
    runScripts: "dangerously",
  });
  w.close();
  w = reloaded.window;
  w.STOCKLANE_CONFIG = {
    authMode: "local",
    authority: "",
    clientId: "",
    scope: "",
  };
  w.Headers = Headers;
  w.confirm = () => true;
  w.fetch = fetchStub;
  w.sessionStorage.setItem("stocklane.tasks.v2.owner", state);
  w.eval(bundled.outputFiles[0].text);
  await wait(() => w.document.querySelector(".resume-row"));
  w.document.querySelector(".resume-row").click();
  await delay();
  await click("Retry unfinished lines");
  await wait(() => w.document.body.textContent.includes("Receipt confirmed."));
  assert.equal(qty, 15);
  assert.equal(saved.size, 2);
  assert.equal(requests[1].key, requests[2].key);
  assert.equal(requests.filter((r) => r.body.productId === id).length, 1);
  await click("Workspace");
  w.document.querySelector(".issue-tile").click();
  await delay();
  await wait(() => w.document.querySelector('[aria-label="Close scanner"]'));
  w.document.querySelector('[aria-label="Close scanner"]').click();
  await delay();
  await fill('[aria-label="QR value"]', "stocklane:v1:" + id);
  await click("Find");
  await fill("#movement-quantity", "16");
  assert.equal(
    [...w.document.querySelectorAll("button")].find(
      (e) => e.textContent.trim() === "Add to stock-out list",
    ).disabled,
    true,
  );
  await fill("#movement-quantity", "2");
  await click("Add to stock-out list");
  await click("Confirm stock-out");
  await wait(() =>
    w.document.body.textContent.includes("Stock-out confirmed."),
  );
  assert.equal(qty, 13);
  assert.equal(requests.at(-1).body.jobId, null);
  assert.equal(requests.at(-1).body.kind, "STOCK_OUT");
  await click("Workspace");
  const count = [...w.document.querySelectorAll(".task-tile")].find((e) =>
    e.textContent.includes("Count stock"),
  );
  count.click();
  await delay();
  await fill('[aria-label="Search count items"]', "AC-123");
  w.document.querySelector(".lookup-row").click();
  await delay();
  await fill('input[type="number"]', "12");
  assert.ok(w.document.body.textContent.includes("There is a difference"));
  assert.equal(qty, 13);
  assert.equal(requests.length, 4);
  w.close();
});
