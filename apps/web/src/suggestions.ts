/** Field suggestions for a new item: AI answers for gaps in the label text, plus values copied from similar items you already stock. */
export type Field = "name" | "brand" | "partNumber" | "category" | "grade" | "capacity" | "location" | "unit";
export type Suggestion = { value: string; why: string };
type Known = Partial<Record<Field, string>>;
type Stocked = { name: string; brand: string; category: string; location?: string | null; unit: string };

const norm = (s: string | null | undefined) => (s || "").trim().toLowerCase();
function mostCommon(values: (string | null | undefined)[]) {
  const counts = new Map<string, { value: string; n: number }>();
  for (const v of values) {
    const key = norm(v);
    if (!key) continue;
    const entry = counts.get(key) || { value: (v as string).trim(), n: 0 };
    entry.n += 1;
    counts.set(key, entry);
  }
  return [...counts.values()].sort((a, b) => b.n - a.n)[0]?.value;
}

export function suggestFields(label: Known, ai: Known, stocked: Stocked[]): Partial<Record<Field, Suggestion>> {
  const out: Partial<Record<Field, Suggestion>> = {};
  const has = (f: Field) => !!(label[f] || "").trim();
  for (const [field, value] of Object.entries(ai) as [Field, string][])
    if (value && value.trim() && !has(field)) out[field] = { value: value.trim(), why: "AI suggestion" };
  const value = (f: Field) => (label[f] || out[f]?.value || "").trim();
  const brand = value("brand");
  const sameBrand = brand ? stocked.filter((p) => norm(p.brand) === norm(brand)) : [];
  if (!has("category") && !out.category) {
    const category = mostCommon(sameBrand.map((p) => p.category));
    if (category) out.category = { value: category, why: "like your other " + brand + " items" };
  }
  const category = value("category");
  const sameCategory = category ? stocked.filter((p) => norm(p.category) === norm(category)) : [];
  if (!has("location")) {
    const near = sameBrand.filter((p) => !category || norm(p.category) === norm(category));
    const shelf = mostCommon(near.map((p) => p.location)) || mostCommon(sameCategory.map((p) => p.location));
    if (shelf) out.location = { value: shelf, why: "where similar items are kept" };
  }
  const unit = mostCommon(sameCategory.map((p) => p.unit));
  if (unit === "LITRE") out.unit = { value: "LITRE", why: "similar items are counted in litres" };
  if (!has("name") && !out.name) {
    const parts = [brand, value("grade"), value("capacity")].filter(Boolean);
    if (parts.length >= 2 || (parts.length === 1 && category)) out.name = { value: [...parts, parts.length < 2 ? category : ""].filter(Boolean).join(" "), why: "built from the label" };
  }
  return out;
}
