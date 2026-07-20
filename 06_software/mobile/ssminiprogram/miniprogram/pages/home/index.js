const { createDeviceDataService } = require("../../services/device-data-service");
const deviceDataService = createDeviceDataService();

const FEATURE_ENTRIES = [
  {
    key: "cameras",
    title: "双摄实时画面",
    subtitle: "左后 / 右后检测画面",
    icon: "视",
    tone: "blue",
    route: "/pages/cameras/index"
  },
  {
    key: "alerts",
    title: "视觉告警与控制",
    subtitle: "左右风险 / 震动调试",
    icon: "警",
    tone: "red",
    route: "/pages/monitor/index"
  },
  {
    key: "tracks",
    title: "安全轨迹跟踪",
    subtitle: "GNSS 位置轨迹",
    icon: "轨",
    tone: "green",
    route: "/pages/tracks/index"
  },
  {
    key: "posture",
    title: "姿态分析和记录",
    subtitle: "BMI270 姿态 / 标定",
    icon: "姿",
    tone: "purple",
    route: "/pages/index/index"
  }
];

Page({
  data: {
    featureEntries: FEATURE_ENTRIES,
    onlineText: "未连接",
    batteryText: "未接入",
    systemState: "等待 SYS STATUS",
    monitorState: "状态未知",
    resourceText: "CPU / 内存 / 温度未读取",
    statusSourceText: "BLE / Cloud 未连接"
  },

  onShow() {
    const status = wx.getStorageSync("smartbagSystemStatus");
    if (status && status.typ === "sys") this.applySystemStatus(status, "BLE", false);
    deviceDataService.getLatestStatus().then((result) => {
      const record = result.data && result.data.payload ? result.data.payload : result.data;
      if (record && record.typ === "sys") this.applySystemStatus(record, result.source, result.stale);
    }).catch(() => {});
  },

  applySystemStatus(status, source, stale) {
    const detectors = Array.isArray(status.detectors) ? status.detectors : [];
    const running = detectors.filter((item) => item.running).length;
    const resources = status.resources || {};
    const parts = [];
    if (typeof resources.cpu_percent === "number") parts.push("CPU " + resources.cpu_percent + "%");
    if (typeof resources.memory_percent === "number") parts.push("内存 " + resources.memory_percent + "%");
    if (typeof resources.temperature_c === "number") parts.push("温度 " + resources.temperature_c + "°C");
    this.setData({
      onlineText: running + "/" + detectors.length + " detector 在线",
      batteryText: status.battery === null || typeof status.battery === "undefined" ? "未接入" : status.battery + "%",
      systemState: running === detectors.length && running > 0 ? "双摄运行" : "需检查",
      monitorState: "SYS STATUS 已更新",
      resourceText: parts.length ? parts.join(" · ") : "CPU / 内存 / 温度未读取",
      statusSourceText: String(source || "unknown").toUpperCase() + (stale ? " 数据已陈旧" : " 数据")
    });
  },

  openFeature(e) {
    const route = e.currentTarget.dataset.route;
    if (route) {
      wx.navigateTo({ url: route });
    }
  }
});
