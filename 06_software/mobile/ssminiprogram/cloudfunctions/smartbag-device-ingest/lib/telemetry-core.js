const DEVICE_ID = "bag001";

class TelemetryError extends Error {
  constructor(code, message, statusCode) {
    super(message || code);
    this.name = "TelemetryError";
    this.code = code;
    this.statusCode = statusCode || 400;
  }
}

const writeFailure = (code, error) => ({
  success: false,
  error: {
    code,
    detailCode: (error && (error.errCode || error.code || error.name)) || "UNKNOWN"
  },
  statusCode: 500
});

const getHeader = (headers, name) => {
  const wanted = name.toLowerCase();
  const key = Object.keys(headers || {}).find((item) => item.toLowerCase() === wanted);
  const value = key ? headers[key] : "";
  return Array.isArray(value) ? value[0] : value;
};

const isObject = (value) => value && typeof value === "object" && !Array.isArray(value);
const isFiniteNumber = (value) => typeof value === "number" && Number.isFinite(value);
const isTimestampMs = (value) => isFiniteNumber(value) && value >= 1000000000000;
const isRequestId = (value) => typeof value === "string" && value.trim().length > 0 && value.length <= 128;

const validateLocation = (location) => {
  if (!isObject(location)) return false;
  if (!isFiniteNumber(location.latitude) || !isFiniteNumber(location.longitude)) return false;
  if (location.latitude < -90 || location.latitude > 90) return false;
  if (location.longitude < -180 || location.longitude > 180) return false;
  if (location.accuracyM !== undefined && (!isFiniteNumber(location.accuracyM) || location.accuracyM < 0)) return false;
  return true;
};

const validateStatus = (status) => {
  if (!isObject(status)) return false;
  if (status.reportedAt !== undefined && !isTimestampMs(status.reportedAt)) return false;
  if (status.location !== undefined && !validateLocation(status.location)) return false;
  if (status.attitude !== undefined) {
    if (!isObject(status.attitude)) return false;
    if (!["rollDeg", "pitchDeg", "yawDeg"].every((key) => isFiniteNumber(status.attitude[key]))) return false;
  }
  if (status.posture_status !== undefined && !["good", "bad"].includes(status.posture_status)) return false;
  if (status.is_wearing !== undefined && typeof status.is_wearing !== "boolean") return false;
  if (status.reminder_active !== undefined && typeof status.reminder_active !== "boolean") return false;
  if (status.reminder_type !== undefined && status.reminder_type !== "hunch_vibration_voice") return false;
  if (status.reminder_reported_at !== undefined && !isTimestampMs(status.reminder_reported_at)) return false;
  if (status.chip_temperature_c !== undefined) {
    if (!isObject(status.chip_temperature_c)) return false;
    if (!["tsensor0", "tsensor1", "tsensor2"].every((key) => isFiniteNumber(status.chip_temperature_c[key]))) return false;
  }
  return true;
};

const validateTrackPoint = (point) => (
  isObject(point) &&
  isRequestId(point.requestId) &&
  isTimestampMs(point.reportedAt) &&
  validateLocation(point.location)
);

const validateAlarm = (alarm) => (
  isObject(alarm) &&
  isRequestId(alarm.requestId) &&
  isTimestampMs(alarm.reportedAt) &&
  ["fall_detected", "posture_hunch_reminder"].includes(alarm.alarmType) &&
  Number.isInteger(alarm.riskLevel) &&
  alarm.riskLevel >= 1 &&
  alarm.riskLevel <= 4 &&
  (alarm.location === undefined || validateLocation(alarm.location))
);

const validatePostureDaily = (daily) => {
  if (!isObject(daily)) return false;
  if (daily.device_id !== undefined && daily.device_id !== DEVICE_ID) return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(daily.date || "")) return false;
  if (!isTimestampMs(daily.updated_at)) return false;
  const wearing = daily.wearing_seconds;
  const good = daily.good_seconds;
  const bad = daily.bad_seconds;
  if (![wearing, good, bad].every((value) => isFiniteNumber(value) && value >= 0)) return false;
  return good + bad <= wearing + 0.001;
};

const validatePayload = (payload) => {
  if (!isObject(payload)) return false;
  if (payload.version !== undefined && payload.version !== 1) return false;
  if (payload.deviceId !== undefined && payload.deviceId !== DEVICE_ID) return false;
  if (!isRequestId(payload.requestId) || !isTimestampMs(payload.reportedAt)) return false;
  if (!validateStatus(payload.status || {})) return false;
  if (payload.trackPoints !== undefined && !Array.isArray(payload.trackPoints)) return false;
  if (payload.alarms !== undefined && !Array.isArray(payload.alarms)) return false;
  const trackPoints = payload.trackPoints || [];
  const alarms = payload.alarms || [];
  if (trackPoints.length > 100 || alarms.length > 100) return false;
  if (!trackPoints.every(validateTrackPoint) || !alarms.every(validateAlarm)) return false;
  if (payload.postureDaily !== undefined && !validatePostureDaily(payload.postureDaily)) return false;
  return true;
};

const createTelemetryProcessor = ({ store, uploadToken, now }) => {
  if (!store || typeof store.mergeStatus !== "function") {
    throw new Error("Telemetry processor requires a store");
  }
  return {
    async process({ headers, rawBody }) {
      if (!uploadToken || getHeader(headers, "x-upload-token") !== uploadToken) {
        return { success: false, error: { code: "INVALID_UPLOAD_TOKEN" }, statusCode: 401 };
      }
      let payload;
      try {
        payload = JSON.parse(Buffer.from(rawBody).toString("utf8"));
      } catch (error) {
        return { success: false, error: { code: "INVALID_JSON" }, statusCode: 400 };
      }
      if (!validatePayload(payload)) {
        return { success: false, error: { code: "INVALID_TELEMETRY" }, statusCode: 400 };
      }
      const receivedAt = typeof now === "function" ? now() : new Date().toISOString();
      try {
        await store.mergeStatus(Object.assign({}, payload.status || {}, {
          _id: DEVICE_ID,
          deviceId: DEVICE_ID,
          receivedAt
        }));
      } catch (error) {
        return writeFailure("STATUS_WRITE_FAILED", error);
      }
      const trackPoints = payload.trackPoints || [];
      for (let index = 0; index < trackPoints.length; index += 1) {
        try {
          await store.insertTrackPoint(Object.assign({}, trackPoints[index], { deviceId: DEVICE_ID, receivedAt }));
        } catch (error) {
          return writeFailure("TRACK_WRITE_FAILED", error);
        }
      }
      if (payload.postureDaily !== undefined) {
        try {
          const daily = Object.assign({}, payload.postureDaily, {
            _id: `${DEVICE_ID}_${payload.postureDaily.date}`,
            device_id: DEVICE_ID,
            receivedAt
          });
          await store.setPostureDaily(daily);
        } catch (error) {
          return writeFailure("POSTURE_DAILY_WRITE_FAILED", error);
        }
      }
      const alarms = payload.alarms || [];
      for (let index = 0; index < alarms.length; index += 1) {
        try {
          await store.insertAlarm(Object.assign({}, alarms[index], { deviceId: DEVICE_ID, receivedAt }));
        } catch (error) {
          return writeFailure("ALARM_WRITE_FAILED", error);
        }
      }
      return { success: true };
    }
  };
};

module.exports = {
  DEVICE_ID,
  TelemetryError,
  createTelemetryProcessor,
  getHeader,
  validatePayload
};
