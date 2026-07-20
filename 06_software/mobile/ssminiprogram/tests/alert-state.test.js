const assert = require("assert");
const { createAlertState, applyAlertFrame } = require("../miniprogram/utils/alert-state");

let state = createAlertState();
state = applyAlertFrame(state, { typ: "alert", side: "left", level: 3, name: "DANGER", class: "car", distance_m: 4.2 }, 3);
assert.strictEqual(state.current.left.level, 3);
assert.strictEqual(state.current.right.level, 0);
assert.strictEqual(state.history.length, 1);
assert.ok(state.history[0].key);
assert.strictEqual(state.history[0].name, "危险");

state = applyAlertFrame(state, { typ: "alert", side: "right", level: 2, name: "CAUTION" }, 3);
assert.strictEqual(state.current.left.level, 3);
assert.strictEqual(state.current.right.level, 2);
assert.notStrictEqual(state.history[0].key, state.history[1].key);

state = applyAlertFrame(state, { typ: "alert", side: "left", level: 0, name: "SAFE" }, 3);
assert.strictEqual(state.current.left.level, 0);
assert.strictEqual(state.current.right.level, 2);
assert.strictEqual(state.history.length, 2);

state = applyAlertFrame(state, {
  typ: "alert", side: "left", level: 0, event_kind: "state_change",
  clear_reason: "source_timeout", effective_level: 0, haptic_level: 0,
  light_mode: "off", audio_enabled: true
}, 100, "BLE");
assert.strictEqual(state.history.length, 3);
assert.strictEqual(state.history[0].clearReason, "source_timeout");
assert.strictEqual(state.history[0].dataSource, "BLE");

const beforeHeartbeat = state.history.length;
state = applyAlertFrame(state, { typ: "alert", side: "right", level: 4, event_kind: "heartbeat" }, 100);
assert.strictEqual(state.history.length, beforeHeartbeat);

for (let index = 0; index < 5; index += 1) {
  state = applyAlertFrame(state, { typ: "alert", side: "right", level: 1 }, 3);
}
assert.strictEqual(state.history.length, 3);
assert.strictEqual(state.current.right.level, 1);

for (let index = 0; index < 120; index += 1) {
  state = applyAlertFrame(state, {
    typ: "alert", side: index % 2 ? "left" : "right", level: (index % 4) + 1,
    event_kind: "state_change", source: "vision:" + index
  }, 100, "Cloud");
}
assert.strictEqual(state.history.length, 100);
assert.strictEqual(state.history[0].dataSource, "Cloud");

console.log("alert state tests passed");
