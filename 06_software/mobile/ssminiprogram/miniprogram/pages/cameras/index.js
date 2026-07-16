const {
  DEFAULT_CAMERA_CONFIG,
  SnapshotHttpTransport,
  normalizeConfig,
  boardBaseUrl
} = require("../../utils/camera-transport");

const STORAGE_KEY = "smartbagCameraConfig";

const emptyCamera = (side, label) => ({
  side,
  label,
  online: false,
  statusText: "未连接",
  imageUrl: "",
  captureFps: "--",
  inferenceFps: "--",
  streamFps: "--",
  lastFrameAge: "--",
  riskName: "SAFE",
  riskLevel: 0,
  device: "--",
  endpoint: "--",
  jpegQuality: "--",
  updatedAt: "--"
});

Page({
  data: {
    config: DEFAULT_CAMERA_CONFIG,
    baseUrl: "未配置",
    left: emptyCamera("left", "左后摄像头"),
    right: emptyCamera("right", "右后摄像头"),
    paused: false,
    viewMode: "overlay",
    connectionMessage: "请填写板端地址"
  },

  onLoad() {
    const stored = wx.getStorageSync(STORAGE_KEY) || {};
    const config = normalizeConfig(stored);
    this.transport = new SnapshotHttpTransport(config, wx);
    this.setData({ config, viewMode: config.viewMode, baseUrl: boardBaseUrl(config) || "未配置" });
  },

  onShow() {
    this.startRefresh();
  },

  onHide() {
    this.stopRefresh();
  },

  onUnload() {
    this.stopRefresh();
  },

  updateConfigField(e) {
    const field = e.currentTarget.dataset.field;
    if (!field) {
      return;
    }
    this.setData({ ["config." + field]: e.detail.value });
  },

  saveAndReconnect() {
    const config = normalizeConfig(Object.assign({}, this.data.config, { viewMode: this.data.viewMode }));
    wx.setStorageSync(STORAGE_KEY, config);
    this.transport.updateConfig(config);
    this.setData({ config, baseUrl: boardBaseUrl(config) || "未配置", connectionMessage: "正在连接" });
    this.startRefresh();
  },

  setViewMode(e) {
    const viewMode = e.currentTarget.dataset.mode === "raw" ? "raw" : "overlay";
    this.setData({ viewMode, "config.viewMode": viewMode });
    this.saveAndReconnect();
  },

  togglePause() {
    const paused = !this.data.paused;
    this.setData({ paused });
    if (paused) {
      this.stopRefresh();
    } else {
      this.startRefresh();
    }
  },

  startRefresh() {
    this.stopRefresh();
    if (this.data.paused || !this.transport || !boardBaseUrl(this.transport.config)) {
      return;
    }
    this.refreshSnapshots();
    this.refreshStatuses();
    const interval = Math.max(100, Math.round(1000 / this.transport.config.refreshFps));
    this.snapshotTimer = setInterval(() => this.refreshSnapshots(), interval);
    this.statusTimer = setInterval(() => this.refreshStatuses(), 1000);
  },

  stopRefresh() {
    if (this.snapshotTimer) {
      clearInterval(this.snapshotTimer);
      this.snapshotTimer = null;
    }
    if (this.statusTimer) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
  },

  refreshSnapshots() {
    const cacheKey = Date.now();
    this.setData({
      "left.imageUrl": this.transport.snapshotUrl("left", cacheKey),
      "right.imageUrl": this.transport.snapshotUrl("right", cacheKey),
      "left.endpoint": this.transport.snapshotUrl("left", ""),
      "right.endpoint": this.transport.snapshotUrl("right", "")
    });
  },

  refreshStatuses() {
    ["left", "right"].forEach((side) => {
      this.transport.status(side).then((status) => this.applyStatus(side, status)).catch((error) => {
        this.setData({
          [side + ".online"]: false,
          [side + ".statusText"]: "离线",
          connectionMessage: error.errMsg || error.message || "连接失败"
        });
      });
    });
  },

  applyStatus(side, status) {
    const now = new Date();
    const updatedAt = ("0" + now.getHours()).slice(-2) + ":" +
      ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
    this.setData({
      [side + ".online"]: status.online === true,
      [side + ".statusText"]: status.online === true ? "在线" : "离线",
      [side + ".captureFps"]: this.formatMetric(status.capture_fps),
      [side + ".inferenceFps"]: this.formatMetric(status.inference_fps),
      [side + ".streamFps"]: this.formatMetric(status.stream_fps),
      [side + ".lastFrameAge"]: this.formatMetric(status.last_frame_age_ms),
      [side + ".riskName"]: status.risk_name || "SAFE",
      [side + ".riskLevel"]: Number(status.risk_level) || 0,
      [side + ".device"]: status.device || "--",
      [side + ".jpegQuality"]: Number.isFinite(Number(status.jpeg_quality)) ? String(status.jpeg_quality) : "--",
      [side + ".updatedAt"]: updatedAt,
      connectionMessage: "状态已更新"
    });
  },

  previewSide(e) {
    const side = e.currentTarget.dataset.side;
    const url = side === "right" ? this.data.right.imageUrl : this.data.left.imageUrl;
    if (url) {
      wx.previewImage({ current: url, urls: [url] });
    }
  },

  formatMetric(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(1) : "--";
  }
});
