const crypto = require("crypto");

const sha256Hex = (value) => crypto.createHash("sha256").update(value).digest("hex");

const safeEqualHex = (left, right) => {
  if (!/^[0-9a-f]{64}$/i.test(String(left || "")) || !/^[0-9a-f]{64}$/i.test(String(right || ""))) {
    return false;
  }
  return crypto.timingSafeEqual(Buffer.from(left, "hex"), Buffer.from(right, "hex"));
};

const parseSecrets = (text) => {
  const value = JSON.parse(String(text || "{}"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("SMARTBAG_DEVICE_SECRETS_JSON must be an object");
  }
  return value;
};

const verifyDeviceRequest = (request, options) => {
  const headers = request.headers || {};
  const getHeader = (name) => headers[name] || headers[name.toLowerCase()] || headers[name.toUpperCase()];
  const deviceId = String(getHeader("X-SmartBag-Device") || "");
  const timestamp = Number(getHeader("X-SmartBag-Timestamp"));
  const nonce = String(getHeader("X-SmartBag-Nonce") || "");
  const bodySha = String(getHeader("X-SmartBag-Body-SHA256") || "");
  const signature = String(getHeader("X-SmartBag-Signature") || "");
  const bodyBuffer = Buffer.isBuffer(request.body) ? request.body : Buffer.from(String(request.body || ""), "utf8");
  if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(deviceId)) throw new Error("invalid device id");
  if (!/^[A-Fa-f0-9]{16,128}$/.test(nonce)) throw new Error("invalid nonce");
  if (bodyBuffer.length > Number(options.maxBodyBytes || 262144)) throw new Error("payload too large");
  if (!Number.isFinite(timestamp) || Math.abs(Number(options.nowSeconds()) - timestamp) > Number(options.maxAgeSeconds || 300)) {
    throw new Error("expired timestamp");
  }
  const actualBodySha = sha256Hex(bodyBuffer);
  if (!safeEqualHex(bodySha, actualBodySha)) throw new Error("body hash mismatch");
  const secret = options.secrets[deviceId];
  if (!secret) throw new Error("unknown device");
  const canonical = [deviceId, String(timestamp), nonce, bodySha].join("\n");
  const expected = crypto.createHmac("sha256", String(secret)).update(canonical).digest("hex");
  if (!safeEqualHex(signature, expected)) throw new Error("invalid signature");
  return { deviceId, timestamp, nonce, bodyBuffer, nonceId: sha256Hex(deviceId + ":" + nonce) };
};

module.exports = { parseSecrets, safeEqualHex, sha256Hex, verifyDeviceRequest };
