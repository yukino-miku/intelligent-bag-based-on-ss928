const assert = require("assert");

let registeredPage;
global.Page = (definition) => { registeredPage = definition; };
global.setInterval = () => ({ timer: true });
global.clearInterval = () => {};
global.wx = {
  cloud: {
    callFunction({ data }) {
      assert.strictEqual(data.action, "getDailyPosture");
      return Promise.resolve({ result: { ok: true, data: { posture: {
        device_id: "bag001",
        date: data.date,
        wearing_seconds: 10800,
        good_seconds: 8100,
        bad_seconds: 2700,
        updated_at: "2026-07-18T10:00:00.000Z"
      } } } });
    }
  },
  createCanvasContext() { return { setFillStyle() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, closePath() {}, setFontSize() {}, setTextAlign() {}, fillText() {}, draw() {} }; },
  redirectTo() {}
};
require("../miniprogram/pages/posture-analysis/index");

const page = Object.assign({}, registeredPage, { data: Object.assign({}, registeredPage.data) });
page.setData = (patch, callback) => { Object.assign(page.data, patch); if (callback) callback(); };

page.onShow();
setImmediate(() => {
  try {
    assert.strictEqual(page.data.stats.goodPercent, 75);
    assert.strictEqual(page.data.stats.badPercent, 25);
    assert.strictEqual(page.data.stats.wearingDuration, "3小时");
    assert.strictEqual(page.data.stats.goodDuration, "2小时15分钟");
    assert.strictEqual(page.data.stats.badDuration, "45分钟");
    assert.strictEqual(page.data.dataMessage, "");
    page.onHide();
    console.log("ok - posture analysis renders daily CloudBase statistics without angle samples");
  } catch (error) {
    console.error(error.stack || error);
    process.exitCode = 1;
  }
});
