import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import QRCode from "qrcode";
import {
  Camera,
  Package,
  ArrowDownLeft,
  ArrowUpRight,
  Activity,
  Plus,
  Printer,
  Search,
  RefreshCw,
  LogOut,
  Check,
  X,
  ScanLine,
  Home,
  ArrowRight,
  ArrowLeft,
  ClipboardCheck,
  ListChecks,
} from "lucide-react";
import {
  api,
  ApiError,
  auth,
  config,
  headers,
  signOut,
  type Product,
  type Match,
  type Draft,
  type Movement,
  type CaptureEntry,
} from "./api";
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/manrope";
import "./stock.css";
import { Scanner } from "./Scanner";
import {
  emptyTask,
  complete,
  validQuantity,
  plannedOut,
  verifyExisting,
  type Direction,
  type StockTask,
  type TaskLine,
} from "./task";

type Item = Product & {
  part_number?: string;
  location?: string;
  archived?: boolean;
};
type Session = { name: string; roles: string[] };
type View =
  | "home"
  | "receive"
  | "issue"
  | "stock"
  | "find"
  | "count"
  | "activity"
  | "review";
const uid = () => crypto.randomUUID();
const number = (n: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(Number(n));
const when = (s: string) =>
  new Date(s).toLocaleString("en-GB", { timeZone: "Asia/Colombo" });
function useCommand() {
  const pending = useRef({ body: "", key: "" });
  return async <T,>(path: string, body: unknown, method = "POST") => {
    const fingerprint = path + method + JSON.stringify(body);
    if (pending.current.body !== fingerprint)
      pending.current = { body: fingerprint, key: uid() };
    const value = await api<T>(
      path,
      { method, body: JSON.stringify(body) },
      pending.current.key,
    );
    pending.current = { body: "", key: "" };
    return value;
  };
}
async function printLabel(item: Item) {
  const popup = window.open("", "_blank");
  if (!popup) throw new Error("Allow a new window to print the label.");
  try {
    const data = await QRCode.toDataURL("stocklane:v1:" + item.id, {
      width: 260,
      margin: 2,
    });
    const doc = popup.document;
    doc.title = "Stock label — " + item.sku;
    const style = doc.createElement("style");
    style.textContent =
      "body{font:14px sans-serif;text-align:center;margin:12mm}img{width:45mm;height:45mm}h1{font-size:18px}p{margin:5px}button{margin:20px;padding:12px}@media print{button{display:none}}";
    doc.head.append(style);
    const img = doc.createElement("img");
    img.src = data;
    img.alt = "Product QR";
    doc.body.append(img);
    for (const text of [
      item.name,
      item.brand,
      item.part_number || item.sku,
      item.location || "",
    ]) {
      const p = doc.createElement("p");
      p.textContent = text;
      doc.body.append(p);
    }
    const button = doc.createElement("button");
    button.textContent = "Print / Save as PDF";
    button.onclick = () => popup.print();
    doc.body.append(button);
  } catch (error) {
    popup.close();
    throw error;
  }
}
function Photo({ id }: { id: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true;
    let object = "";
    apiPhoto(id)
      .then((blob) => {
        object = URL.createObjectURL(blob);
        if (active) setUrl(object);
        else URL.revokeObjectURL(object);
      })
      .catch(() => {});
    return () => {
      active = false;
      if (object) URL.revokeObjectURL(object);
    };
  }, [id]);
  return url ? (
    <img className="item-photo" src={url} alt="Approved item reference" />
  ) : (
    <span className="photo-placeholder">
      <Package />
    </span>
  );
}
async function apiPhoto(id: string) {
  const r = await fetch(
    (config.apiBase || "") + "/api/vision/images/" + encodeURIComponent(id),
    { headers: await headers() },
  );
  if (!r.ok) throw new Error("Photo unavailable");
  return r.blob();
}
function App() {
  const [view, setView] = useState<View>("home");
  const [items, setItems] = useState<Item[]>([]),
    [moves, setMoves] = useState<Movement[]>([]),
    [captures, setCaptures] = useState<CaptureEntry[]>([]);
  const [session, setSession] = useState<Session | null>(null),
    [status, setStatus] = useState<any>(null),
    [loading, setLoading] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [tasks, setTasks] = useState<Record<Direction, StockTask>>({
    IN: emptyTask(),
    OUT: emptyTask(),
  });
  const taskRef = useRef(tasks),
    storageKey = useRef(""),
    submitting = useRef(false);
  const [selected, setSelected] = useState(""),
    [quantity, setQuantity] = useState(1),
    [qr, setQr] = useState(""),
    [search, setSearch] = useState("");
  const [scanner, setScanner] = useState(false),
    [match, setMatch] = useState<Match | null>(null),
    [draft, setDraft] = useState<Draft | null>(null);
  const [imageId, setImageId] = useState(""),
    [preview, setPreview] = useState(""),
    [capture, setCapture] = useState<CaptureEntry | null>(null),
    [saveReference, setSaveReference] = useState(false);
  const [newItem, setNewItem] = useState(false),
    [edit, setEdit] = useState<Item | null>(null),
    [labelItem, setLabelItem] = useState<Item | null>(null);
  const [archived, setArchived] = useState<Item[]>([]),
    [showArchived, setShowArchived] = useState(false),
    [query, setQuery] = useState("");
  const [countId, setCountId] = useState(""),
    [physical, setPhysical] = useState("");
  const file = useRef<HTMLInputElement>(null),
    sequence = useRef(0),
    mutation = useCommand();
  const direction: Direction = view === "issue" ? "OUT" : "IN";
  const inTask = view === "receive" || view === "issue";
  const task = tasks[direction],
    active = items.find((item) => item.id === selected),
    owner = !!session?.roles.includes("ROLE_OWNER");
  const pending = captures.filter((c) => c.status === "PENDING");
  const tell = (message: string) => setNotice(message);
  const persist = (next: Record<Direction, StockTask>) => {
    // Persist before submitting: a reload retries with the same command identity.
    if (storageKey.current)
      sessionStorage.setItem(storageKey.current, JSON.stringify(next));
    taskRef.current = next;
    setTasks(next);
  };
  const updateLine = (dir: Direction, id: string, patch: Partial<TaskLine>) => {
    const current = taskRef.current;
    persist({
      ...current,
      [dir]: {
        ...current[dir],
        lines: current[dir].lines.map((line) =>
          line.id === id ? { ...line, ...patch } : line,
        ),
      },
    });
  };
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, m, c, s, v] = await Promise.all([
        api<Item[]>("/api/inventory/products"),
        api<Movement[]>("/api/inventory/movements"),
        api<CaptureEntry[]>("/api/vision/captures")
          .then((data) => {
            setCameraError("");
            return data;
          })
          .catch(() => {
            setCameraError(
              "Camera inbox is temporarily unavailable. Receiving and stock-out still work.",
            );
            return [];
          }),
        api<Session>("/api/inventory/session"),
        api("/api/vision/status").catch(() => ({
          modelReady: false,
          bedrockConfigured: false,
        })),
      ]);
      setItems(p);
      setMoves(m);
      setCaptures(c);
      setSession(s);
      setStatus(v);
      const key = "stocklane.tasks.v2." + s.name;
      if (storageKey.current !== key) {
        storageKey.current = key;
        let restored = { IN: emptyTask(), OUT: emptyTask() };
        try {
          const saved = JSON.parse(sessionStorage.getItem(key) || "null");
          if (
            saved &&
            Array.isArray(saved.IN?.lines) &&
            Array.isArray(saved.OUT?.lines)
          )
            restored = saved;
        } catch {
          /* Start fresh if no valid local draft. */
        }
        taskRef.current = restored;
        setTasks(restored);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (location.pathname === "/auth/callback" && auth) {
      void auth
        .signinRedirectCallback()
        .then(() => location.replace("/"))
        .catch((e) => setError(e.message));
    } else void refresh();
  }, [refresh]);
  useEffect(
    () => () => {
      if (preview.startsWith("blob:")) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  const resetIdentification = () => {
    sequence.current++;
    setSelected("");
    setQuantity(1);
    setQr("");
    setSearch("");
    setMatch(null);
    setImageId("");
    setPreview("");
    setCapture(null);
    setDraft(null);
    setSaveReference(false);
  };
  const navigate = (next: View) => {
    if (submitting.current) return;
    setScanner(false);
    resetIdentification();
    setView(next);
    setError("");
    setNotice("");
  };
  const start = (dir: Direction) => {
    navigate(dir === "IN" ? "receive" : "issue");
    setScanner(true);
  };
  const chooseQR = useCallback(
    (value: string) => {
      setScanner(false);
      const text = value.trim().toLowerCase();
      if (
        !/^stocklane:v1:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          text,
        )
      ) {
        setError(
          "This is not a Stocklane item QR. Use a product photo or search by part number.",
        );
        return;
      }
      const id = text.slice("stocklane:v1:".length),
        item = items.find((p) => p.id === id);
      if (!item) {
        setError(
          "This label is not in the active catalogue. Refresh or ask the owner to check archived items.",
        );
        return;
      }
      if (view === "count") {
        setCountId(id);
        setPhysical("");
      } else {
        setSelected(id);
        setQuantity(1);
        setMatch(null);
        setImageId("");
        setCapture(null);
        setSaveReference(false);
      }
      setError("");
      setNotice("Item found. Check the part number.");
    },
    [items, view],
  );
  const analyse = async (photo: File) => {
    const run = ++sequence.current;
    setBusy(true);
    setError("");
    setSelected("");
    setMatch(null);
    setDraft(null);
    setImageId("");
    setCapture(null);
    setSaveReference(false);
    setPreview(URL.createObjectURL(photo));
    try {
      const form = new FormData();
      form.append("file", photo);
      const result = await api<{ value: string | null }>("/api/vision/qr", {
        method: "POST",
        body: form,
      });
      if (run !== sequence.current) return;
      if (result.value) {
        chooseQR(result.value);
        return;
      }
      const found = await api<Match>("/api/vision/match", {
        method: "POST",
        body: form,
      });
      if (run !== sequence.current) return;
      setMatch({
        ...found,
        candidates: found.candidates.filter((c) =>
          items.some((p) => p.id === c.product.id),
        ),
      });
      setImageId(found.imageId);
    } catch (e) {
      if (run === sequence.current) setError((e as Error).message);
    } finally {
      if (run === sequence.current) setBusy(false);
    }
  };
  const readLabel = async () => {
    setBusy(true);
    setError("");
    try {
      setDraft(
        await api<Draft>("/api/vision/drafts", {
          method: "POST",
          body: JSON.stringify({ imageId }),
        }),
      );
      setNewItem(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const addLine = () => {
    if (!active || !validQuantity(quantity, active.unit)) {
      setError(
        "Enter a positive quantity. Pieces need whole numbers; litres allow up to three decimals.",
      );
      return;
    }
    const current = taskRef.current;
    if (
      capture &&
      Object.values(current).some((t) =>
        t.lines.some((line) => line.captureId === capture.id),
      )
    ) {
      setError(
        "This camera capture is already in a draft. Review the existing line.",
      );
      return;
    }
    if (
      direction === "OUT" &&
      quantity + plannedOut(current.OUT.lines, active.id) >
        Number(active.quantity)
    ) {
      setError(
        "The draft requests more than the available stock. Reduce its quantity.",
      );
      return;
    }
    const line: TaskLine = {
      id: uid(),
      key: uid(),
      productId: active.id,
      name: active.name,
      part: active.part_number || active.sku,
      unit: active.unit,
      quantity,
      captureId: capture?.id,
      imageId: imageId || undefined,
      reference: saveReference && !!imageId,
      attempted: false,
    };
    try {
      persist({
        ...current,
        [direction]: {
          ...current[direction],
          lines: [...current[direction].lines, line],
        },
      });
      tell(active.name + " added to your draft. Stock has not changed.");
      resetIdentification();
    } catch {
      setError(
        "This browser cannot save the draft. Enable session storage before continuing.",
      );
    }
  };
  const commit = async () => {
    if (submitting.current || !task.lines.length) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const dir = direction;
    try {
      for (const original of taskRef.current[dir].lines) {
        let line = { ...original };
        if (complete(line)) continue;
        updateLine(dir, line.id, {
          attempted: true,
          error: undefined,
          rejected: false,
        });
        line.attempted = true;
        try {
          if (!line.movementId) {
            let movement: any = line.captureId
              ? (
                  await api<any>(
                    "/api/inventory/captures/" + line.captureId + "/movement",
                  )
                ).movement
              : null;
            if (movement) verifyExisting(movement, line, dir);
            else
              movement = await api<any>(
                "/api/inventory/movements",
                {
                  method: "POST",
                  body: JSON.stringify({
                    kind: dir === "IN" ? "RECEIPT" : "STOCK_OUT",
                    productId: line.productId,
                    quantity: line.quantity,
                    jobId: null,
                    issueId: null,
                    note: "Stock " + dir + " · task " + taskRef.current[dir].id,
                    sourceCaptureId: line.captureId || null,
                  }),
                },
                line.key,
              );
            line.movementId = movement.id;
            updateLine(dir, line.id, { movementId: movement.id });
          }
          if (line.captureId && !line.reconciled) {
            await api("/api/vision/captures/" + line.captureId, {
              method: "PATCH",
              body: JSON.stringify({ movementId: line.movementId }),
            });
            updateLine(dir, line.id, { reconciled: true });
          }
          if (line.reference && line.imageId && !line.referenceSaved) {
            await api("/api/vision/references", {
              method: "POST",
              body: JSON.stringify({
                productId: line.productId,
                imageId: line.imageId,
              }),
            });
            updateLine(dir, line.id, { referenceSaved: true });
          }
        } catch (e) {
          updateLine(dir, line.id, {
            error: (e as Error).message,
            rejected:
              !line.movementId &&
              e instanceof ApiError &&
              [400, 404, 409, 422].includes(e.status),
          });
          throw e;
        }
      }
      await refresh();
      tell(
        dir === "IN"
          ? "Receipt confirmed. Stock has been updated."
          : "Stock-out confirmed. Stock has been updated.",
      );
    } catch (e) {
      setError(
        "Some lines may already be recorded. Review the statuses below, then retry unfinished lines. " +
          (e as Error).message,
      );
      await refresh();
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  const discard = () => {
    if (task.lines.some((l) => l.attempted && !complete(l))) {
      setError(
        "An attempted line is unfinished. Retry it before starting a new task.",
      );
      return;
    }
    if (
      task.lines.some((l) => !complete(l)) &&
      !confirm(
        "Discard the unconfirmed draft? Stock has not changed for those lines.",
      )
    )
      return;
    persist({ ...taskRef.current, [direction]: emptyTask() });
    resetIdentification();
    setNotice("Ready for a new task.");
  };
  const reference = async () => {
    if (!active || !imageId) return;
    setBusy(true);
    try {
      await api("/api/vision/references", {
        method: "POST",
        body: JSON.stringify({ productId: active.id, imageId }),
      });
      tell("Reference saved. Stock is unchanged.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const archive = async (p: Item, value: boolean) => {
    if (
      !confirm(
        value
          ? "Archive " + p.name + "? Stock must be zero; history remains."
          : "Restore " + p.name + "?",
      )
    )
      return;
    try {
      await mutation("/api/inventory/products/" + p.id + "/archive", {
        archived: value,
      });
      await refresh();
      if (showArchived)
        setArchived(await api<Item[]>("/api/inventory/products/archived"));
      tell(value ? "Item archived." : "Item restored.");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const review = (c: CaptureEntry) => {
    navigate(c.direction === "IN" ? "receive" : "issue");
    setCapture(c);
    setSelected(c.result.identifiedProductId || "");
    setMatch(c.result);
    setImageId(c.image_id);
  };
  const filtered = (source: Item[], text: string) =>
    source.filter((p) =>
      [p.name, p.brand, p.part_number, p.location, p.category, p.sku]
        .join(" ")
        .toLowerCase()
        .includes(text.toLowerCase()),
    );
  const allComplete = task.lines.length > 0 && task.lines.every(complete),
    locked = task.lines.some((l) => l.attempted);
  const countItem = items.find((p) => p.id === countId);
  const showResults = (source: Item[]) =>
    source.slice(0, 30).map((p) => (
      <button
        className="lookup-row"
        key={p.id}
        onClick={() => {
          setSelected(p.id);
          setQuantity(1);
          setError("");
        }}
      >
        <ItemPhoto item={p} />
        <span>
          <strong>{p.name}</strong>
          <small>
            {p.brand} · {p.part_number || p.sku}
          </small>
          <small>{p.location || "Shelf not set"}</small>
        </span>
        <b>
          {number(p.quantity)}
          <small>{p.unit === "LITRE" ? "L" : "units"}</small>
        </b>
      </button>
    ));
  return (
    <div className="stock-shell">
      <aside className="stock-sidebar">
        <a
          className="stock-brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("home");
          }}
        >
          stocklane<span>.</span>
        </a>
        <p>WORKSHOP STOCK</p>
        {(
          [
            ["home", "Workspace", Home],
            ["stock", owner ? "Manage catalogue" : "Current stock", Package],
            ["review", "Needs review", Camera],
            ["activity", "Activity", Activity],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            disabled={busy}
            className={view === key ? "chosen" : ""}
            onClick={() => navigate(key)}
          >
            <Icon size={19} />
            {label}
            {key === "review" && pending.length > 0 && (
              <b className="counter">{pending.length}</b>
            )}
          </button>
        ))}
        <div className="stock-sidebar-foot">
          <span className="user-avatar">
            {session?.name.slice(0, 1).toUpperCase() || "S"}
          </span>
          <strong>{owner ? "Owner workspace" : "Stock team"}</strong>
          <small>Montero Workshop</small>
        </div>
      </aside>
      <main className="stock-main">
        <header className="stock-header">
          <span>
            <span className="online-dot" /> Workshop inventory
          </span>
          <div>
            <button
              className="icon-button"
              aria-label="Refresh stock"
              disabled={loading || busy}
              onClick={() => void refresh()}
            >
              <RefreshCw size={19} />
            </button>
            {auth && (
              <button
                className="button secondary small"
                disabled={busy}
                onClick={() => void signOut()}
              >
                <LogOut size={16} /> Sign out
              </button>
            )}
          </div>
        </header>
        {notice && (
          <div className="stock-notice" role="status">
            <Check size={18} />
            {notice}
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {error && (
          <div className="stock-error" role="alert">
            {error}
            {auth && !session && (
              <button
                className="button secondary"
                onClick={() => void auth?.signinRedirect()}
              >
                Sign in
              </button>
            )}
          </div>
        )}
        {view === "home" && (
          <>
            <div className="workspace-intro">
              <p className="eyebrow">YOUR STOCK. UNDER CONTROL.</p>
              <h1>What are we doing today?</h1>
              <p>Choose a task. Scan an item. Keep stock accurate.</p>
            </div>
            <div className="task-tiles">
              <button
                className="task-tile receive-tile"
                disabled={!session || busy}
                onClick={() => start("IN")}
              >
                <span className="tile-icon">
                  <ArrowDownLeft />
                </span>
                <span className="tile-tag">ITEMS COMING IN</span>
                <h2>Receive stock</h2>
                <p>Add a delivery to your shelves.</p>
                <span className="tile-bottom">
                  Start receiving <ArrowRight size={20} />
                </span>
              </button>
              <button
                className="task-tile issue-tile"
                disabled={!session || busy}
                onClick={() => start("OUT")}
              >
                <span className="tile-icon">
                  <ArrowUpRight />
                </span>
                <span className="tile-tag">ITEMS GOING OUT</span>
                <h2>Take stock out</h2>
                <p>Record parts leaving the storeroom.</p>
                <span className="tile-bottom">
                  Start scanning <ArrowRight size={20} />
                </span>
              </button>
              <button
                className="task-tile"
                disabled={!session || busy}
                onClick={() => navigate("find")}
              >
                <span className="tile-icon">
                  <Search />
                </span>
                <h2>Find an item</h2>
                <p>Look up a part, photo or shelf.</p>
                <span className="tile-bottom">
                  Search stock <ArrowRight size={20} />
                </span>
              </button>
              <button
                className="task-tile"
                disabled={!session || busy}
                onClick={() => navigate("count")}
              >
                <span className="tile-icon">
                  <ClipboardCheck />
                </span>
                <h2>Count stock</h2>
                <p>Compare a physical count with your records.</p>
                <span className="tile-bottom">
                  Check a quantity <ArrowRight size={20} />
                </span>
              </button>
            </div>
            {(tasks.IN.lines.length > 0 || tasks.OUT.lines.length > 0) && (
              <section className="resume-section">
                <h3>Continue where you left off</h3>
                {(["IN", "OUT"] as const)
                  .filter((d) => tasks[d].lines.length > 0)
                  .map((d) => (
                    <button
                      className="resume-row"
                      key={d}
                      onClick={() => navigate(d === "IN" ? "receive" : "issue")}
                    >
                      <span>
                        {d === "IN" ? "Receipt" : "Stock-out"} ·{" "}
                        {tasks[d].lines.length} lines
                      </span>
                      <span>
                        {tasks[d].lines.every(complete)
                          ? "Completed"
                          : "Continue draft"}{" "}
                        <ArrowRight size={18} />
                      </span>
                    </button>
                  ))}
              </section>
            )}
            <div className="workspace-overview">
              <span>
                <b>{items.length}</b> catalogue items
              </span>
              <span>
                <b>
                  {
                    items.filter(
                      (p) => Number(p.quantity) <= Number(p.reorder_level),
                    ).length
                  }
                </b>{" "}
                low-stock items
              </span>
              <button onClick={() => navigate("review")}>
                <b>{cameraError ? "—" : pending.length}</b>{" "}
                {cameraError
                  ? "camera inbox unavailable"
                  : "camera captures to review"}{" "}
                <ArrowRight size={16} />
              </button>
            </div>
          </>
        )}
        {(inTask || view === "find") && (
          <>
            <button
              className="back-link"
              disabled={busy}
              onClick={() => navigate("home")}
            >
              <ArrowLeft size={17} /> Workspace
            </button>
            <div className="stock-title">
              <div>
                <p className="eyebrow">
                  {inTask
                    ? "SCAN → REVIEW → CONFIRM"
                    : "LOOK UP YOUR CATALOGUE"}
                </p>
                <h1>
                  {view === "find"
                    ? "Find an item"
                    : direction === "IN"
                      ? "Receive stock"
                      : "Take stock out"}
                </h1>
                <p>
                  {view === "find"
                    ? "Search by part number, scan a QR or identify a photo."
                    : "Build your list first. Stock changes only when you confirm."}
                </p>
              </div>
              {inTask && (
                <span
                  className={
                    "direction-badge " + (direction === "IN" ? "in" : "out")
                  }
                >
                  {direction === "IN" ? <ArrowDownLeft /> : <ArrowUpRight />}
                  {direction === "IN" ? "RECEIVING STOCK" : "TAKING STOCK OUT"}
                </span>
              )}
            </div>
            <div className={"workflow-grid " + (!inTask ? "lookup-only" : "")}>
              <section className="stock-panel scan-panel">
                <div className="section-heading">
                  <h2>{active ? "Check this item" : "Identify an item"}</h2>
                  {active && (
                    <button
                      className="stock-link"
                      disabled={busy}
                      onClick={resetIdentification}
                    >
                      Change item
                    </button>
                  )}
                </div>
                {!active && (
                  <>
                    <button
                      className="scan-launch"
                      disabled={busy || allComplete || locked}
                      onClick={() => setScanner(true)}
                    >
                      <ScanLine size={32} />
                      <span>
                        <strong>Scan QR label</strong>
                        <small>Use your phone camera</small>
                      </span>
                      <ArrowRight />
                    </button>
                    <div className="scan-alternatives">
                      <button
                        className="button secondary"
                        disabled={busy || allComplete || locked}
                        onClick={() => file.current?.click()}
                      >
                        <Camera size={18} /> Identify from photo
                      </button>
                      <details>
                        <summary>QR scanner / paste code</summary>
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            chooseQR(qr);
                          }}
                        >
                          <input
                            aria-label="QR value"
                            value={qr}
                            onChange={(e) => setQr(e.target.value)}
                            placeholder="Scan or paste product QR"
                          />
                          <button
                            className="button secondary"
                            disabled={!qr || busy}
                          >
                            Find
                          </button>
                        </form>
                      </details>
                    </div>
                    <div className="search-box">
                      <Search size={19} />
                      <input
                        aria-label="Search catalogue"
                        disabled={busy || allComplete || locked}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search name or manufacturer part number"
                      />
                    </div>
                    {busy && (
                      <p role="status" className="stock-help">
                        Checking the item…
                      </p>
                    )}
                    {preview && (
                      <img
                        className="identification-photo"
                        src={preview}
                        alt="Photo being identified"
                      />
                    )}
                    {match && !busy && (
                      <div className="match-results">
                        <h3>
                          {match.candidates.length
                            ? "Could it be one of these?"
                            : "No reliable photo match"}
                        </h3>
                        <p className="stock-help">
                          Check the manufacturer part number and specification.
                        </p>
                        {match.candidates.map((c) => {
                          const p = items.find((i) => i.id === c.product.id)!;
                          return (
                            <button
                              className="lookup-row"
                              key={p.id}
                              onClick={() => setSelected(p.id)}
                            >
                              <Photo id={c.imageId} />
                              <span>
                                <strong>{p.name}</strong>
                                <small>
                                  {p.brand} · {p.part_number || p.sku}
                                </small>
                              </span>
                              <ArrowRight size={18} />
                            </button>
                          );
                        })}
                      </div>
                    )}
                    {search && (
                      <div className="lookup-results">
                        {showResults(filtered(items, search))}
                        {filtered(items, search).length === 0 && (
                          <p className="stock-help">
                            No item found. Check the part number or register it
                            below.
                          </p>
                        )}
                        {filtered(items, search).length > 30 && (
                          <p className="stock-help">
                            Type more to narrow these results.
                          </p>
                        )}
                      </div>
                    )}
                    {!search && !match && (
                      <p className="stock-help">
                        A QR is the quickest way. No QR? Use a photo or search
                        above.
                      </p>
                    )}
                    {(!inTask || direction === "IN") &&
                      !locked &&
                      !allComplete && (
                        <div className="new-item-prompt">
                          <span>Not in your catalogue?</span>
                          <div>
                            {imageId && status?.bedrockConfigured && (
                              <button
                                className="stock-link"
                                disabled={busy}
                                onClick={() => void readLabel()}
                              >
                                Suggest details from label
                              </button>
                            )}
                            <button
                              className="stock-link"
                              disabled={busy}
                              onClick={() => {
                                setDraft(null);
                                setNewItem(true);
                              }}
                            >
                              <Plus size={16} /> Register new item
                            </button>
                          </div>
                        </div>
                      )}
                  </>
                )}
                {active && (
                  <>
                    <div className="identified-item">
                      <ItemPhoto item={active} />
                      <div>
                        <span className="identified-tag">
                          <Check size={14} /> ITEM IDENTIFIED
                        </span>
                        <h2>{active.name}</h2>
                        <p>
                          {active.brand} ·{" "}
                          <strong>{active.part_number || active.sku}</strong>
                        </p>
                        <p>
                          {active.grade} {active.capacity}
                        </p>
                        <span className="shelf-chip">
                          {active.location || "Shelf not set"}
                        </span>
                      </div>
                    </div>
                    <div className="available-stock">
                      <span>Available now</span>
                      <b>
                        {number(active.quantity)}{" "}
                        <small>
                          {active.unit === "LITRE" ? "litres" : "units"}
                        </small>
                      </b>
                    </div>
                    {inTask ? (
                      <>
                        <label
                          className="stock-field quantity-label"
                          htmlFor="movement-quantity"
                        >
                          {direction === "IN"
                            ? "How many arrived?"
                            : "How many are leaving?"}
                        </label>
                        <div className="quantity-control">
                          <button
                            aria-label="Decrease quantity"
                            disabled={busy || quantity <= 1}
                            onClick={() =>
                              setQuantity(
                                Math.max(
                                  active.unit === "UNIT" ? 1 : 0.001,
                                  quantity - 1,
                                ),
                              )
                            }
                          >
                            −
                          </button>
                          <input
                            id="movement-quantity"
                            type="number"
                            min={active.unit === "UNIT" ? 1 : 0.001}
                            step={active.unit === "UNIT" ? 1 : 0.001}
                            value={quantity}
                            disabled={busy}
                            onChange={(e) =>
                              setQuantity(Number(e.target.value))
                            }
                          />
                          <button
                            aria-label="Increase quantity"
                            disabled={busy}
                            onClick={() => setQuantity(quantity + 1)}
                          >
                            +
                          </button>
                        </div>
                        {direction === "OUT" &&
                          quantity + plannedOut(task.lines, active.id) >
                            Number(active.quantity) && (
                            <p className="stock-error">
                              Not enough stock for this draft.
                            </p>
                          )}
                        {imageId && (
                          <label className="stock-check">
                            <input
                              type="checkbox"
                              checked={saveReference}
                              onChange={(e) =>
                                setSaveReference(e.target.checked)
                              }
                            />{" "}
                            Save this verified photo for future identification
                          </label>
                        )}
                        <button
                          className="button primary full large"
                          disabled={
                            busy ||
                            allComplete ||
                            locked ||
                            !validQuantity(quantity, active.unit) ||
                            (direction === "OUT" &&
                              quantity + plannedOut(task.lines, active.id) >
                                Number(active.quantity))
                          }
                          onClick={addLine}
                        >
                          <Plus size={19} /> Add to{" "}
                          {direction === "IN" ? "receipt" : "stock-out list"}
                        </button>
                        <p className="stock-help">
                          You will review the full list before stock changes.
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="stock-form-actions">
                          <button
                            className="button primary"
                            onClick={() => {
                              setView("receive");
                              setQuantity(1);
                            }}
                          >
                            Receive this item
                          </button>
                          <button
                            className="button secondary"
                            onClick={() => {
                              setView("issue");
                              setQuantity(1);
                            }}
                          >
                            Take this item out
                          </button>
                          <button
                            className="button secondary"
                            onClick={() => setLabelItem(active)}
                          >
                            <Printer size={17} /> QR label
                          </button>
                        </div>
                        {imageId && (
                          <button
                            className="stock-link"
                            disabled={busy}
                            onClick={() => void reference()}
                          >
                            Save verified reference photo only
                          </button>
                        )}
                      </>
                    )}
                  </>
                )}
                <input
                  ref={file}
                  type="file"
                  accept="image/jpeg,image/png"
                  capture="environment"
                  hidden
                  onChange={(e) => {
                    const photo = e.target.files?.[0];
                    if (photo) void analyse(photo);
                    e.target.value = "";
                  }}
                />
              </section>
              {inTask && (
                <section className="stock-panel draft-panel">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">
                        {allComplete
                          ? "COMPLETED"
                          : locked
                            ? "RECORDING STATUS"
                            : "NOT YET RECORDED"}
                      </p>
                      <h2>
                        {direction === "IN"
                          ? "Your receipt"
                          : "Your stock-out list"}
                      </h2>
                    </div>
                    <span className="counter">{task.lines.length}</span>
                  </div>
                  {!task.lines.length ? (
                    <div className="draft-empty">
                      <ListChecks size={40} />
                      <h3>Your list starts here</h3>
                      <p>
                        Scan an item, check the quantity,
                        <br />
                        and add it to this list.
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="draft-lines">
                        {task.lines.map((line) => (
                          <article
                            className={
                              "draft-line " +
                              (complete(line) ? "line-done" : "")
                            }
                            key={line.id}
                          >
                            <div>
                              <strong>{line.name}</strong>
                              <small>{line.part}</small>
                              <span
                                className={
                                  "line-status " +
                                  (complete(line) ? "success" : "")
                                }
                              >
                                {complete(line)
                                  ? "✓ Recorded"
                                  : line.movementId
                                    ? "Stock recorded · finishing review"
                                    : line.rejected
                                      ? "Rejected · remove this line to correct it"
                                      : line.attempted
                                        ? "Needs retry · quantity locked"
                                        : "Draft · stock unchanged"}
                              </span>
                              {line.error && (
                                <p className="stock-error">{line.error}</p>
                              )}
                            </div>
                            <b>
                              {number(line.quantity)}
                              <small>
                                {line.unit === "LITRE" ? "L" : "units"}
                              </small>
                            </b>
                            {(!locked || line.rejected) && (
                              <button
                                className="icon-button"
                                aria-label={"Remove " + line.name}
                                onClick={() =>
                                  persist({
                                    ...taskRef.current,
                                    [direction]: {
                                      ...taskRef.current[direction],
                                      lines: taskRef.current[
                                        direction
                                      ].lines.filter((l) => l.id !== line.id),
                                    },
                                  })
                                }
                              >
                                <X size={17} />
                              </button>
                            )}
                          </article>
                        ))}
                      </div>
                      <div className="draft-confirm">
                        <p>
                          {allComplete
                            ? "All items recorded. Your stock is up to date."
                            : locked
                              ? "Retry keeps the same command IDs and skips recorded movements."
                              : "Check each item and quantity. Confirming records these movements."}
                        </p>
                        {!allComplete && (
                          <button
                            className={
                              "button primary full large " +
                              (direction === "OUT" ? "out-button" : "")
                            }
                            disabled={busy || !session}
                            onClick={() => void commit()}
                          >
                            <Check size={20} />
                            {busy
                              ? "Recording…"
                              : locked
                                ? "Retry unfinished lines"
                                : direction === "IN"
                                  ? "Confirm receipt"
                                  : "Confirm stock-out"}
                          </button>
                        )}
                        <button
                          className="stock-link full"
                          disabled={busy}
                          onClick={discard}
                        >
                          {allComplete
                            ? "Start a new " +
                              (direction === "IN" ? "receipt" : "stock-out")
                            : locked
                              ? "Start a new task after resolving lines"
                              : "Clear draft"}
                        </button>
                      </div>
                    </>
                  )}
                </section>
              )}
            </div>
          </>
        )}
        {view === "stock" && (
          <>
            <div className="stock-title">
              <div>
                <p className="eyebrow">CATALOGUE & SHELVES</p>
                <h1>{owner ? "Manage catalogue" : "Current stock"}</h1>
                <p>
                  Find exact parts. Keep their labels and shelf details
                  together.
                </p>
              </div>
              <button
                className="button primary"
                onClick={() => {
                  resetIdentification();
                  setNewItem(true);
                }}
              >
                <Plus size={18} /> Register item
              </button>
            </div>
            <section className="stock-panel">
              <div className="stock-tools">
                <div className="search-box">
                  <Search size={19} />
                  <input
                    aria-label="Search stock"
                    placeholder="Name, part number or shelf"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                {owner && (
                  <label className="stock-check">
                    <input
                      type="checkbox"
                      checked={showArchived}
                      onChange={async (e) => {
                        const checked = e.target.checked;
                        setShowArchived(checked);
                        if (checked)
                          try {
                            setArchived(
                              await api<Item[]>(
                                "/api/inventory/products/archived",
                              ),
                            );
                          } catch (x) {
                            setError((x as Error).message);
                          }
                      }}
                    />{" "}
                    Archived items
                  </label>
                )}
              </div>
              <div className="catalogue-list">
                {filtered(showArchived ? archived : items, query).map((p) => (
                  <article className="catalogue-row" key={p.id}>
                    <ItemPhoto item={p} />
                    <div className="catalogue-description">
                      <strong>{p.name}</strong>
                      <small>
                        {p.brand} · {p.part_number || p.sku}
                      </small>
                      <span>
                        {p.category} · {p.location || "Shelf not set"}
                      </span>
                    </div>
                    <div className="catalogue-quantity">
                      <b>{number(p.quantity)}</b>
                      <small>{p.unit === "LITRE" ? "litres" : "units"}</small>
                      {Number(p.quantity) <= Number(p.reorder_level) &&
                        !p.archived && (
                          <span className="low-stock">Low stock</span>
                        )}
                    </div>
                    <div className="stock-row-actions">
                      <button onClick={() => setLabelItem(p)}>
                        <Printer size={16} /> QR label
                      </button>
                      {!p.archived && (
                        <button
                          onClick={() => {
                            navigate("find");
                            setSelected(p.id);
                          }}
                        >
                          View item
                        </button>
                      )}
                      {owner && (
                        <details>
                          <summary aria-label={"Actions for " + p.name}>
                            More
                          </summary>
                          <button onClick={() => setEdit(p)}>
                            Edit details
                          </button>
                          <button onClick={() => void archive(p, !p.archived)}>
                            {p.archived ? "Restore item" : "Archive item"}
                          </button>
                        </details>
                      )}
                    </div>
                  </article>
                ))}
              </div>
              {filtered(showArchived ? archived : items, query).length ===
                0 && (
                <div className="stock-empty">
                  <Package size={38} />
                  <h3>
                    {query
                      ? "No matching items"
                      : "Your catalogue is ready to begin"}
                  </h3>
                  <p>
                    {query
                      ? "Try the manufacturer part number."
                      : "Register your first item, then print its QR label."}
                  </p>
                </div>
              )}
            </section>
          </>
        )}
        {view === "count" && (
          <>
            <button className="back-link" onClick={() => navigate("home")}>
              <ArrowLeft size={17} /> Workspace
            </button>
            <div className="stock-title">
              <div>
                <p className="eyebrow">PHYSICAL STOCK CHECK</p>
                <h1>Count stock</h1>
                <p>Compare what is on the shelf with the recorded quantity.</p>
              </div>
            </div>
            <section className="stock-panel count-panel">
              <button className="scan-launch" onClick={() => setScanner(true)}>
                <ScanLine size={30} />
                <span>
                  <strong>Scan item QR</strong>
                  <small>Choose what you are counting</small>
                </span>
                <ArrowRight />
              </button>
              <label className="stock-field">
                Or search by part number
                <input
                  aria-label="Search count items"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Name or manufacturer part number"
                />
              </label>
              {search && (
                <div className="lookup-results">
                  {filtered(items, search)
                    .slice(0, 20)
                    .map((p) => (
                      <button
                        className="lookup-row"
                        key={p.id}
                        onClick={() => {
                          setCountId(p.id);
                          setPhysical("");
                          setSearch("");
                        }}
                      >
                        <ItemPhoto item={p} />
                        <span>
                          <strong>{p.name}</strong>
                          <small>{p.part_number || p.sku}</small>
                        </span>
                      </button>
                    ))}
                </div>
              )}
              {countItem && (
                <>
                  <div className="identified-item">
                    <ItemPhoto item={countItem} />
                    <div>
                      <h2>{countItem.name}</h2>
                      <p>
                        {countItem.brand} ·{" "}
                        {countItem.part_number || countItem.sku}
                      </p>
                      <span className="shelf-chip">
                        {countItem.location || "Shelf not set"}
                      </span>
                    </div>
                  </div>
                  <label className="stock-field">
                    Physically counted quantity
                    <input
                      type="number"
                      min="0"
                      step={countItem.unit === "UNIT" ? 1 : 0.001}
                      value={physical}
                      onChange={(e) => setPhysical(e.target.value)}
                    />
                  </label>
                  {physical !== "" &&
                    Number.isFinite(Number(physical)) &&
                    Number(physical) >= 0 &&
                    (Number(physical) === 0 ||
                      validQuantity(Number(physical), countItem.unit)) && (
                      <div
                        className={
                          "count-result " +
                          (Number(physical) === Number(countItem.quantity)
                            ? "balanced"
                            : "difference")
                        }
                      >
                        <h3>
                          {Number(physical) === Number(countItem.quantity)
                            ? "The count matches"
                            : "There is a difference"}
                        </h3>
                        <p>
                          Recorded: <b>{number(countItem.quantity)}</b> ·
                          Counted: <b>{number(Number(physical))}</b>
                        </p>
                        <p>
                          Difference:{" "}
                          <b>
                            {number(
                              Number(physical) - Number(countItem.quantity),
                            )}
                          </b>
                        </p>
                      </div>
                    )}
                  <p className="stock-help">
                    Comparison only. This does not change or save stock. Recheck
                    any difference with the owner before recording a correction.
                  </p>
                  <button
                    className="button secondary"
                    onClick={() => {
                      setCountId("");
                      setPhysical("");
                      setScanner(true);
                    }}
                  >
                    Check another item
                  </button>
                </>
              )}
            </section>
          </>
        )}
        {view === "activity" && (
          <>
            <div className="stock-title">
              <div>
                <p className="eyebrow">CONFIRMED MOVEMENTS</p>
                <h1>Stock activity</h1>
                <p>
                  A clear history of what changed, when and who recorded it.
                  Asia/Colombo.
                </p>
              </div>
            </div>
            <section className="stock-panel stock-table-wrap">
              <table className="stock-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Item</th>
                    <th>Movement</th>
                    <th>Quantity</th>
                    <th>Recorded by</th>
                  </tr>
                </thead>
                <tbody>
                  {moves.map((m) => (
                    <tr key={m.id}>
                      <td>{when(m.created_at)}</td>
                      <td>
                        <strong>{m.name}</strong>
                        <small>{m.sku}</small>
                      </td>
                      <td>
                        <span
                          className={
                            "movement-chip " +
                            (["STOCK_OUT", "ISSUE"].includes(m.kind)
                              ? "out"
                              : "in")
                          }
                        >
                          {m.kind === "STOCK_OUT"
                            ? "OUT"
                            : m.kind === "RECEIPT"
                              ? "IN"
                              : m.kind}
                        </span>
                      </td>
                      <td>{number(m.quantity)}</td>
                      <td>{m.actor}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!moves.length && (
                <div className="stock-empty">No recorded movements yet.</div>
              )}
            </section>
          </>
        )}
        {view === "review" && (
          <>
            <div className="stock-title">
              <div>
                <p className="eyebrow">CAMERA INBOX</p>
                <h1>
                  Needs review{" "}
                  <span className="heading-count">{pending.length}</span>
                </h1>
                <p>
                  Check the item and quantity, then add it to a receipt or
                  stock-out list.
                </p>
              </div>
            </div>
            <section className="stock-panel">
              {cameraError ? (
                <p className="stock-error" role="alert">
                  {cameraError}
                </p>
              ) : pending.length === 0 ? (
                <div className="stock-empty">
                  <Check size={42} />
                  <h3>You are all caught up</h3>
                  <p>No camera captures need review.</p>
                  <small>
                    A connected tray camera submits captures here once
                    configured.
                  </small>
                </div>
              ) : (
                pending.map((c) => {
                  const queued = Object.values(tasks).some((t) =>
                    t.lines.some((l) => l.captureId === c.id),
                  );
                  return (
                    <article className="camera-review-row" key={c.id}>
                      <Photo id={c.image_id} />
                      <div>
                        <span
                          className={
                            "movement-chip " +
                            (c.direction === "IN" ? "in" : "out")
                          }
                        >
                          {c.direction === "IN"
                            ? "Incoming item"
                            : "Outgoing item"}
                        </span>
                        <h3>{c.station_id}</h3>
                        <small>{when(c.created_at)}</small>
                      </div>
                      <button
                        className="button secondary"
                        disabled={queued}
                        onClick={() => review(c)}
                      >
                        {queued ? "Already in a draft" : "Review item"}{" "}
                        <ArrowRight size={17} />
                      </button>
                    </article>
                  );
                })
              )}
            </section>
          </>
        )}
      </main>
      {scanner && (
        <Scanner onScan={chooseQR} onClose={() => setScanner(false)} />
      )}
      {(newItem || edit) && (
        <ProductEditor
          item={edit}
          draft={draft}
          imageId={edit?.image_id || imageId}
          capture={null}
          inTask={inTask && !edit}
          products={items}
          onClose={() => {
            setNewItem(false);
            setEdit(null);
          }}
          onSaved={async (p, message) => {
            const wasEdit = !!edit;
            setNewItem(false);
            setEdit(null);
            setDraft(null);
            tell(message);
            await refresh();
            if (p && !wasEdit) {
              setLabelItem(p);
              if (inTask) {
                setSelected(p.id);
                setQuantity(1);
              } else {
                setView("find");
                setSelected(p.id);
              }
            }
          }}
        />
      )}
      {labelItem && (
        <LabelDialog item={labelItem} onClose={() => setLabelItem(null)} />
      )}
    </div>
  );
}
function ItemPhoto({ item }: { item: Item }) {
  return item.image_id ? (
    <Photo id={item.image_id} />
  ) : (
    <span className="photo-placeholder">
      <Package size={28} />
    </span>
  );
}
function LabelDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const [data, setData] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    QRCode.toDataURL("stocklane:v1:" + item.id, { width: 360, margin: 3 })
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => setError("QR generation failed. Reopen Print QR to retry."));
    return () => {
      active = false;
    };
  }, [item.id]);
  return (
    <div className="stock-modal-shade">
      <section
        className="stock-modal stock-label-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Printable QR label"
      >
        <button
          className="stock-close"
          aria-label="Close label"
          onClick={onClose}
        >
          <X />
        </button>
        <h2>Product QR label</h2>
        <p>Print and attach this label to the item or its storage bin.</p>
        {data && (
          <img
            className="stock-qr-preview"
            src={data}
            alt="Generated Stocklane product QR"
          />
        )}
        <h3>{item.name}</h3>
        <p>
          {item.brand} · {item.part_number || item.sku}
          <br />
          {item.location}
        </p>
        {error && <p role="alert">{error}</p>}
        <div className="stock-form-actions">
          <a
            className="button secondary"
            href={data}
            download={item.sku + "-qr.png"}
          >
            Download PNG
          </a>
          <button
            className="button primary"
            disabled={!data}
            onClick={() =>
              void printLabel(item).catch((e) => setError(e.message))
            }
          >
            <Printer size={18} /> Print / Save PDF
          </button>
        </div>
      </section>
    </div>
  );
}
function ProductEditor({
  item,
  draft,
  imageId,
  capture,
  inTask = false,
  products,
  onClose,
  onSaved,
}: {
  item: Item | null;
  draft: Draft | null;
  imageId: string;
  capture: CaptureEntry | null;
  inTask?: boolean;
  products: Item[];
  onClose: () => void;
  onSaved: (p: Item | null, message: string) => void;
}) {
  const d = draft?.fields || {};
  const [name, setName] = useState(item?.name || d.name || ""),
    [brand, setBrand] = useState(item?.brand || d.brand || ""),
    [part, setPart] = useState(item?.part_number || d.partNumber || ""),
    [category, setCategory] = useState(item?.category || d.category || ""),
    [spec, setSpec] = useState(item?.grade || d.grade || ""),
    [size, setSize] = useState(item?.capacity || d.capacity || ""),
    [location, setLocation] = useState(item?.location || ""),
    [quantity, setQuantity] = useState(0),
    [unit, setUnit] = useState(item?.unit || "UNIT"),
    [reorder, setReorder] = useState(Number(item?.reorder_level) || 0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const sku = useRef("ITEM-" + uid().slice(0, 8).toUpperCase());
  const command = useCommand();
  const duplicate = products.find(
    (p) =>
      p.id !== item?.id &&
      part.trim() &&
      p.brand.trim().toLowerCase() === brand.trim().toLowerCase() &&
      p.part_number?.trim().toLowerCase() === part.trim().toLowerCase(),
  );
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (duplicate) {
      setError(
        "This manufacturer and part number already exist. Use the existing product.",
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      const data = {
        name,
        brand,
        category,
        grade: spec,
        capacity: size,
        partNumber: part,
        location,
        reorderLevel: reorder,
      };
      let result: Item;
      if (item)
        result = await command<Item>(
          "/api/inventory/products/" + item.id,
          data,
          "PATCH",
        );
      else
        result = await command<Item>("/api/inventory/products", {
          ...data,
          sku: sku.current,
          barcode: null,
          unit,
          openingQuantity: quantity,
          sellingPrice: 0,
          imageId: imageId || null,
          sourceCaptureId: capture?.direction === "IN" ? capture.id : null,
        });
      let message = item
        ? "Catalogue updated. QR identity and stock history retained."
        : inTask
          ? "Item registered with zero stock. Add its quantity to your receipt."
          : "Item registered. Print its QR label to start scanning.";
      if (!item && draft) {
        try {
          await api("/api/vision/drafts/" + draft.id, {
            method: "PATCH",
            body: JSON.stringify({ status: "APPROVED", productId: result.id }),
          });
        } catch {
          message +=
            " AI draft resolution is pending; stock was already recorded.";
        }
      }
      if (!item && capture?.direction === "IN") {
        try {
          const movement = (
            await api<any>(
              "/api/inventory/captures/" + capture.id + "/movement",
            )
          ).movement;
          if (movement)
            await api("/api/vision/captures/" + capture.id, {
              method: "PATCH",
              body: JSON.stringify({ movementId: movement.id }),
            });
        } catch {
          message += " Camera status reconciliation is pending.";
        }
      }
      onSaved(result, message);
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stock-modal-shade">
      <section
        className="stock-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-title"
      >
        <button
          className="stock-close"
          aria-label="Close"
          disabled={busy}
          onClick={onClose}
        >
          <X />
        </button>
        <h2 id="product-title">
          {item ? "Edit catalogue item" : "Register a new item"}
        </h2>
        <p>
          {draft
            ? "AI suggestions require your review. Unreadable details are left blank."
            : "Use the visible manufacturer and part number where available."}
        </p>
        {imageId && <Photo id={imageId} />}
        <form onSubmit={(e) => void save(e)}>
          {inTask && (
            <p className="stock-help">
              Register the catalogue item here. Its received quantity is
              confirmed in your receipt afterwards.
            </p>
          )}
          <div className="stock-form-grid">
            {(
              [
                ["Item name", name, setName, true],
                ["Manufacturer / brand", brand, setBrand, true],
                ["Manufacturer part number", part, setPart, false],
                ["Category", category, setCategory, true],
                ["Shelf / location", location, setLocation, false],
              ] as const
            ).map(([label, value, set, required]) => (
              <label className="stock-field" key={label}>
                {label}
                <input
                  required={required}
                  maxLength={
                    label === "Manufacturer / brand"
                      ? 100
                      : label === "Category"
                        ? 80
                        : 180
                  }
                  value={value}
                  onChange={(e) => set(e.target.value)}
                />
              </label>
            ))}
            {!item && (
              <>
                <label className="stock-field">
                  Counting unit
                  <select
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                  >
                    <option value="UNIT">
                      Piece / sealed unit / defined set
                    </option>
                    <option value="LITRE">Measured litres</option>
                  </select>
                </label>
                {!inTask && (
                  <label className="stock-field">
                    Initial physical quantity
                    <input
                      type="number"
                      required
                      min={capture ? 1 : 0}
                      step={unit === "LITRE" ? 0.001 : 1}
                      value={quantity}
                      onChange={(e) => setQuantity(Number(e.target.value))}
                    />
                  </label>
                )}
              </>
            )}
            <details className="product-more">
              <summary>More details</summary>
              <label className="stock-field">
                Specification
                <input
                  maxLength={80}
                  value={spec}
                  onChange={(e) => setSpec(e.target.value)}
                />
              </label>
              <label className="stock-field">
                Size / pack description
                <input
                  maxLength={60}
                  value={size}
                  onChange={(e) => setSize(e.target.value)}
                />
              </label>
              <label className="stock-field">
                Low-stock threshold
                <input
                  type="number"
                  min="0"
                  step={unit === "LITRE" ? 0.001 : 1}
                  required
                  value={reorder}
                  onChange={(e) => setReorder(Number(e.target.value))}
                />
              </label>
            </details>
          </div>
          {duplicate && (
            <p className="stock-error">
              Existing item: {duplicate.name}. Close this form and select it
              instead.
            </p>
          )}
          {error && (
            <p className="stock-error" role="alert">
              {error}
            </p>
          )}
          <div className="stock-form-actions">
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={onClose}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy || !!duplicate}>
              {busy ? "Saving…" : item ? "Save changes" : "Approve & register"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
