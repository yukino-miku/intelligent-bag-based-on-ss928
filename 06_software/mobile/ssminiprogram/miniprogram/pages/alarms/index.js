const cloudDataSource = require("../../services/cloud-data-source");

const FALL_ALARM_TYPE = "fall_detected";
const FALL_TITLE = "检测到摔倒";
const NO_LOCATION_TEXT = "暂无定位";

const parseAlarmTime = (value) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (value && typeof value.getTime === "function") {
    return value.getTime();
  }
  if (typeof value === "string") {
    const timestamp = new Date(value.replace(/-/g, "/")).getTime();
    return Number.isFinite(timestamp) ? timestamp : 0;
  }
  return 0;
};

const pad = (value) => String(value).padStart(2, "0");

const formatAlarmTime = (timestamp) => {
  if (!timestamp) {
    return { dateLabel: "--", timeText: "时间未知", timeDetail: "时间未知" };
  }
  const date = new Date(timestamp);
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  return {
    dateLabel: month + "." + day,
    timeText: year + "-" + pad(month) + "-" + pad(day) + " " + hours + ":" + minutes,
    timeDetail: year + "年" + month + "月" + day + "日 " + hours + ":" + minutes
  };
};

const normalizeFallAlarm = (item, index) => {
  const raw = item && typeof item === "object" ? item : {};
  const location = raw.location && typeof raw.location === "object" ? raw.location : {};
  const latitude = Number(location.latitude);
  const longitude = Number(location.longitude);
  const hasLocation = Number.isFinite(latitude) && Number.isFinite(longitude);
  const time = parseAlarmTime(raw.reportedAt || raw.deviceTimestampMs || raw.receivedAt);
  const labels = formatAlarmTime(time);
  return Object.assign({
    id: raw.alarmId || raw._id || ("fall-" + index + "-" + time),
    typeText: FALL_TITLE,
    riskText: "高风险",
    messageText: raw.message || "未提供补充说明",
    locationText: hasLocation ? latitude.toFixed(6) + ", " + longitude.toFixed(6) : NO_LOCATION_TEXT,
    addressText: hasLocation ? latitude.toFixed(6) + ", " + longitude.toFixed(6) : NO_LOCATION_TEXT,
    latitude: hasLocation ? latitude : 0,
    longitude: hasLocation ? longitude : 0,
    hasLocation,
    time
  }, labels);
};

const buildAlarmMarker = (item) => {
  if (!item || !item.hasLocation) {
    return [];
  }
  return [{
    id: 1,
    latitude: item.latitude,
    longitude: item.longitude,
    title: item.typeText,
    callout: {
      content: item.typeText,
      color: "#101820",
      fontSize: 13,
      borderRadius: 6,
      bgColor: "#FFFFFF",
      padding: 8,
      display: "ALWAYS"
    }
  }];
};

Page({
  data: {
    title: "摔倒报警历史",
    subtitle: "云端摔倒记录 / 时间线",
    isAlertsMode: true,
    isAlarmDetail: false,
    alarmLoading: false,
    alarmError: "",
    alarmRecords: [],
    selectedAlarm: null,
    alarmMarkers: []
  },

  onLoad(options) {
    this.alertAlarmId = options && options.alarmId ? options.alarmId : "";
    this.setData({ isAlertsMode: true });
  },

  onShow() {
    if (this.data.isAlertsMode) {
      this.loadAlarmHistory();
    }
  },

  loadAlarmHistory() {
    this.setData({ alarmLoading: true, alarmError: "" });
    cloudDataSource.getAlarmHistory().then((result) => {
      const items = result && Array.isArray(result.items) ? result.items : [];
      const records = items
        .filter((item) => item && item.alarmType === FALL_ALARM_TYPE)
        .map((item, index) => normalizeFallAlarm(item, index))
        .sort((left, right) => right.time - left.time);
      const selected = this.alertAlarmId
        ? records.find((item) => item.id === this.alertAlarmId) || null
        : null;
      const isAlarmDetail = Boolean(selected);
      this.setData({
        title: "摔倒报警历史",
        subtitle: "云端摔倒记录 / 时间线",
        isAlertsMode: true,
        isAlarmDetail,
        alarmLoading: false,
        alarmRecords: records,
        selectedAlarm: selected,
        alarmMarkers: buildAlarmMarker(selected)
      });
      wx.setNavigationBarTitle({ title: isAlarmDetail ? "摔倒报警详情" : "摔倒报警历史" });
    }).catch(() => {
      this.setData({
        alarmLoading: false,
        alarmError: "云端报警加载失败，请稍后重试",
        alarmRecords: [],
        selectedAlarm: null,
        alarmMarkers: []
      });
    });
  },

  openAlarmDetail(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) {
      return;
    }
    wx.navigateTo({
      url: "/pages/alarms/index?alarmId=" + encodeURIComponent(id)
    });
  },

  goAlarmList() {
    const pages = getCurrentPages();
    if (pages.length > 1) {
      wx.navigateBack({ delta: 1 });
      return;
    }
    wx.redirectTo({ url: "/pages/alarms/index" });
  }
});
