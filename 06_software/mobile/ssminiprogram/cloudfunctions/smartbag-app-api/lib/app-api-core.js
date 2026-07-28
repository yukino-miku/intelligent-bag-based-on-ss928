const DEVICE_ID = "bag001";
const HISTORY_LIMIT = 100;

const success = (data) => ({ ok: true, data });
const failure = (code) => ({ ok: false, error: { code, message: code } });

const createAppApi = ({ repository }) => {
  if (!repository) {
    throw new Error("App API requires a repository");
  }
  return {
    async handle(event) {
      const action = event && event.action;
      try {
        if (action === "getLatestStatus") {
          return success({ status: await repository.getStatus(DEVICE_ID) });
        }
        if (action === "getRealtimePosture") {
          return success({ posture: await repository.getStatus(DEVICE_ID) });
        }
        if (action === "getDailyPosture") {
          const date = event && event.date;
          if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) {
            return failure("INVALID_DATE");
          }
          return success({ posture: await repository.getDailyPosture(DEVICE_ID, date) });
        }
        if (action === "getTrackPoints") {
          return success({ items: await repository.listTrackPoints(DEVICE_ID, HISTORY_LIMIT) });
        }
        if (action === "getAlarmHistory") {
          return success({ items: await repository.listAlarmHistory(DEVICE_ID, HISTORY_LIMIT) });
        }
        if (action === "saveTrafficAlert") {
          const alert = event && event.alert;
          if (!validTrafficAlert(alert)) {
            return failure("INVALID_TRAFFIC_ALERT");
          }
          return success({ eventId: await repository.upsertTrafficAlert(DEVICE_ID, alert) });
        }
        return failure("UNSUPPORTED_ACTION");
      } catch (error) {
        return failure("INTERNAL_ERROR");
      }
    }
  };
};

const validTrafficAlert = (alert) => (
  alert && typeof alert === "object" &&
  /^[A-Za-z0-9:_-]{3,128}$/.test(String(alert.event_id || alert.eventId || "")) &&
  Number.isInteger(Number(alert.level)) && Number(alert.level) >= 3 && Number(alert.level) <= 4
);

module.exports = { DEVICE_ID, HISTORY_LIMIT, createAppApi, validTrafficAlert };
