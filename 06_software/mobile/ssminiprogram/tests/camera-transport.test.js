const assert = require("assert");
const {
  SnapshotHttpTransport,
  boardBaseUrl,
  normalizeConfig
} = require("../miniprogram/utils/camera-transport");

const config = normalizeConfig({ boardHost: "192.0.2.10", videoPort: 8080, viewMode: "overlay" });
assert.strictEqual(boardBaseUrl(config), "http://192.0.2.10:8080");

const transport = new SnapshotHttpTransport(config, null);
const left = transport.snapshotUrl("left", 1);
const right = transport.snapshotUrl("right", 1);
assert(left.includes("/api/v1/camera/left/snapshot.jpg"));
assert(right.includes("/api/v1/camera/right/snapshot.jpg"));
assert.notStrictEqual(left, right);
const custom = normalizeConfig({ leftPath: "custom/left/", rightPath: "/custom/right/" });
assert.strictEqual(custom.leftPath, "/custom/left");
assert.strictEqual(custom.rightPath, "/custom/right");
assert.strictEqual(boardBaseUrl(normalizeConfig({})), "");

console.log("camera transport tests passed");
