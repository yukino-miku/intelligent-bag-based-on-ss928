const assert = require("assert");
const alarm = require("../miniprogram/utils/alarm-utils");

const tests = [];

const test = (name, fn) => {
  tests.push({ name, fn });
};

test("mock alarm records expose the requested dates in Chengdu", () => {
  const records = alarm.getAlarmRecords();

  assert.strictEqual(records.length, 3);
  assert.deepStrictEqual(records.map((item) => item.dateLabel), ["7.1", "7.5", "7.6"]);

  records.forEach((item) => {
    assert.ok(item.timeText.indexOf("2026-07-") === 0);
    assert.ok(item.latitude > 30.45 && item.latitude < 30.85);
    assert.ok(item.longitude > 103.85 && item.longitude < 104.25);
    assert.ok(item.locationText.indexOf("成都") >= 0);
  });
});

test("findAlarmById resolves known records and falls back to the latest", () => {
  const selected = alarm.findAlarmById("alarm-20260705");
  assert.strictEqual(selected.dateLabel, "7.5");

  const fallback = alarm.findAlarmById("missing");
  assert.strictEqual(fallback.dateLabel, "7.6");
});

test("buildAlarmMarker returns a single map marker at the alarm location", () => {
  const selected = alarm.findAlarmById("alarm-20260701");
  const markers = alarm.buildAlarmMarker(selected);

  assert.strictEqual(markers.length, 1);
  assert.strictEqual(markers[0].id, 1);
  assert.strictEqual(markers[0].latitude, selected.latitude);
  assert.strictEqual(markers[0].longitude, selected.longitude);
  assert.ok(markers[0].callout.content.indexOf("危险报警") >= 0);
});

let failed = 0;

for (let i = 0; i < tests.length; i += 1) {
  const item = tests[i];
  try {
    item.fn();
    console.log("ok - " + item.name);
  } catch (err) {
    failed += 1;
    console.error("not ok - " + item.name);
    console.error(err && err.stack ? err.stack : err);
  }
}

if (failed) {
  process.exit(1);
}
