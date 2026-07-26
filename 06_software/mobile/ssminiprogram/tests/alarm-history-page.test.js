const assert = require("assert");

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

let registeredPage;
let alarmItems = [];
let alarmFailure = null;

global.Page = (definition) => { registeredPage = definition; };
global.wx = {
  cloud: {
    callFunction() {
      if (alarmFailure) {
        return Promise.reject(alarmFailure);
      }
      return Promise.resolve({ result: { ok: true, data: { items: alarmItems } } });
    }
  },
  setNavigationBarTitle() {},
  navigateTo() {},
  navigateBack() {},
  redirectTo() {}
};

require("../miniprogram/pages/alarms/index");

const createPage = () => {
  const page = Object.assign({}, registeredPage, { data: Object.assign({}, registeredPage.data) });
  page.setData = (patch) => Object.assign(page.data, patch);
  return page;
};

const flushPromises = () => new Promise((resolve) => setImmediate(resolve));

test("loads only fall_detected CloudBase alarms in newest-first order", async () => {
  alarmFailure = null;
  alarmItems = [
    { alarmId: "collision", alarmType: "collision", reportedAt: 1784160003000 },
    { alarmId: "older-fall", alarmType: "fall_detected", reportedAt: 1784160001000, message: "older", location: { latitude: 30.1, longitude: 104.1 } },
    { alarmId: "newer-fall", alarmType: "fall_detected", reportedAt: 1784160002000, message: "newer" }
  ];
  const page = createPage();

  page.onLoad({});
  page.onShow();
  await flushPromises();

  assert.deepStrictEqual(page.data.alarmRecords.map((item) => item.id), ["newer-fall", "older-fall"]);
  assert.strictEqual(page.data.alarmRecords[0].typeText, "检测到摔倒");
  assert.strictEqual(page.data.alarmRecords[0].riskText, "高风险");
  assert.strictEqual(page.data.alarmRecords[0].locationText, "暂无定位");
  assert.strictEqual(page.data.alarmRecords[1].locationText, "30.100000, 104.100000");
});

test("shows a usable error state when CloudBase alarm loading fails", async () => {
  alarmFailure = { code: "CLOUD_CALL_FAILED" };
  const page = createPage();

  page.onLoad({});
  page.onShow();
  await flushPromises();

  assert.strictEqual(page.data.alarmLoading, false);
  assert.strictEqual(page.data.alarmError, "云端报警加载失败，请稍后重试");
  assert.deepStrictEqual(page.data.alarmRecords, []);
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
