const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "miniprogram");
const read = (page, extension) => fs.readFileSync(path.join(root, "pages", page, "index." + extension), "utf8");
const analysisJs = read("posture-analysis", "js");
const analysisWxml = read("posture-analysis", "wxml");
const monitorJs = read("posture-live", "js");
const monitorWxml = read("posture-live", "wxml");
const cloudSource = fs.readFileSync(path.join(root, "services", "cloud-data-source.js"), "utf8");

const test = (name, fn) => {
  try {
    fn();
    console.log("ok - " + name);
  } catch (error) {
    console.error("not ok - " + name);
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
  }
};

test("posture analysis keeps the presentation layout and uses daily cloud statistics", () => {
  assert.ok(analysisWxml.indexOf("今日姿态分析") >= 0);
  assert.strictEqual(analysisWxml.indexOf("今日累计时长"), -1);
  assert.ok(analysisJs.indexOf("getDailyPosture") >= 0);
  assert.ok(analysisJs.indexOf("goodPercent: 100, badPercent: 0") >= 0);
  assert.strictEqual(analysisWxml.indexOf("最近姿态记录"), -1);
  assert.strictEqual(analysisJs.indexOf("pitchDeg"), -1);
});

test("realtime posture is presentation-only and refreshes only while visible", () => {
  assert.ok(monitorWxml.indexOf("BMI270 实时姿态") >= 0);
  assert.ok(monitorJs.indexOf("getRealtimePosture") >= 0);
  assert.ok(monitorJs.indexOf("onHide") >= 0);
  assert.ok(monitorJs.indexOf("onUnload") >= 0);
  assert.strictEqual(monitorWxml.indexOf("pitch"), -1);
  assert.strictEqual(monitorWxml.indexOf("roll"), -1);
  assert.strictEqual(monitorWxml.indexOf("yaw"), -1);
  assert.strictEqual(monitorJs.indexOf("startScan"), -1);
});

test("shared CloudBase access keeps posture reads behind the event function", () => {
  assert.ok(cloudSource.indexOf("getRealtimePosture") >= 0);
  assert.ok(cloudSource.indexOf("getDailyPosture") >= 0);
  assert.strictEqual(cloudSource.indexOf("wx.cloud.database"), -1);
});
