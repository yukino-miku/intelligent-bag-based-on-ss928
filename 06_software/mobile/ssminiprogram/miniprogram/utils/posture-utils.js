const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const toFiniteNumber = (value, fallback) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const toTimestampMs = (value) => {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return value < 100000000000 ? value * 1000 : value;
  if (typeof value === "string") {
    // CloudBase serializes Date values as ISO-8601 strings.  Keep the ISO
    // separators intact; replacing them for the iOS local-date workaround
    // makes strings with `T`/`Z` invalid and falsely marks the device offline.
    const timestamp = Date.parse(value.includes("T") ? value : value.replace(/-/g, "/"));
    return Number.isFinite(timestamp) ? timestamp : 0;
  }
  if (value && typeof value.getTime === "function") return value.getTime();
  return 0;
};
const formatClock = (timestampMs) => {
  if (!timestampMs) return "--:--:--";
  const date = new Date(timestampMs);
  const pad = (value) => ("0" + value).slice(-2);
  return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
};
const formatDuration = (seconds) => {
  const total = Math.max(0, Math.floor(toFiniteNumber(seconds, 0)));
  if (total < 60) return total + "秒";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total % 3600 / 60);
  if (!hours) return minutes + "分钟";
  return hours + "小时" + (minutes ? minutes + "分钟" : "");
};
const getLocalDate = (date) => {
  const value = date || new Date();
  const pad = (number) => ("0" + number).slice(-2);
  return value.getFullYear() + "-" + pad(value.getMonth() + 1) + "-" + pad(value.getDate());
};
const normalizeRealtimePosture = (record) => {
  if (!record) return null;
  const rawStatus = record.posture_status || record.postureStatus || "unknown";
  return {
    deviceId: record.device_id || record.deviceId || "bag001",
    postureStatus: rawStatus === "good" || rawStatus === "bad" ? rawStatus : "unknown",
    isWearing: record.is_wearing === true || record.isWearing === true,
    reminderActive: record.reminder_active === true || record.reminderActive === true,
    reminderType: record.reminder_type || record.reminderType || "",
    updatedAtMs: toTimestampMs(record.updated_at || record.updatedAt || record.receivedAt)
  };
};
const normalizeHunchReminder = (record) => {
  if (!record || record.alarmType !== "posture_hunch_reminder") return null;
  const timestampMs = toTimestampMs(record.reportedAt || record.receivedAt);
  if (!timestampMs) return null;
  return { id: record.alarmId || record.requestId || String(timestampMs), timeText: formatClock(timestampMs), message: "已轻微震动 5 秒并播放语音提醒" };
};
const toRealtimeDisplay = (posture, nowMs, offlineAfterMs) => {
  const stale = !posture || !posture.updatedAtMs || nowMs - posture.updatedAtMs > offlineAfterMs;
  if (stale) return { statusText: "设备离线", statusLevel: "offline", postureKey: "unknown", postureText: "暂无数据", postureDetail: "未收到设备的最新姿态状态", showReminder: false, updateTime: "--:--:--" };
  if (!posture.isWearing) return { statusText: "设备在线", statusLevel: "connected", postureKey: "unworn", postureText: "未佩戴", postureDetail: "当前未检测到背包佩戴状态", showReminder: false, updateTime: formatClock(posture.updatedAtMs) };
  if (posture.postureStatus === "good") return { statusText: "设备在线", statusLevel: "connected", postureKey: "good", postureText: "良好姿态", postureDetail: "良好姿态，没有驼背", showReminder: posture.reminderActive, updateTime: formatClock(posture.updatedAtMs) };
  if (posture.postureStatus === "bad") return { statusText: "设备在线", statusLevel: "connected", postureKey: "bad", postureText: "不良姿态", postureDetail: "检测到持续不良驼背姿态，请及时调整", showReminder: posture.reminderActive, updateTime: formatClock(posture.updatedAtMs) };
  return { statusText: "设备在线", statusLevel: "connected", postureKey: "unknown", postureText: "暂无数据", postureDetail: "当前姿态状态不可用", showReminder: false, updateTime: formatClock(posture.updatedAtMs) };
};
const normalizeDailyPosture = (record) => {
  if (!record) return null;
  const wearingSeconds = Math.max(0, toFiniteNumber(record.wearing_seconds || record.wearingSeconds, 0));
  const goodSeconds = clamp(Math.max(0, toFiniteNumber(record.good_seconds || record.goodSeconds, 0)), 0, wearingSeconds);
  const badSeconds = clamp(Math.max(0, toFiniteNumber(record.bad_seconds || record.badSeconds, 0)), 0, wearingSeconds);
  const hasValidData = wearingSeconds > 0;
  const goodPercent = hasValidData ? clamp(Math.round(goodSeconds / wearingSeconds * 100), 0, 100) : 0;
  return { deviceId: record.device_id || record.deviceId || "bag001", date: record.date || "", wearingSeconds, goodSeconds, badSeconds, goodPercent, badPercent: hasValidData ? 100 - goodPercent : 0, updatedAtMs: toTimestampMs(record.updated_at || record.updatedAt || record.receivedAt), hasValidData };
};
module.exports = { formatClock, formatDuration, getLocalDate, normalizeDailyPosture, normalizeHunchReminder, normalizeRealtimePosture, toRealtimeDisplay };
