const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "miniprogram");
const read = (parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const remoteJs = read(["pages", "remote", "index.js"]);
const remoteWxml = read(["pages", "remote", "index.wxml"]);
const appJson = read(["app.json"]);

assert.ok(appJson.indexOf('"pages/remote/index"') >= 0);
assert.ok(remoteJs.indexOf('const TARGET_NAME = "SS928-SmartBag"') >= 0);
assert.ok(remoteJs.indexOf("if (name !== TARGET_NAME) continue;") >= 0, "remote page must reject non-SmartBag NUS devices");
[
  "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
  "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
  "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
].forEach((uuid) => assert.ok(remoteJs.indexOf(uuid) >= 0));
assert.strictEqual(remoteJs.indexOf("6E400101-B5A3-F393-E0A9-E50E24DCCA9E"), -1, "remote must not use the retired source-only NUS service");
assert.ok(remoteJs.indexOf("if (!this.data.connected") >= 0);
[
  "AL L1", "AL L2", "AL L3", "AL L4",
  "AL R1", "AL R2", "AL R3", "AL R4", "AL CLEAR", "AL FALL"
].forEach((command) => assert.ok(remoteWxml.indexOf(command) >= 0, command + " control is missing"));

console.log("ok - SmartBag BLE remote page contract");
