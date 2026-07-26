const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "miniprogram");
const homeJs = fs.readFileSync(path.join(root, "pages", "home", "index.js"), "utf8");
const homeWxml = fs.readFileSync(path.join(root, "pages", "home", "index.wxml"), "utf8");
const app = JSON.parse(fs.readFileSync(path.join(root, "app.json"), "utf8"));

[
  "/pages/cameras/index",
  "/pages/monitor/index",
  "/pages/tracks/index",
  "/pages/index/index",
  "/pages/alarms/index",
  "/pages/posture-analysis/index",
  "/pages/remote/index"
].forEach((route) => assert.ok(homeJs.indexOf(route) >= 0, route + " is missing from home"));

[
  "pages/cameras/index",
  "pages/monitor/index",
  "pages/tracks/index",
  "pages/index/index",
  "pages/alarms/index",
  "pages/posture-analysis/index",
  "pages/posture-live/index",
  "pages/remote/index"
].forEach((route) => assert.ok(app.pages.includes(route), route + " is missing from app.json"));

assert.ok(homeWxml.indexOf("{{resourceText}}") >= 0);
assert.strictEqual(homeJs.indexOf("pages/placeholder"), -1);
assert.strictEqual(homeJs.indexOf("pages/example"), -1);
console.log("ok - target home keeps existing pages and adds integrated CloudBase/BLE routes");
