const MAX_LIMIT = 100;

const normalizeDeviceId = (value) => {
  const deviceId = String(value || "");
  if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(deviceId)) throw new Error("invalid deviceId");
  return deviceId;
};

const normalizeLimit = (value) => Math.max(1, Math.min(MAX_LIMIT, Number(value) || 50));

const normalizeCursor = (value) => {
  if (!value) return null;
  const decoded = JSON.parse(Buffer.from(String(value), "base64").toString("utf8"));
  if (!decoded || !Number.isFinite(Number(decoded.ts)) || typeof decoded.id !== "string") {
    throw new Error("invalid cursor");
  }
  return { ts: Number(decoded.ts), id: decoded.id };
};

const encodeCursor = (item) => Buffer.from(JSON.stringify({ ts: Number(item.ts), id: String(item._id) })).toString("base64");

const resultEnvelope = (data, source, nowMs, staleAfterMs) => {
  const updatedAt = data && Number(data.ts || data.updated_at || 0);
  return {
    ok: true,
    data: data || null,
    source,
    updatedAt,
    stale: !updatedAt || Number(nowMs) - updatedAt * (updatedAt < 1e12 ? 1000 : 1) > staleAfterMs
  };
};

module.exports = { encodeCursor, normalizeCursor, normalizeDeviceId, normalizeLimit, resultEnvelope };
