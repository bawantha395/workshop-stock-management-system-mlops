import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Camera as CameraIcon, Check, Minus, Plus } from "lucide-react";
import { api, type Match, type Product, type BarcodeLookup } from "./api";

const Camera = React.lazy(() => import("./Camera").then((m) => ({ default: m.Camera })));

type Item = Product & { part_number?: string; location?: string; archived?: boolean };
export type Mode = "receive" | "give";
const PART_QR = /^stocklane:v1:([0-9a-f-]{36})$/;
const key = () => crypto.randomUUID();
const amount = (n: number) => new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(n);

export function partFromCode(value: string, items: Item[]) {
  const id = PART_QR.exec(value.trim())?.[1];
  return items.find((p) => p.id === id) || null;
}

export function Counter({ items, initialMode = "give", picked = null, onNewItem, onBarcodeSuggestion, onChanged }: { items: Item[]; initialMode?: Mode; picked?: Item | null; onNewItem?: (imageId: string) => void; onBarcodeSuggestion?: (barcode: string, suggestions: Record<string, string>) => void; onChanged: () => void }) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [part, setPart] = useState<Item | null>(null);
  const [candidates, setCandidates] = useState<Item[]>([]);
  const [photoId, setPhotoId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [search, setSearch] = useState("");
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [done, setDone] = useState("");
  const commandKey = useRef(key());

  useEffect(() => { setMode(initialMode); }, [initialMode]);
  // A new item registered from this screen comes back selected, ready for its quantity.
  useEffect(() => { if (picked) { setPart(picked); setCandidates([]); setPhotoId(""); setQuantity(1); setError(""); } }, [picked]);

  const reset = (message = "") => {
    setPart(null); setCandidates([]); setPhotoId("");
    setQuantity(1); setSearch(""); setError(""); setDone(message); commandKey.current = key();
  };
  const switchMode = (next: Mode) => { setMode(next); reset(); };

  const onQR = useCallback((value: string) => {
    setCamera(false);
    const found = partFromCode(value, items);
    if (found) { setPart(found); setCandidates([]); setPhotoId(""); setError(""); }
    else setError("This QR is not a stock item. Take a photo of the part instead.");
  }, [items]);
  const identifyPhoto = async (file?: File) => {
    if (!file) return;
    setCamera(false);
    setBusy(true); setError(""); setDone(""); setPart(null); setCandidates([]);
    try {
      const form = new FormData(); form.append("file", file);
      const qr = await api<{ value: string | null }>("/api/vision/qr", { method: "POST", body: form });
      if (qr.value) { onQR(qr.value); return; }
      const match = await api<Match>("/api/vision/match", { method: "POST", body: form });
      const known = match.candidates.map((c) => items.find((i) => i.id === c.product.id)).filter((i): i is Item => !!i).slice(0, 3);
      setPhotoId(match.imageId); setCandidates(known);
      if (!known.length) setError(mode === "receive" ? "No match from the photo. Search below, or add it as a new item." : "No match from the photo. Search for the part below.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const step = (delta: number, max?: number) => setQuantity((q) => Math.max(1, Math.min(max ?? 9999, q + delta)));

  const give = async () => {
    if (!part) return;
    setBusy(true); setError("");
    try {
      await api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ kind: "STOCK_OUT", productId: part.id, quantity, note: "Issued at the storeroom counter" }) }, commandKey.current);
      if (photoId) {
        // A confirmed photo becomes a reference and future training data for the photo model.
        try { await api("/api/vision/references", { method: "POST", body: JSON.stringify({ productId: part.id, imageId: photoId }) }); } catch { /* the movement is already recorded */ }
      }
      onChanged(); reset("Recorded: " + amount(quantity) + " × " + part.name + " taken out.");
    } catch (e) { setError((e as Error).message); commandKey.current = key(); }
    finally { setBusy(false); }
  };
  const onBarcode = async (value: string) => {
    setCamera(false); setBusy(true); setError(""); setDone("");
    const found = items.find((item) => item.barcode === value);
    if (found) {
      setPart(found); setCandidates([]); setPhotoId(""); setBusy(false); return;
    }
    try {
      const result = await api<BarcodeLookup>("/api/vision/barcodes/" + encodeURIComponent(value));
      setDone(result.found
        ? "Barcode found externally. Review the suggested details manually before registering."
        : "Barcode " + value + " is not in the catalogue. Enter the item details manually.");
      if (mode === "receive" && onBarcodeSuggestion) {
        onBarcodeSuggestion(value, result.suggestions);
      }
      setSearch(value);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const receive = async () => {
    if (!part) return;
    setBusy(true); setError("");
    try {
      await api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ kind: "RECEIPT", productId: part.id, quantity, note: "Received at the counter" }) }, commandKey.current);
      if (photoId) {
        try { await api("/api/vision/references", { method: "POST", body: JSON.stringify({ productId: part.id, imageId: photoId }) }); } catch { /* the receipt is already recorded */ }
      }
      onChanged(); reset("Recorded: " + amount(quantity) + " × " + part.name + " added to stock.");
    } catch (e) { setError((e as Error).message); commandKey.current = key(); }
    finally { setBusy(false); }
  };
  const matches = search.trim().length >= 2 ? items.filter((i) => (i.name + " " + i.sku + " " + i.brand).toLowerCase().includes(search.trim().toLowerCase())).slice(0, 6) : [];
  const choosePart = (item: Item) => { setPart(item); setCandidates([]); setPhotoId(""); setError(""); };
  return (
    <section className="counter-screen" aria-label="Storeroom counter">
      <div className="counter-modes" role="tablist">
        {(([["receive", "Receive"], ["give", "Give a part"]]) as [Mode, string][]).map(([m, label]) => (
          <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "chosen " + m : m} onClick={() => switchMode(m)}>{label}</button>
        ))}
      </div>
      {done && <p className="counter-done" role="status"><Check size={20} /> {done}</p>}
      {error && (
        <div className="stock-error stock-error-toast" role="alert">
          <strong>Could not complete that action</strong>
          <span>{error}</span>
          <button className="toast-close" aria-label="Dismiss error" onClick={() => setError("")}>×</button>
        </div>
      )}
      {(mode === "give" || mode === "receive") && (
        <>
          <div className="counter-step">
            <h2><span>1</span> {mode === "receive" ? "Which part came in?" : "Which part?"}</h2>
            {part ? (
              <div className="counter-chosen"><strong>{part.name}</strong><small>Part no. {part.part_number || "Not set"} · System no. {part.sku} · {amount(Number(part.quantity))} in stock{part.location ? " · " + part.location : ""}</small><button onClick={() => { setPart(null); setPhotoId(""); }}>Change</button></div>
            ) : (
              <>
                <button className="counter-big wide" disabled={busy} onClick={() => setCamera(true)}><CameraIcon size={30} /> {busy ? "Checking the photo…" : "Open camera"}</button>
                <p className="stock-help">Scan a Stocklane QR or original product barcode. You can also take a photo or search manually.</p>
                {candidates.length > 0 && (
                  <div className="counter-candidates">
                    <p>Is it one of these?</p>
                    {candidates.map((c) => <button key={c.id} onClick={() => choosePart(c)}><strong>{c.name}</strong><small>Part no. {c.part_number || "Not set"} · System no. {c.sku}{c.location ? " · " + c.location : ""}</small></button>)}
                  </div>
                )}
                {mode === "receive" && photoId && onNewItem && (
                  <button className="counter-new" onClick={() => onNewItem(photoId)}><Plus size={20} /> {candidates.length ? "None of these: add as a new item" : "Add as a new item (reads the label)"}</button>
                )}
                <label className="stock-field counter-search">Or search<input value={search} placeholder="Oil filter" onChange={(e) => setSearch(e.target.value)} /></label>
                {matches.map((m) => <button key={m.id} className="counter-result" onClick={() => choosePart(m)}>{m.name} <small>Part no. {m.part_number || "Not set"} · System no. {m.sku}</small></button>)}
              </>
            )}
          </div>
          {part && (
            <div className="counter-step">
              <h2><span>2</span> How many?</h2>
              <div className="counter-stepper">
                <button aria-label="One less" onClick={() => step(-1)}><Minus /></button>
                <input aria-label="Quantity" type="number" min={part.unit === "LITRE" ? 0.001 : 1} step={part.unit === "LITRE" ? 0.001 : 1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
                <button aria-label="One more" onClick={() => step(1)}><Plus /></button>
                <span>{part.unit === "LITRE" ? "litres" : "pieces"}</span>
              </div>
            </div>
          )}
          {part && mode === "give" && <p className="stock-help counter-confirm-help">No recipient details are required. Confirm the quantity leaving the storeroom.</p>}
          {part && mode === "receive" && (
            <button className="button primary counter-confirm" disabled={busy || !(quantity > 0)} onClick={() => void receive()}>
              {busy ? "Saving…" : "Add " + amount(quantity) + " × " + part.name + " to stock"}
            </button>
          )}
          {part && mode === "give" && (
            <button className="button primary counter-confirm" disabled={busy || !(quantity > 0)} onClick={() => void give()}>
              {busy ? "Saving…" : "Record " + amount(quantity) + " × " + part.name + " leaving stock"}
            </button>
          )}
        </>
      )}

      {camera && (
        <React.Suspense fallback={null}>
          <Camera onQR={onQR} onBarcode={(value) => void onBarcode(value)} onPhoto={(f) => void identifyPhoto(f)} onClose={() => setCamera(false)} />
        </React.Suspense>
      )}
      {part && <button className="counter-restart" onClick={() => reset()}><ArrowLeft size={16} /> Scan another item</button>}
    </section>
  );
}
