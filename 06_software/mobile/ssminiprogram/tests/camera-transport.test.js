const assert = require("assert");
const fs = require("fs");
const path = require("path");
const {
  SnapshotHttpTransport,
  boardBaseUrl,
  normalizeConfig,
  normalizeCameraStatus
} = require("../miniprogram/utils/camera-transport");

const config = normalizeConfig({ boardHost: "192.0.2.10", videoPort: 8080, viewMode: "overlay" });
assert.strictEqual(boardBaseUrl(config), "http://192.0.2.10:8080");

const transport = new SnapshotHttpTransport(config, null);
const left = transport.snapshotUrl("left", 1);
const right = transport.snapshotUrl("right", 1);
assert(left.includes("/api/v1/camera/left/snapshot.jpg"));
assert(right.includes("/api/v1/camera/right/snapshot.jpg"));
assert(left.includes("view=overlay"));
assert.notStrictEqual(left, right);

const custom = normalizeConfig({ leftPath: "custom/left/", rightPath: "/custom/right/" });
assert.strictEqual(custom.leftPath, "/custom/left");
assert.strictEqual(custom.rightPath, "/custom/right");
assert.strictEqual(boardBaseUrl(normalizeConfig({})), "");

const cached = normalizeCameraStatus({
  online: true,
  active: false,
  frame_state: "cached",
  effective_fps: 4.1,
  end_to_end_observation_gap_ms: 1200
});
assert.strictEqual(cached.statusText, "缓存帧");
assert.strictEqual(cached.captureFps, 4.1);
assert.strictEqual(cached.observationGapMs, 1200);
assert.strictEqual(normalizeCameraStatus({ online: true, active: true }).statusText, "正在采集");
assert.strictEqual(normalizeCameraStatus({ online: false }).frameState, "offline");

let aborted = false;
const abortable = new SnapshotHttpTransport(config, {
  request() {
    return { abort() { aborted = true; } };
  }
}).status("left");
assert.strictEqual(typeof abortable.abort, "function");
abortable.abort();
assert.strictEqual(aborted, true);

const pageSource = fs.readFileSync(
  path.join(__dirname, "../miniprogram/pages/cameras/index.js"),
  "utf8"
);
assert(!pageSource.includes("setInterval("));
assert(!pageSource.includes("wx.previewImage"));
assert(pageSource.includes("snapshotInFlight"));
assert(pageSource.includes("focusSide"));
assert(pageSource.includes("abort()"));

console.log("camera transport tests passed");
