import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validQuantity,
  plannedOut,
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
test("stock recorded is distinct from reference indexing", () => {
  assert.equal(complete(line), false);
  assert.equal(complete({ ...line, movementId: "m1" }), true);
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
