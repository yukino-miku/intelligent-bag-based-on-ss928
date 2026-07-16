const assert = require("assert");
const { createAlertState, applyAlertFrame } = require("../miniprogram/utils/alert-state");

let state = createAlertState();
state = applyAlertFrame(state, { typ: "alert", side: "left", level: 3, name: "DANGER", class: "car", distance_m: 4.2 }, 3);
assert.strictEqual(state.current.left.level, 3);
assert.strictEqual(state.current.right.level, 0);
assert.strictEqual(state.history.length, 1);
assert.ok(state.history[0].key);

state = applyAlertFrame(state, { typ: "alert", side: "right", level: 2, name: "CAUTION" }, 3);
assert.strictEqual(state.current.left.level, 3);
assert.strictEqual(state.current.right.level, 2);
assert.notStrictEqual(state.history[0].key, state.history[1].key);

state = applyAlertFrame(state, { typ: "alert", side: "left", level: 0, name: "SAFE" }, 3);
assert.strictEqual(state.current.left.level, 0);
assert.strictEqual(state.current.right.level, 2);
assert.strictEqual(state.history.length, 2);

for (let index = 0; index < 5; index += 1) {
  state = applyAlertFrame(state, { typ: "alert", side: "right", level: 1 }, 3);
}
assert.strictEqual(state.history.length, 3);

console.log("alert state tests passed");
