import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validQuantity,
  plannedOut,
  verifyExisting,
  complete,
  emptyTask,
} from "../src/task.ts";
const line = {
  id: "l1",
  key: "command-one",
  productId: "filter",
  name: "Filter",
  part: "AC-123",
  quantity: 2,
  unit: "UNIT",
  attempted: false,
  reference: false,
};
test("reject invalid counts and fractional pieces; measured litres allow three decimals", () => {
  for (const n of [NaN, Infinity, -1, 0, 1.2])
    assert.equal(validQuantity(n, "UNIT"), false);
  assert.equal(validQuantity(2, "UNIT"), true);
  assert.equal(validQuantity(1.125, "LITRE"), true);
  assert.equal(validQuantity(1.1255, "LITRE"), false);
});
test("outgoing draft includes every unsent line for the item, but not recorded lines", () => {
  assert.equal(
    plannedOut(
      [
        line,
        { ...line, id: "l2", quantity: 3 },
        { ...line, id: "l3", quantity: 8, movementId: "m1" },
        { ...line, productId: "belt", quantity: 7 },
      ],
      "filter",
    ),
    5,
  );
});
test("capture reuse cannot silently accept another product, amount or direction", () => {
  const movement = { product_id: "filter", kind: "STOCK_OUT", quantity: 2 };
  assert.doesNotThrow(() => verifyExisting(movement, line, "OUT"));
  assert.throws(() =>
    verifyExisting({ ...movement, product_id: "belt" }, line, "OUT"),
  );
  assert.throws(() =>
    verifyExisting({ ...movement, quantity: 3 }, line, "OUT"),
  );
  assert.throws(() => verifyExisting(movement, line, "IN"));
});
test("stock recorded is distinct from camera reconciliation and reference indexing", () => {
  assert.equal(complete(line), false);
  assert.equal(complete({ ...line, movementId: "m1" }), true);
  assert.equal(complete({ ...line, movementId: "m1", captureId: "c1" }), false);
  assert.equal(
    complete({ ...line, movementId: "m1", captureId: "c1", reconciled: true }),
    true,
  );
  assert.equal(complete({ ...line, movementId: "m1", reference: true }), false);
  assert.equal(
    complete({
      ...line,
      movementId: "m1",
      reference: true,
      referenceSaved: true,
    }),
    true,
  );
});
test("new tasks have independent identities", () =>
  assert.notEqual(emptyTask().id, emptyTask().id));
