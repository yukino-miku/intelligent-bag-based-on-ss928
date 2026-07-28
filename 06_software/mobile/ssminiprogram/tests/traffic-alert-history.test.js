const assert = require("assert");
const history = require("../miniprogram/utils/traffic-alert-history");

const storage = {};
const removed = [];
const wxApi = {
  getStorageSync(key) { return storage[key]; },
  setStorageSync(key, value) { storage[key] = JSON.parse(JSON.stringify(value)); },
  removeSavedFile(options) { removed.push(options.filePath); },
  saveFile(options) { options.success({ savedFilePath: "saved://alert.jpg" }); }
};

const reset = () => {
  Object.keys(storage).forEach((key) => delete storage[key]);
  removed.length = 0;
};

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test("deduplicates by event_id", () => {
  reset();
  history.upsertEvent(wxApi, { event_id: "evt-1", level: 3, effective_score: 0.7 });
  history.upsertEvent(wxApi, { event_id: "evt-1", level: 4, effective_score: 0.9 });
  const items = history.loadHistory(wxApi);
  assert.strictEqual(items.length, 1);
  assert.strictEqual(items[0].level, 4);
});

test("keeps metadata and marks retry when board is offline", async () => {
  reset();
  const boardApi = { getAlert() { return Promise.reject(new Error("offline")); } };
  const result = await history.syncTrafficAlert(wxApi, boardApi, { event_id: "evt-2", level: 3, side: "left" });
  assert.strictEqual(result.syncStatus, "retry_pending");
  assert.strictEqual(history.loadHistory(wxApi)[0].eventId, "evt-2");
});

test("downloads and saves the board image while CloudBase failure is non-fatal", async () => {
  reset();
  const boardApi = {
    getAlert() { return Promise.resolve({ event_id: "evt-3", level: 4, image_status: "saved", class_name: "truck" }); },
    downloadAlertImage() { return Promise.resolve("temp://alert.jpg"); }
  };
  const result = await history.syncTrafficAlert(wxApi, boardApi, { event_id: "evt-3", level: 4 }, {
    cloudUploader() { return Promise.reject(new Error("cloud unavailable")); }
  });
  assert.strictEqual(result.localImagePath, "saved://alert.jpg");
  assert.strictEqual(result.syncStatus, "complete");
});

test("prunes old local images", () => {
  reset();
  const items = [
    { event_id: "new", start_time: 3, localImagePath: "saved://new.jpg" },
    { event_id: "middle", start_time: 2, localImagePath: "saved://middle.jpg" },
    { event_id: "old", start_time: 1, localImagePath: "saved://old.jpg" }
  ];
  const kept = history.saveHistory(wxApi, items, { limit: 2, imageLimit: 1 });
  assert.strictEqual(kept.length, 2);
  assert.deepStrictEqual(removed.sort(), ["saved://middle.jpg", "saved://old.jpg"]);
});

const run = async () => {
  let failures = 0;
  for (const item of tests) {
    try {
      await item.fn();
      console.log("ok - " + item.name);
    } catch (error) {
      failures += 1;
      console.error("not ok - " + item.name);
      console.error(error.stack || error);
    }
  }
  if (failures) process.exit(1);
};

run();
