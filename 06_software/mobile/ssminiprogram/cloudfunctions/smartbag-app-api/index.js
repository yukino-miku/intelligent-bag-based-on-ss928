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
  }
};

const api = createAppApi({ repository });

exports.main = async (event, context) => api.handle(event, context);
