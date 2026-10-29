import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Camera as CameraIcon, Check, Minus, PackageX, Plus, Trash2, UserRound } from "lucide-react";
import { api, type Match, type Product } from "./api";

const Camera = React.lazy(() => import("./Camera").then((m) => ({ default: m.Camera })));

type Item = Product & { location?: string; archived?: boolean };
type Person = { id: string; name: string };
type Handover = { id: string; product_id: string; sku: string; name: string; unit: string; quantity: number; outstanding: number; created_at: string };
export type Mode = "receive" | "give" | "back";
const PART_QR = /^stocklane:v1:([0-9a-f-]{36})$/;
const key = () => crypto.randomUUID();
const amount = (n: number) => new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(n);

export function partFromCode(value: string, items: Item[]) {
  const id = PART_QR.exec(value.trim())?.[1];
  return items.find((p) => p.id === id) || null;
}

export function Counter({ items, owner, initialMode = "give", picked = null, onNewItem, onChanged }: { items: Item[]; owner: boolean; initialMode?: Mode; picked?: Item | null; onNewItem?: (imageId: string) => void; onChanged: () => void }) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [people, setPeople] = useState<Person[]>([]);
  const [part, setPart] = useState<Item | null>(null);
  const [candidates, setCandidates] = useState<Item[]>([]);
  const [photoId, setPhotoId] = useState("");
  const [person, setPerson] = useState<Person | null>(null);
  const [handovers, setHandovers] = useState<Handover[] | null>(null);
  const [handover, setHandover] = useState<Handover | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [search, setSearch] = useState("");
  const [camera, setCamera] = useState(false);
  const [unused, setUnused] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [done, setDone] = useState("");
  const [newName, setNewName] = useState("");
  const commandKey = useRef(key());

  const loadPeople = () => api<Person[]>("/api/inventory/people").then(setPeople).catch((e) => setError((e as Error).message));
  useEffect(() => { void loadPeople(); }, []);
  useEffect(() => { setMode(initialMode); }, [initialMode]);
  // A new item registered from this screen comes back selected, ready for its quantity.
  useEffect(() => { if (picked) { setPart(picked); setCandidates([]); setPhotoId(""); setQuantity(1); setError(""); } }, [picked]);

  const reset = (message = "") => {
    setPart(null); setCandidates([]); setPhotoId(""); setPerson(null); setUnused(false); setHandovers(null); setHandover(null);
    setQuantity(1); setSearch(""); setError(""); setDone(message); commandKey.current = key();
  };
  const switchMode = (next: Mode) => { setMode(next); reset(); };

  const choosePerson = async (p: Person) => {
    setPerson(p); setUnused(false); setError(""); setDone("");
    if (mode === "back") {
      try { setHandovers(await api<Handover[]>("/api/inventory/people/" + p.id + "/handovers")); }
      catch (e) { setError((e as Error).message); }
    }
  };
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
    if (!part || (!person && !unused)) return;
    setBusy(true); setError("");
    try {
      await api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ kind: "STOCK_OUT", productId: part.id, quantity, ...(person ? { receiverId: person.id } : {}), note: person ? "Given to " + person.name + " at the counter" : "Used up or damaged" }) }, commandKey.current);
      if (photoId) {
        // A confirmed photo becomes a reference and future training data for the photo model.
        try { await api("/api/vision/references", { method: "POST", body: JSON.stringify({ productId: part.id, imageId: photoId }) }); } catch { /* the movement is already recorded */ }
      }
      onChanged(); reset("Recorded: " + amount(quantity) + " × " + part.name + (person ? " given to " + person.name : " taken out as used up or damaged") + ".");
    } catch (e) { setError((e as Error).message); commandKey.current = key(); }
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
  const takeBack = async () => {
    if (!handover || !person) return;
    setBusy(true); setError("");
    try {
      await api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ kind: "RETURN", productId: handover.product_id, quantity, issueId: handover.id, note: "Taken back from " + person.name + " at the counter" }) }, commandKey.current);
      onChanged(); reset("Recorded: " + amount(quantity) + " × " + handover.name + " taken back from " + person.name + ".");
    } catch (e) { setError((e as Error).message); commandKey.current = key(); }
    finally { setBusy(false); }
  };
  const addPerson = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try { await api("/api/inventory/people", { method: "POST", body: JSON.stringify({ name: newName }) }, key()); setNewName(""); await loadPeople(); }
    catch (x) { setError((x as Error).message); }
  };
  const removePerson = async (p: Person) => {
    try { await api("/api/inventory/people/" + p.id, { method: "DELETE" }); await loadPeople(); }
    catch (x) { setError((x as Error).message); }
  };

  const matches = search.trim().length >= 2 ? items.filter((i) => (i.name + " " + i.sku + " " + i.brand).toLowerCase().includes(search.trim().toLowerCase())).slice(0, 6) : [];
  const peopleButtons = (
    <div className="counter-people">
      {people.map((p) => (
        <button key={p.id} className={"counter-person" + (person?.id === p.id ? " chosen" : "")} onClick={() => void choosePerson(p)}>
          <UserRound size={22} /> {p.name}
        </button>
      ))}
      {mode === "give" && (
        <button className={"counter-person other" + (unused ? " chosen" : "")} onClick={() => { setUnused(true); setPerson(null); }}>
          <PackageX size={22} /> Used up / damaged
        </button>
      )}
    </div>
  );

  return (
    <section className="counter-screen" aria-label="Storeroom counter">
      <div className="counter-modes" role="tablist">
        {(([["receive", "Receive"], ["give", "Give a part"], ["back", "Take back"]]) as [Mode, string][]).map(([m, label]) => (
          <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "chosen " + m : m} onClick={() => switchMode(m)}>{label}</button>
        ))}
      </div>
      {done && <p className="counter-done" role="status"><Check size={20} /> {done}</p>}
      {error && <p className="stock-error" role="alert">{error}</p>}
      {mode !== "receive" && !people.length && (
        <p className="stock-help">{owner ? "Add the names of the people who collect parts (below) to start." : "No names on the list yet. Ask the owner to add them."}</p>
      )}

      {(mode === "give" || mode === "receive") && (
        <>
          <div className="counter-step">
            <h2><span>1</span> {mode === "receive" ? "Which part came in?" : "Which part?"}</h2>
            {part ? (
              <div className="counter-chosen"><strong>{part.name}</strong><small>{part.sku} · {amount(Number(part.quantity))} in stock{part.location ? " · " + part.location : ""}</small><button onClick={() => { setPart(null); setPhotoId(""); }}>Change</button></div>
            ) : (
              <>
                <button className="counter-big wide" disabled={busy} onClick={() => setCamera(true)}><CameraIcon size={30} /> {busy ? "Checking the photo…" : "Open camera"}</button>
                <p className="stock-help">Point at the part. A QR label is read by itself; otherwise take a photo.</p>
                {candidates.length > 0 && (
                  <div className="counter-candidates">
                    <p>Is it one of these?</p>
                    {candidates.map((c) => <button key={c.id} onClick={() => setPart(c)}><strong>{c.name}</strong><small>{c.sku}{c.location ? " · " + c.location : ""}</small></button>)}
                  </div>
                )}
                {mode === "receive" && photoId && onNewItem && (
                  <button className="counter-new" onClick={() => onNewItem(photoId)}><Plus size={20} /> {candidates.length ? "None of these: add as a new item" : "Add as a new item (reads the label)"}</button>
                )}
                <label className="stock-field counter-search">Or search<input value={search} placeholder="Oil filter" onChange={(e) => setSearch(e.target.value)} /></label>
                {matches.map((m) => <button key={m.id} className="counter-result" onClick={() => { setPart(m); setPhotoId(""); }}>{m.name} <small>{m.sku}</small></button>)}
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
          {part && mode === "give" && (
            <div className="counter-step">
              <h2><span>3</span> Who is taking it?</h2>
              {peopleButtons}
            </div>
          )}
          {part && mode === "receive" && (
            <button className="button primary counter-confirm" disabled={busy || !(quantity > 0)} onClick={() => void receive()}>
              {busy ? "Saving…" : "Add " + amount(quantity) + " × " + part.name + " to stock"}
            </button>
          )}
          {part && (person || unused) && mode === "give" && (
            <button className="button primary counter-confirm" disabled={busy || !(quantity > 0)} onClick={() => void give()}>
              {busy ? "Saving…" : "Give " + amount(quantity) + " × " + part.name + (person ? " to " + person.name : " (used up / damaged)")}
            </button>
          )}
        </>
      )}

      {mode === "back" && (
        <>
          <div className="counter-step">
            <h2><span>1</span> Who is returning it?</h2>
            {peopleButtons}
          </div>
          {person && handovers && (
            <div className="counter-step">
              <h2><span>2</span> Which part?</h2>
              {handovers.length === 0 && <p className="stock-help">{person.name} has no parts out from the last 30 days.</p>}
              <div className="counter-candidates">
                {handovers.map((h) => (
                  <button key={h.id} className={handover?.id === h.id ? "chosen" : ""} onClick={() => { setHandover(h); setQuantity(Math.min(1, h.outstanding) || 1); }}>
                    <strong>{h.name}</strong><small>{amount(h.outstanding)} still out · given {new Date(h.created_at).toLocaleDateString("en-GB", { timeZone: "Asia/Colombo" })}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
          {handover && (
            <>
              <div className="counter-step">
                <h2><span>3</span> How many?</h2>
                <div className="counter-stepper">
                  <button aria-label="One less" onClick={() => step(-1, handover.outstanding)}><Minus /></button>
                  <input aria-label="Quantity" type="number" value={quantity} max={handover.outstanding} onChange={(e) => setQuantity(Number(e.target.value))} />
                  <button aria-label="One more" onClick={() => step(1, handover.outstanding)}><Plus /></button>
                  <span>of {amount(handover.outstanding)}</span>
                </div>
              </div>
              <button className="button primary counter-confirm" disabled={busy || !(quantity > 0) || quantity > handover.outstanding} onClick={() => void takeBack()}>
                {busy ? "Saving…" : "Take back " + amount(quantity) + " × " + handover.name}
              </button>
            </>
          )}
        </>
      )}

      {owner && (
        <details className="counter-admin" open={!people.length}>
          <summary>People who collect parts ({people.length})</summary>
          <ul>
            {people.map((p) => (
              <li key={p.id}>
                <span>{p.name}</span>
                <button className="button secondary" aria-label={"Remove " + p.name} onClick={() => void removePerson(p)}><Trash2 size={16} /></button>
              </li>
            ))}
          </ul>
          <form className="analysis-filters" onSubmit={(e) => void addPerson(e)}>
            <label className="stock-field">Add a name<input value={newName} maxLength={80} placeholder="Nimal" onChange={(e) => setNewName(e.target.value)} /></label>
            <button className="button primary">Add</button>
          </form>
        </details>
      )}

      {camera && (
        <React.Suspense fallback={null}>
          <Camera onQR={onQR} onPhoto={(f) => void identifyPhoto(f)} onClose={() => setCamera(false)} />
        </React.Suspense>
      )}
      {mode !== "back" && part && <button className="counter-restart" onClick={() => reset()}><ArrowLeft size={16} /> Start again</button>}
    </section>
  );
}
