const assert = require("assert");
const crypto = require("crypto");
const path = require("path");
const security = require(path.join(__dirname, "../cloudfunctions/smartbag-api/security"));
const api = require(path.join(__dirname, "../cloudfunctions/smartbag-api/api-core"));

const body = Buffer.from(JSON.stringify({ device_id: "dev-1", events: [] }));
const bodySha = security.sha256Hex(body);
const timestamp = 1000;
const nonce = "0011223344556677";
const canonical = ["dev-1", timestamp, nonce, bodySha].join("\n");
const signature = crypto.createHmac("sha256", "test-secret").update(canonical).digest("hex");
const headers = {
  "X-SmartBag-Device": "dev-1",
  "X-SmartBag-Timestamp": String(timestamp),
  "X-SmartBag-Nonce": nonce,
  "X-SmartBag-Body-SHA256": bodySha,
  "X-SmartBag-Signature": signature
};

assert.strictEqual(security.verifyDeviceRequest({ headers, body }, { secrets: { "dev-1": "test-secret" }, nowSeconds: () => 1001 }).deviceId, "dev-1");
assert.throws(() => security.verifyDeviceRequest({ headers: Object.assign({}, headers, { "X-SmartBag-Signature": "0".repeat(64) }), body }, { secrets: { "dev-1": "test-secret" }, nowSeconds: () => 1001 }), /signature/);
assert.throws(() => security.verifyDeviceRequest({ headers, body }, { secrets: { "dev-1": "test-secret" }, nowSeconds: () => 1400 }), /expired/);
assert.strictEqual(api.normalizeLimit(1000), 100);
assert.strictEqual(api.normalizeDeviceId("bag-02"), "bag-02");
assert.throws(() => api.normalizeDeviceId(""), /deviceId/);
const cursor = api.encodeCursor({ ts: 123, _id: "abc" });
assert.deepStrictEqual(api.normalizeCursor(cursor), { ts: 123, id: "abc" });

console.log("cloud security tests passed");
