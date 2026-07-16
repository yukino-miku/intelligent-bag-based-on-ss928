const PI = 3.1415926535897932384626;
const A = 6378245.0;
const EE = 0.00669342162296594323;

const isFiniteNumber = (value) => {
  const num = Number(value);
  return Number.isFinite(num);
};

const toNumber = (value, fallback) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const appendBleText = (buffer, text) => {
  const merged = String(buffer || "") + String(text || "");
  const parts = merged.split("\n");
  const lines = [];
  for (let i = 0; i < parts.length - 1; i += 1) {
    const line = parts[i].replace(/\r$/, "").trim();
    if (line) {
      lines.push(line);
    }
  }
  return {
    lines,
    buffer: parts[parts.length - 1] || ""
  };
};

const isValidCoordinate = (latitude, longitude) => (
  isFiniteNumber(latitude) &&
  isFiniteNumber(longitude) &&
  Number(latitude) >= -90 &&
  Number(latitude) <= 90 &&
  Number(longitude) >= -180 &&
  Number(longitude) <= 180
);

const outOfChina = (longitude, latitude) => (
  longitude < 72.004 ||
  longitude > 137.8347 ||
  latitude < 0.8293 ||
  latitude > 55.8271
);

const transformLat = (x, y) => {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(y * PI) + 40.0 * Math.sin(y / 3.0 * PI)) * 2.0 / 3.0;
  ret += (160.0 * Math.sin(y / 12.0 * PI) + 320 * Math.sin(y * PI / 30.0)) * 2.0 / 3.0;
  return ret;
};

const transformLon = (x, y) => {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(x * PI) + 40.0 * Math.sin(x / 3.0 * PI)) * 2.0 / 3.0;
  ret += (150.0 * Math.sin(x / 12.0 * PI) + 300.0 * Math.sin(x / 30.0 * PI)) * 2.0 / 3.0;
  return ret;
};

const wgs84ToGcj02 = (longitude, latitude) => {
  const lon = Number(longitude);
  const lat = Number(latitude);
  if (!isValidCoordinate(lat, lon) || outOfChina(lon, lat)) {
    return { longitude: lon, latitude: lat };
  }

  let dLat = transformLat(lon - 105.0, lat - 35.0);
  let dLon = transformLon(lon - 105.0, lat - 35.0);
  const radLat = lat / 180.0 * PI;
  let magic = Math.sin(radLat);
  magic = 1 - EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / ((A * (1 - EE)) / (magic * sqrtMagic) * PI);
  dLon = (dLon * 180.0) / (A / sqrtMagic * Math.cos(radLat) * PI);
  return {
    longitude: lon + dLon,
    latitude: lat + dLat
  };
};

const normalizeTrackPoint = (raw) => {
  let time;
  let latitude;
  let longitude;
  let accuracy;
  let speed;
  let course;
  let altitude;
  let fix;
  let satellites;
  let source;
  let coordSystem = "wgs84";

  if (Array.isArray(raw)) {
    time = toNumber(raw[0], 0);
    latitude = toNumber(raw[1], NaN);
    longitude = toNumber(raw[2], NaN);
    accuracy = toNumber(raw[3], null);
    speed = toNumber(raw[4], null);
    course = toNumber(raw[5], null);
    fix = 1;
  } else if (raw && typeof raw === "object") {
    time = toNumber(raw.t, 0);
    latitude = toNumber(raw.lat, NaN);
    longitude = toNumber(raw.lon, NaN);
    accuracy = toNumber(raw.acc, null);
    altitude = toNumber(raw.alt, null);
    speed = toNumber(raw.spd, null);
    course = toNumber(raw.course, null);
    fix = typeof raw.fix === "undefined" ? 1 : toNumber(raw.fix, 0);
    satellites = toNumber(raw.sat, null);
    source = raw.src || "";
    coordSystem = String(raw.cs || "wgs84").toLowerCase();
  } else {
    return null;
  }

  if (!isValidCoordinate(latitude, longitude) || Number(fix) <= 0) {
    return null;
  }

  const converted = coordSystem === "gcj02" ?
    { latitude, longitude } :
    wgs84ToGcj02(longitude, latitude);

  return {
    time,
    rawLatitude: latitude,
    rawLongitude: longitude,
    latitude: converted.latitude,
    longitude: converted.longitude,
    sourceCoordSystem: coordSystem,
    accuracy,
    altitude,
    speed,
    course,
    fix,
    satellites,
    source
  };
};

const pointKey = (point) => (
  String(point.time) + ":" +
  point.rawLatitude.toFixed(7) + ":" +
  point.rawLongitude.toFixed(7)
);

const mergeTrackChunk = (currentPoints, frame) => {
  const points = Array.isArray(currentPoints) ? currentPoints.slice() : [];
  const seen = {};
  for (let i = 0; i < points.length; i += 1) {
    seen[pointKey(points[i])] = true;
  }

  const rawPoints = frame && Array.isArray(frame.pts) ? frame.pts : [];
  for (let i = 0; i < rawPoints.length; i += 1) {
    const point = normalizeTrackPoint(rawPoints[i]);
    if (!point) {
      continue;
    }
    const key = pointKey(point);
    if (seen[key]) {
      continue;
    }
    seen[key] = true;
    points.push(point);
  }

  return {
    points,
    nextOffset: frame && typeof frame.next === "number" ? frame.next : null,
    done: !!(frame && (frame.done === true || Number(frame.done) === 1))
  };
};

const downsampleTrackPoints = (points, maxPoints) => {
  const list = Array.isArray(points) ? points.filter((point) => !!point) : [];
  const limit = Math.max(2, Number(maxPoints) || 2);
  if (list.length <= limit) {
    return list.slice();
  }

  const sampled = [list[0]];
  const lastIndex = list.length - 1;
  for (let i = 1; i < limit - 1; i += 1) {
    const index = Math.round(i * lastIndex / (limit - 1));
    const point = list[index];
    if (point && point !== sampled[sampled.length - 1]) {
      sampled.push(point);
    }
  }
  if (sampled[sampled.length - 1] !== list[lastIndex]) {
    sampled.push(list[lastIndex]);
  }
  return sampled;
};

const toMapPoint = (point) => ({
  latitude: point.latitude,
  longitude: point.longitude
});

const buildPolyline = (points) => {
  const list = Array.isArray(points) ? points.filter((point) => point && isValidCoordinate(point.latitude, point.longitude)) : [];
  if (list.length < 2) {
    return [];
  }
  return [{
    points: list.map(toMapPoint),
    color: "#2F80ED",
    width: 6,
    arrowLine: true,
    borderColor: "#FFFFFF",
    borderWidth: 2
  }];
};

const buildMarker = (id, point, title, color) => ({
  id,
  latitude: point.latitude,
  longitude: point.longitude,
  title,
  width: 26,
  height: 26,
  callout: {
    content: title,
    color: "#17212B",
    fontSize: 12,
    borderRadius: 4,
    bgColor: "#FFFFFF",
    padding: 6,
    display: "BYCLICK"
  },
  label: {
    content: title,
    color,
    fontSize: 12,
    anchorX: -12,
    anchorY: -32
  }
});

const buildMarkers = (points) => {
  const list = Array.isArray(points) ? points.filter((point) => point && isValidCoordinate(point.latitude, point.longitude)) : [];
  if (!list.length) {
    return [];
  }
  if (list.length === 1) {
    return [buildMarker(3, list[0], "Live", "#2F80ED")];
  }
  return [
    buildMarker(1, list[0], "Start", "#18A058"),
    buildMarker(2, list[list.length - 1], "End", "#D64545"),
    buildMarker(3, list[list.length - 1], "Live", "#2F80ED")
  ];
};

const formatTrackTime = (seconds) => {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) {
    return "--";
  }
  const date = new Date(value > 100000000000 ? value : value * 1000);
  const pad = (num) => ("0" + num).slice(-2);
  return (
    pad(date.getMonth() + 1) + "/" +
    pad(date.getDate()) + " " +
    pad(date.getHours()) + ":" +
    pad(date.getMinutes())
  );
};

module.exports = {
  appendBleText,
  buildMarkers,
  buildPolyline,
  downsampleTrackPoints,
  formatTrackTime,
  isValidCoordinate,
  mergeTrackChunk,
  normalizeTrackPoint,
  outOfChina,
  wgs84ToGcj02
};
