const assert = require("assert");

const telemetry = require("../cloudfunctions/smartbag-device-ingest/lib/telemetry-core");
const appApi = require("../cloudfunctions/smartbag-app-api/lib/app-api-core");

const tests = [];
const test = (name, fn) => tests.push({ name, fn });
const UPLOAD_TOKEN = "competition-upload-token";

const makePayload = () => ({
  version: 1,
  deviceId: "bag001",
  requestId: "batch-1784160000000",
  reportedAt: 1784160000000,
  status: {
    location: { latitude: 30.65736, longitude: 104.0832 },
    attitude: { rollDeg: 1.2, pitchDeg: -3.4, yawDeg: 92.1 },
    risk: { level: 1, type: "rear_vehicle", direction: "left_rear" },
    battery: { percent: 82 },
    network: { type: "5g-redcap", rssiDbm: -81 },
    firmwareVersion: "sim-v1"
  },
  trackPoints: [{
    requestId: "track-1784160000000",
    reportedAt: 1784160000000,
    location: { latitude: 30.65736, longitude: 104.0832 },
    speed: 1.2,
    heading: 92
  }],
  alarms: [{
    requestId: "fall-1784160000000",
    alarmId: "fall-1784160000000",
    reportedAt: 1784160000000,
    alarmType: "fall_detected",
    riskLevel: 3,
    message: "fall detected",
    location: { latitude: 30.65736, longitude: 104.0832 }
  }]
});

const makeStore = (initialStatus) => {
  const state = { status: Object.assign({}, initialStatus || {}), tracks: [], alarms: [], daily: null };
  return {
    state,
    async mergeStatus(document) { state.status = Object.assign({}, state.status, document); },
    async insertTrackPoint(document) { state.tracks.push(document); },
    async insertAlarm(document) { state.alarms.push(document); },
    async setPostureDaily(document) { state.daily = document; }
  };
};

test("accepts the upload token and writes all records as bag001", async () => {
  const store = makeStore();
  const processor = telemetry.createTelemetryProcessor({ store, uploadToken: UPLOAD_TOKEN, now: () => "2026-07-17T00:00:00.000Z" });
  const result = await processor.process({
    headers: { "x-upload-token": UPLOAD_TOKEN },
    rawBody: Buffer.from(JSON.stringify(makePayload()))
  });
  assert.deepStrictEqual(result, { success: true });
  assert.strictEqual(store.state.status._id, "bag001");
  assert.strictEqual(store.state.status.deviceId, "bag001");
  assert.strictEqual(store.state.tracks[0].deviceId, "bag001");
  assert.strictEqual(store.state.alarms[0].deviceId, "bag001");
});

test("merges partial posture without deleting the latest GNSS location and writes daily totals", async () => {
  const store = makeStore({ location: { latitude: 30.1, longitude: 104.1, valid: true } });
  const processor = telemetry.createTelemetryProcessor({ store, uploadToken: UPLOAD_TOKEN, now: () => "2026-07-20T00:00:00.000Z" });
  const payload = {
    version: 1,
    deviceId: "bag001",
    requestId: "posture-1",
    reportedAt: 1784505600000,
    status: {
      reportedAt: 1784505600000,
      posture_status: "bad",
      is_wearing: true,
      reminder_active: true,
      attitude: { rollDeg: 1.2, pitchDeg: -18.4, yawDeg: 92.1 }
    },
    postureDaily: {
      device_id: "bag001",
      date: "2026-07-20",
      wearing_seconds: 20,
      good_seconds: 15,
      bad_seconds: 5,
      updated_at: 1784505600000
    },
    trackPoints: [],
    alarms: []
  };

  const result = await processor.process({
    headers: { "x-upload-token": UPLOAD_TOKEN },
    rawBody: Buffer.from(JSON.stringify(payload))
  });

  assert.deepStrictEqual(result, { success: true });
  assert.strictEqual(store.state.status.location.latitude, 30.1);
  assert.strictEqual(store.state.status.posture_status, "bad");
  assert.strictEqual(store.state.daily._id, "bag001_2026-07-20");
  assert.strictEqual(store.state.daily.bad_seconds, 5);
});

test("rejects invalid posture and missing append request ids before writing", async () => {
  const invalidPayloads = [
    Object.assign(makePayload(), { status: { posture_status: "hunch" } }),
    Object.assign(makePayload(), { trackPoints: [{ reportedAt: 1784160000000, location: { latitude: 30, longitude: 104 } }] }),
    Object.assign(makePayload(), { alarms: [{ reportedAt: 1784160000000, alarmType: "fall_detected", riskLevel: 3 }] }),
    Object.assign(makePayload(), { status: { location: { latitude: 91, longitude: 104 } } }),
    Object.assign(makePayload(), { postureDaily: { device_id: "bag001", date: "2026-07-20", wearing_seconds: 5, good_seconds: 4, bad_seconds: 2, updated_at: 1784160000000 } })
  ];

  for (let index = 0; index < invalidPayloads.length; index += 1) {
    const store = makeStore();
    const processor = telemetry.createTelemetryProcessor({ store, uploadToken: UPLOAD_TOKEN });
    const result = await processor.process({
      headers: { "x-upload-token": UPLOAD_TOKEN },
      rawBody: Buffer.from(JSON.stringify(invalidPayloads[index]))
    });
    assert.strictEqual(result.success, false);
    assert.strictEqual(result.error.code, "INVALID_TELEMETRY");
    assert.deepStrictEqual(store.state.status, {});
    assert.strictEqual(store.state.tracks.length, 0);
    assert.strictEqual(store.state.alarms.length, 0);
  }
});

test("rejects an invalid upload token", async () => {
  const processor = telemetry.createTelemetryProcessor({ store: makeStore(), uploadToken: UPLOAD_TOKEN });
  const result = await processor.process({
    headers: { "x-upload-token": "wrong-token" },
    rawBody: Buffer.from(JSON.stringify(makePayload()))
  });
  assert.strictEqual(result.success, false);
  assert.strictEqual(result.error.code, "INVALID_UPLOAD_TOKEN");
});

test("returns latest status without user binding", async () => {
  const api = appApi.createAppApi({
    repository: { async getStatus(deviceId) { return { deviceId, battery: { percent: 82 } }; } }
  });
  const result = await api.handle({ action: "getLatestStatus" });
  assert.deepStrictEqual(result, { ok: true, data: { status: { deviceId: "bag001", battery: { percent: 82 } } } });
});

test("returns daily posture for the requested local date", async () => {
  const api = appApi.createAppApi({
    repository: {
      async getDailyPosture(deviceId, date) {
        return { device_id: deviceId, date, wearing_seconds: 3600 };
      }
    }
  });
  const result = await api.handle({ action: "getDailyPosture", date: "2026-07-18" });
  assert.deepStrictEqual(result, {
    ok: true,
    data: { posture: { device_id: "bag001", date: "2026-07-18", wearing_seconds: 3600 } }
  });
});

test("limits history reads to 100 records", async () => {
  const api = appApi.createAppApi({
    repository: { async listTrackPoints(deviceId, limit) { return Array.from({ length: limit }, (_, index) => ({ deviceId, sequence: index })); } }
  });
  const result = await api.handle({ action: "getTrackPoints" });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.data.items.length, 100);
  assert.strictEqual(result.data.items[0].deviceId, "bag001");
});

const run = async () => {
  let failed = 0;
  for (let index = 0; index < tests.length; index += 1) {
    const item = tests[index];
    try {
      await item.fn();
      console.log("ok - " + item.name);
    } catch (error) {
      failed += 1;
      console.error("not ok - " + item.name);
      console.error(error && error.stack ? error.stack : error);
    }
  }
  if (failed) process.exit(1);
};

run();
