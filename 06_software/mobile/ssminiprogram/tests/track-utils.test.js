const assert = require("assert");
const track = require("../miniprogram/utils/track-utils");

const tests = [];

const test = (name, fn) => {
  tests.push({ name, fn });
};

const approx = (actual, expected, tolerance) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, actual + " != " + expected);
};

test("appendBleText keeps partial frames and emits complete JSON lines", () => {
  const first = track.appendBleText("", "{\"typ\":\"tl\"");
  assert.deepStrictEqual(first.lines, []);
  assert.strictEqual(first.buffer, "{\"typ\":\"tl\"");

  const second = track.appendBleText(first.buffer, ",\"items\":[]}\n{\"typ\":\"loc\"}\npart");
  assert.deepStrictEqual(second.lines, ["{\"typ\":\"tl\",\"items\":[]}", "{\"typ\":\"loc\"}"]);
  assert.strictEqual(second.buffer, "part");
});

test("wgs84ToGcj02 converts mainland coordinates and leaves outside-China coordinates unchanged", () => {
  const shanghai = track.wgs84ToGcj02(121.4737, 31.23042);
  assert.ok(Math.abs(shanghai.longitude - 121.4737) > 0.001);
  assert.ok(Math.abs(shanghai.latitude - 31.23042) > 0.001);

  const sanFrancisco = track.wgs84ToGcj02(-122.4194, 37.7749);
  approx(sanFrancisco.longitude, -122.4194, 0.0000001);
  approx(sanFrancisco.latitude, 37.7749, 0.0000001);
});

test("normalizeTrackPoint accepts compact BLE arrays and rejects invalid fixes", () => {
  const point = track.normalizeTrackPoint([1780926600.123, 31.23042, 121.4737, 6.2, 0.8, 92.0]);
  assert.strictEqual(point.time, 1780926600.123);
  assert.strictEqual(point.rawLatitude, 31.23042);
  assert.strictEqual(point.rawLongitude, 121.4737);
  assert.strictEqual(point.accuracy, 6.2);
  assert.strictEqual(point.speed, 0.8);
  assert.strictEqual(point.course, 92.0);
  assert.notStrictEqual(point.latitude, point.rawLatitude);
  assert.notStrictEqual(point.longitude, point.rawLongitude);

  assert.strictEqual(track.normalizeTrackPoint({ t: 1, lat: 91, lon: 121, fix: 1 }), null);
  assert.strictEqual(track.normalizeTrackPoint({ t: 1, lat: 31, lon: 181, fix: 1 }), null);
  assert.strictEqual(track.normalizeTrackPoint({ t: 1, lat: 31, lon: 121, fix: 0 }), null);
});

test("mergeTrackChunk appends valid points, deduplicates, and exposes next offset", () => {
  const first = track.mergeTrackChunk([], {
    typ: "trk",
    i: 0,
    o: 0,
    next: 2,
    done: 0,
    pts: [
      [1, 31.23042, 121.4737, 6, 0.8, 92],
      [2, 31.23043, 121.4738, 6, 0.9, 94],
      [2, 31.23043, 121.4738, 6, 0.9, 94],
      [3, 91, 121.4739, 6, 0.9, 94]
    ]
  });

  assert.strictEqual(first.points.length, 2);
  assert.strictEqual(first.nextOffset, 2);
  assert.strictEqual(first.done, false);

  const second = track.mergeTrackChunk(first.points, {
    typ: "trk",
    i: 0,
    o: 2,
    done: 1,
    pts: [
      [2, 31.23043, 121.4738, 6, 0.9, 94],
      [4, 31.2305, 121.4739, 5, 1.1, 96]
    ]
  });

  assert.strictEqual(second.points.length, 3);
  assert.strictEqual(second.nextOffset, null);
  assert.strictEqual(second.done, true);
});

test("downsampleTrackPoints keeps endpoints and map overlays use GCJ-02 points", () => {
  const points = [];
  for (let i = 0; i < 101; i += 1) {
    points.push(track.normalizeTrackPoint([1000 + i, 31 + i * 0.0001, 121 + i * 0.0001, 5, 1, 90]));
  }

  const sampled = track.downsampleTrackPoints(points, 20);
  assert.ok(sampled.length <= 20);
  assert.strictEqual(sampled[0].time, points[0].time);
  assert.strictEqual(sampled[sampled.length - 1].time, points[points.length - 1].time);

  const polyline = track.buildPolyline(sampled);
  assert.strictEqual(polyline.length, 1);
  assert.strictEqual(polyline[0].points.length, sampled.length);
  assert.ok(polyline[0].points[0].latitude !== points[0].rawLatitude);

  const markers = track.buildMarkers(sampled);
  assert.strictEqual(markers.length, 3);
  assert.strictEqual(markers[0].id, 1);
  assert.strictEqual(markers[1].id, 2);
  assert.strictEqual(markers[2].id, 3);
});

let failed = 0;

for (let i = 0; i < tests.length; i += 1) {
  const item = tests[i];
  try {
    item.fn();
    console.log("ok - " + item.name);
  } catch (err) {
    failed += 1;
    console.error("not ok - " + item.name);
    console.error(err && err.stack ? err.stack : err);
  }
}

if (failed) {
  process.exit(1);
}
