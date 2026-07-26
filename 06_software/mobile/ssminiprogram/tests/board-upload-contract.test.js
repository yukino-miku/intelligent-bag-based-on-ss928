const assert = require("assert");
const fs = require("fs");
const path = require("path");

const postureUtils = require("../miniprogram/utils/posture-utils");
const trackUtils = require("../miniprogram/utils/track-utils");

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test("processed BMI270 status maps to realtime good and bad posture", () => {
  const bad = postureUtils.normalizeRealtimePosture({
    deviceId: "bag001",
    posture_status: "bad",
    is_wearing: true,
    reminder_active: true,
    receivedAt: "2026-07-20T10:00:00.000Z",
    attitude: { rollDeg: 1.2, pitchDeg: -18.4, yawDeg: 92.1 }
  });
  assert.strictEqual(bad.postureStatus, "bad");
  assert.strictEqual(bad.isWearing, true);
  assert.strictEqual(bad.reminderActive, true);
  assert.strictEqual(Object.prototype.hasOwnProperty.call(bad, "attitude"), false);
});

test("CloudBase ISO receivedAt remains a valid realtime timestamp", () => {
  const receivedAt = "2026-07-21T18:00:06.410Z";
  const posture = postureUtils.normalizeRealtimePosture({
    deviceId: "bag001",
    posture_status: "good",
    is_wearing: true,
    receivedAt
  });
  const display = postureUtils.toRealtimeDisplay(posture, Date.parse(receivedAt) + 5000, 60000);
  assert.strictEqual(display.statusLevel, "connected");
  assert.strictEqual(display.postureKey, "good");
});

test("absolute board daily totals map to the analysis percentages", () => {
  const daily = postureUtils.normalizeDailyPosture({
    device_id: "bag001",
    date: "2026-07-20",
    wearing_seconds: 20,
    good_seconds: 15,
    bad_seconds: 5,
    updated_at: 1784505600000
  });
  assert.strictEqual(daily.goodPercent, 75);
  assert.strictEqual(daily.badPercent, 25);
  assert.strictEqual(daily.hasValidData, true);
});

test("DX-GP21-A CloudBase point maps from WGS84 to the map model", () => {
  const point = trackUtils.normalizeCloudTrackPoint({
    reportedAt: 1784505600000,
    location: { latitude: 30.65736, longitude: 104.0832, accuracyM: 8, valid: true },
    speed: 1.2,
    heading: 92,
    source: "dx_gp21",
    coordinateSystem: "wgs84"
  });
  assert.ok(point);
  assert.strictEqual(point.rawLatitude, 30.65736);
  assert.strictEqual(point.rawLongitude, 104.0832);
  assert.notStrictEqual(point.latitude, point.rawLatitude);
});

test("alarm page reads fall_detected history and does not request warning uploads", () => {
  const pageSource = fs.readFileSync(
    path.join(__dirname, "..", "miniprogram", "pages", "alarms", "index.js"),
    "utf8"
  );
  assert.ok(pageSource.indexOf('FALL_ALARM_TYPE = "fall_detected"') >= 0);
  assert.ok(pageSource.indexOf("alarmType === FALL_ALARM_TYPE") >= 0);
  assert.strictEqual(pageSource.indexOf("rear_vehicle"), -1);
});

let failed = 0;
for (let index = 0; index < tests.length; index += 1) {
  try {
    tests[index].fn();
    console.log("ok - " + tests[index].name);
  } catch (error) {
    failed += 1;
    console.error("not ok - " + tests[index].name);
    console.error(error && error.stack ? error.stack : error);
  }
}
if (failed) process.exit(1);
