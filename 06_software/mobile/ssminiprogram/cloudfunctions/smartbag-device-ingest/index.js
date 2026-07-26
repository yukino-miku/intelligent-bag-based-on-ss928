const http = require("http");
const tcb = require("@cloudbase/node-sdk");
const telemetry = require("./lib/telemetry-core");

const CLOUDBASE_ENV_ID = process.env.CLOUDBASE_ENV_ID || "";
if (!CLOUDBASE_ENV_ID) {
  throw new Error("CLOUDBASE_ENV_ID must be configured for smartbag-device-ingest");
}

const app = tcb.init({ env: CLOUDBASE_ENV_ID });
const db = app.database();
const MAX_BODY_BYTES = 64 * 1024;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Upload-Token"
};

const sendJson = (res, statusCode, body) => {
  res.writeHead(statusCode, Object.assign({ "Content-Type": "application/json; charset=utf-8" }, corsHeaders));
  res.end(JSON.stringify(body));
};

const readRawBody = (req) => new Promise((resolve, reject) => {
  const chunks = [];
  let size = 0;
  let rejected = false;
  req.on("data", (chunk) => {
    size += chunk.length;
    if (size > MAX_BODY_BYTES && !rejected) {
      rejected = true;
      reject(new telemetry.TelemetryError("PAYLOAD_TOO_LARGE", "PAYLOAD_TOO_LARGE", 413));
      req.resume();
      return;
    }
    if (!rejected) {
      chunks.push(chunk);
    }
  });
  req.on("end", () => {
    if (!rejected) {
      resolve(Buffer.concat(chunks));
    }
  });
  req.on("error", reject);
});

const createCloudStore = (database) => ({
  async mergeStatus(document) {
    const documentId = document._id;
    const data = Object.assign({}, document);
    delete data._id;
    const reference = database.collection("device_status").doc(documentId);
    try {
      await reference.update(data);
    } catch (error) {
      const code = error && (error.errCode || error.code);
      if (code !== -502005 && code !== "DATABASE_DOCUMENT_NOT_EXIST") throw error;
      await reference.set(data);
    }
  },
  async insertTrackPoint(document) {
    await database.collection("track_points").add(document);
  },
  async insertAlarm(document) {
    await database.collection("alarm_history").add(document);
  },
  async setPostureDaily(document) {
    const documentId = document._id;
    const data = Object.assign({}, document);
    delete data._id;
    await database.collection("posture_daily_stats").doc(documentId).set(data);
  }
});

const createServer = ({ processor }) => http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, corsHeaders);
    res.end();
    return;
  }
  const url = new URL(req.url || "/", "http://127.0.0.1");
  if (url.pathname !== "/v1/device/telemetry") {
    sendJson(res, 404, { ok: false, error: { code: "NOT_FOUND", message: "NOT_FOUND" } });
    return;
  }
  if (req.method !== "POST") {
    sendJson(res, 405, { ok: false, error: { code: "METHOD_NOT_ALLOWED", message: "METHOD_NOT_ALLOWED" } });
    return;
  }
  try {
    const rawBody = await readRawBody(req);
    const result = await processor.process({ headers: req.headers, rawBody });
    sendJson(res, result.success ? 200 : result.statusCode || 400, result.success ? result : { success: false, error: result.error });
  } catch (error) {
    const statusCode = error && error.statusCode ? error.statusCode : 500;
    const code = error && error.code ? error.code : "INTERNAL_ERROR";
    console.error("Telemetry request failed", {
      code,
      message: error && error.message ? error.message : "",
      stack: error && error.stack ? error.stack : ""
    });
    sendJson(res, statusCode, { success: false, error: { code } });
  }
});

const processor = telemetry.createTelemetryProcessor({
  store: createCloudStore(db),
  uploadToken: process.env.SMARTBAG_UPLOAD_TOKEN || ""
});

if (require.main === module) {
  createServer({ processor }).listen(9000);
}

module.exports = { createCloudStore, createServer, readRawBody };
