import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
import QRCode from "qrcode";

const appRoot = fileURLToPath(new URL("..", import.meta.url));
const compiled = await build({
  stdin: {
    contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {Scanner} from './src/Scanner';const root=createRoot(document.getElementById('root'));window.stopScanner=()=>root.unmount();root.render(<Scanner onScan={value=>window.scanResults.push(value)} onClose={()=>root.unmount()}/>);`,
    resolveDir: appRoot,
    loader: "tsx",
  },
  bundle: true,
  write: false,
  platform: "browser",
  format: "iife",
  define: { "process.env.NODE_ENV": '"production"' },
});
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("live camera decodes an actual QR once and releases camera without uploading frames", async () => {
  const value = "stocklane:v1:12345678-1234-4234-8234-123456789012";
  const qr = QRCode.create(value, { errorCorrectionLevel: "M" }).modules;
  const scale = 8,
    margin = 4,
    width = (qr.size + margin * 2) * scale;
  const pixels = new Uint8ClampedArray(width * width * 4);
  for (let y = 0; y < width; y++)
    for (let x = 0; x < width; x++) {
      const row = Math.floor(y / scale) - margin,
        col = Math.floor(x / scale) - margin;
      const black =
        row >= 0 &&
        col >= 0 &&
        row < qr.size &&
        col < qr.size &&
        qr.get(row, col);
      const offset = (y * width + x) * 4;
      pixels[offset] =
        pixels[offset + 1] =
        pixels[offset + 2] =
          black ? 0 : 255;
      pixels[offset + 3] = 255;
    }
  const dom = new JSDOM('<div id="root"></div>', {
      url: "https://stock.test",
      runScripts: "dangerously",
    }),
    w = dom.window;
  let stopped = 0,
    uploads = 0;
  w.scanResults = [];
  w.fetch = () => {
    uploads++;
    throw Error("Camera frames must remain local");
  };
  Object.defineProperty(w.navigator, "mediaDevices", {
    value: {
      getUserMedia: async () => ({
        getTracks: () => [{ stop: () => stopped++ }],
      }),
    },
  });
  Object.defineProperties(w.HTMLVideoElement.prototype, {
    readyState: { get: () => 4 },
    videoWidth: { get: () => width },
    videoHeight: { get: () => width },
  });
  w.HTMLVideoElement.prototype.play = async () => {};
  w.HTMLCanvasElement.prototype.getContext = () => ({
    drawImage() {},
    getImageData: () => ({ data: pixels, width, height: width }),
  });
  w.eval(compiled.outputFiles[0].text);
  for (let i = 0; i < 80 && w.scanResults.length === 0; i++) await delay(10);
  assert.deepEqual(Array.from(w.scanResults), [value]);
  await delay(250);
  assert.equal(w.scanResults.length, 1);
  assert.equal(uploads, 0);
  assert.ok(stopped >= 1);
  w.stopScanner();
  w.close();
});

test("camera denial offers alternate methods instead of trapping the task", async () => {
  const dom = new JSDOM('<div id="root"></div>', {
      url: "https://stock.test",
      runScripts: "dangerously",
    }),
    w = dom.window;
  w.scanResults = [];
  Object.defineProperty(w.navigator, "mediaDevices", {
    value: {
      getUserMedia: async () => {
        throw Error("Permission denied");
      },
    },
  });
  w.eval(compiled.outputFiles[0].text);
  for (let i = 0; i < 80 && !w.document.querySelector('[role="alert"]'); i++)
    await delay(10);
  assert.match(
    w.document.querySelector('[role="alert"]').textContent,
    /camera access/,
  );
  assert.ok(
    [...w.document.querySelectorAll("button")].some(
      (button) => button.textContent === "Use another method",
    ),
  );
  w.stopScanner();
  w.close();
});
