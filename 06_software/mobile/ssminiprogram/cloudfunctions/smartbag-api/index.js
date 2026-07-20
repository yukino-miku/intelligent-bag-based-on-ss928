const cloud = require("wx-server-sdk");
const { parseSecrets, sha256Hex, verifyDeviceRequest } = require("./security");
const { encodeCursor, normalizeCursor, normalizeDeviceId, normalizeLimit, resultEnvelope } = require("./api-core");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const command = db.command;

const assertBinding = async (openid, deviceId) => {
  const result = await db.collection("device_bindings").where({ openid, deviceId, active: true }).limit(1).get();
  if (!result.data || !result.data.length) throw new Error("device is not bound to current user");
};

const queryPage = async (collection, deviceId, event) => {
  const limit = normalizeLimit(event.limit);
  const cursor = normalizeCursor(event.cursor);
  const where = { device_id: deviceId };
  if (cursor) where.ts = command.lt(cursor.ts);
  const result = await db.collection(collection).where(where).orderBy("ts", "desc").limit(limit).get();
  const items = result.data || [];
  return { items, cursor: items.length === limit ? encodeCursor(items[items.length - 1]) : null, limit };
};

const handleAppCall = async (event) => {
  const context = cloud.getWXContext();
  const openid = context.OPENID;
  if (!openid) throw new Error("missing trusted OPENID");
  const deviceId = normalizeDeviceId(event.deviceId);
  await assertBinding(openid, deviceId);
  const now = Date.now();
  if (event.action === "getLatestStatus") {
    const result = await db.collection("device_status").where({ device_id: deviceId }).orderBy("ts", "desc").limit(1).get();
    return resultEnvelope(result.data[0], "cloud", now, 15000);
  }
  if (event.action === "getRealtimePosture") {
    const result = await db.collection("device_status").where({ device_id: deviceId, kind: "imu" }).orderBy("ts", "desc").limit(1).get();
    return resultEnvelope(result.data[0], "cloud", now, 15000);
  }
  if (event.action === "getDailyPosture") {
    return { ok: true, source: "cloud", data: (await db.collection("posture_daily_stats").where({ device_id: deviceId, date: String(event.date || "") }).limit(1).get()).data[0] || null };
  }
  if (event.action === "getTrackPoints") return Object.assign({ ok: true, source: "cloud" }, await queryPage("track_points", deviceId, event));
  if (event.action === "getAlarmHistory") return Object.assign({ ok: true, source: "cloud" }, await queryPage("alarm_history", deviceId, event));
  throw new Error("unsupported action");
};

const handleTelemetry = async (event) => {
  const bodyText = event.isBase64Encoded ? Buffer.from(event.body || "", "base64") : Buffer.from(String(event.body || ""), "utf8");
  const verified = verifyDeviceRequest(
    { headers: event.headers || {}, body: bodyText },
    { secrets: parseSecrets(process.env.SMARTBAG_DEVICE_SECRETS_JSON), nowSeconds: () => Math.floor(Date.now() / 1000), maxAgeSeconds: 300, maxBodyBytes: 262144 }
  );
  const payload = JSON.parse(bodyText.toString("utf8"));
  if (payload.device_id !== verified.deviceId || !Array.isArray(payload.events) || payload.events.length > 100) throw new Error("invalid telemetry batch");
  await db.collection("device_nonces").add({ data: { _id: verified.nonceId, device_id: verified.deviceId, nonce_sha256: sha256Hex(verified.nonce), ts: verified.timestamp, expires_at: verified.timestamp + 600 } });
  for (const item of payload.events) {
    const kind = String(item.kind || "status");
    const record = { device_id: verified.deviceId, kind, ts: Number(item.ts || verified.timestamp), payload: item.payload || {} };
    const collection = kind === "alert" ? "alarm_history" : kind === "track" ? "track_points" : "device_status";
    await db.collection(collection).add({ data: record });
  }
  return { statusCode: 200, headers: { "content-type": "application/json" }, body: JSON.stringify({ ok: true, accepted: payload.events.length }) };
};

exports.main = async (event) => {
  try {
    return event && event.headers ? await handleTelemetry(event) : await handleAppCall(event || {});
  } catch (error) {
    const message = String(error && error.message || error);
    if (event && event.headers) return { statusCode: 403, headers: { "content-type": "application/json" }, body: JSON.stringify({ ok: false, error: message }) };
    return { ok: false, error: message };
  }
};
