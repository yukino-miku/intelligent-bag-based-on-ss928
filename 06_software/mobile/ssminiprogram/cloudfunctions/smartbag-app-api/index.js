const cloud = require("wx-server-sdk");
const { createAppApi } = require("./lib/app-api-core");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();

const repository = {
  async getStatus(deviceId) {
    try {
      const result = await db.collection("device_status").doc(deviceId).get();
      return result && result.data ? result.data : null;
    } catch (error) {
      return null;
    }
  },
  async getDailyPosture(deviceId, date) {
    try {
      const result = await db.collection("posture_daily_stats").where({ device_id: deviceId, date }).limit(1).get();
      return result && result.data && result.data[0] ? result.data[0] : null;
    } catch (error) {
      return null;
    }
  },
  async listTrackPoints(deviceId, limit) {
    const result = await db.collection("track_points").where({ deviceId }).orderBy("receivedAt", "desc").limit(limit).get();
    return result && result.data ? result.data : [];
  },
  async listAlarmHistory(deviceId, limit) {
    const result = await db.collection("alarm_history").where({ deviceId }).orderBy("receivedAt", "desc").limit(limit).get();
    return result && result.data ? result.data : [];
  },
  async upsertTrafficAlert(deviceId, alert) {
    const eventId = String(alert.event_id || alert.eventId);
    const documentId = (deviceId + "_" + eventId).replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 128);
    await db.collection("traffic_alerts").doc(documentId).set({
      deviceId,
      eventId,
      alert,
      receivedAt: db.serverDate()
    });
    return eventId;
  }
};

const api = createAppApi({ repository });

exports.main = async (event, context) => api.handle(event, context);
