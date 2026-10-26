export type Direction = "IN" | "OUT";
export type TaskLine = {
  id: string;
  key: string;
  productId: string;
  name: string;
  part: string;
  unit: string;
  quantity: number;
  captureId?: string;
  imageId?: string;
  reference: boolean;
  attempted: boolean;
  movementId?: string;
  reconciled?: boolean;
  referenceSaved?: boolean;
  rejected?: boolean;
  error?: string;
};
export type StockTask = { id: string; lines: TaskLine[] };
export function emptyTask(): StockTask {
  return { id: crypto.randomUUID(), lines: [] };
}
export function complete(line: TaskLine) {
  return (
    !!line.movementId &&
    (!line.captureId || !!line.reconciled) &&
    (!line.reference || !!line.referenceSaved)
  );
}
export function validQuantity(quantity: number, unit: string) {
  return (
    Number.isFinite(quantity) &&
    quantity > 0 &&
    quantity <= 999999999 &&
    Math.abs(quantity * 1000 - Math.round(quantity * 1000)) < 0.00001 &&
    (unit !== "UNIT" || Number.isInteger(quantity))
  );
}
export function plannedOut(lines: TaskLine[], productId: string) {
  return lines
    .filter((line) => line.productId === productId && !line.movementId)
    .reduce((sum, line) => sum + line.quantity, 0);
}
/** Existing evidence must never silently resolve to another item or amount. */
export function verifyExisting(
  movement: { product_id: string; kind: string; quantity: number },
  line: TaskLine,
  direction: Direction,
) {
  if (
    movement.product_id !== line.productId ||
    movement.kind !== (direction === "IN" ? "RECEIPT" : "STOCK_OUT") ||
    Number(movement.quantity) !== line.quantity
  )
    throw new Error(
      "This camera capture already has a different stock movement. Check Stock activity before continuing.",
    );
}
