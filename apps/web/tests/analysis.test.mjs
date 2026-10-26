import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
const root = fileURLToPath(new URL("..", import.meta.url));
test("owner analysis sends Sri Lanka date bounds and distinguishes closing from current stock", async () => {
  const result = await build({
    stdin: {
      contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {StockAnalysis} from './src/StockAnalysis';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<StockAnalysis/>);`,
      resolveDir: root,
      loader: "tsx",
    },
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    define: { "process.env.NODE_ENV": '"production"' },
  });
  const dom = new JSDOM('<div id="root"></div>', {
      url: "https://stock.test",
      runScripts: "dangerously",
    }),
    w = dom.window;
  w.Headers = Headers;
  w.STOCKLANE_CONFIG = { authMode: "local" };
  const requests = [];
  w.fetch = async (url) => {
    requests.push(new URL(url, "https://stock.test"));
    const q = requests.at(-1).searchParams;
    return new Response(
      JSON.stringify({
        rows: [
          {
            id: "item",
            sku: "AF-1",
            name: "Air filter",
            brand: "Demo",
            part_number: "P1",
            category: "Filters",
            location: "A",
            unit: "UNIT",
            archived: false,
            opening_quantity: 5,
            added_quantity: 3,
            taken_quantity: 2,
            closing_quantity: 6,
            available_now: 8,
          },
        ],
        total: 1,
        page: 0,
        pageSize: 100,
        from: q.get("from"),
        until: q.get("until"),
        asOf: "2026-10-26T00:00:00Z",
      }),
      { status: 200 },
    );
  };
  w.eval(result.outputFiles[0].text);
  const wait = async (fn) => {
    for (let i = 0; i < 100; i++) {
      if (fn()) return;
      await new Promise((r) => setTimeout(r, 10));
    }
    throw Error("UI did not finish loading");
  };
  await wait(() => w.document.querySelector("tbody tr"));
  const inputs = w.document.querySelectorAll('input[type="datetime-local"]');
  for (const [index, value] of [
    "2025-12-01T00:00",
    "2026-01-01T00:00",
  ].entries()) {
    Object.getOwnPropertyDescriptor(
      w.HTMLInputElement.prototype,
      "value",
    ).set.call(inputs[index], value);
    inputs[index].dispatchEvent(new w.Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 10));
  }
  w.document
    .querySelector("form")
    .dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  await wait(() => requests.length === 2);
  assert.equal(
    requests.at(-1).searchParams.get("from"),
    "2025-11-30T18:30:00.000Z",
  );
  assert.equal(
    requests.at(-1).searchParams.get("until"),
    "2025-12-31T18:30:00.000Z",
  );
  const cells = [...w.document.querySelectorAll("tbody td")].map(
    (td) => td.textContent,
  );
  assert.deepEqual(cells.slice(-5), ["5", "3", "2", "6", "8"]);
  assert.match(w.document.body.textContent, /Start time is included/);
  w.cleanup();
  w.close();
});
