const {
  DEFAULT_CAMERA_CONFIG,
  SnapshotHttpTransport,
  normalizeConfig,
  boardBaseUrl,
  normalizeCameraStatus
} = require("../../utils/camera-transport");

const STORAGE_KEY = "smartbagCameraConfig";
const SIDES = ["left", "right"];

const emptyCamera = (side, label) => ({
  side,
  label,
  online: false,
  active: false,
  frameState: "offline",
  statusText: "未连接",
  imageUrl: "",
  captureFps: "--",
  inferenceFps: "--",
  lastFrameAge: "--",
  observationGap: "--",
  riskName: "SAFE",
  riskLevel: 0,
  device: "--",
  endpoint: "--",
  jpegQuality: "--",
  sliceId: "--",
  updatedAt: "--"
});

Page({
  data: {
    config: DEFAULT_CAMERA_CONFIG,
    baseUrl: "未配置",
    left: emptyCamera("left", "左侧摄像头"),
    right: emptyCamera("right", "右侧摄像头"),
    paused: false,
    focusSide: "",
    viewMode: "overlay",
    connectionMessage: "请填写板端地址"
  },

  onLoad() {
    const config = normalizeConfig(wx.getStorageSync(STORAGE_KEY) || {});
    this.transport = new SnapshotHttpTransport(config, wx);
    this.refreshGeneration = 0;
    this.snapshotTimers = {};
    this.snapshotInFlight = { left: false, right: false };
    this.snapshotGeneration = { left: 0, right: 0 };
    this.snapshotBackoffMs = { left: 0, right: 0 };
    this.statusTasks = {};
    this.statusBackoffMs = 0;
    this.setData({
      config,
      viewMode: config.viewMode,
      baseUrl: boardBaseUrl(config) || "未配置"
    });
  },

  onShow() {
    this.startRefresh();
  },

  onHide() {
    this.stopRefresh(true);
  },

  onUnload() {
    this.stopRefresh(true);
  },

  updateConfigField(e) {
    const field = e.currentTarget.dataset.field;
    if (field) {
      this.setData({ ["config." + field]: e.detail.value });
    }
  },

  saveAndReconnect() {
    const config = normalizeConfig(Object.assign({}, this.data.config, {
      viewMode: this.data.viewMode
    }));
    wx.setStorageSync(STORAGE_KEY, config);
    this.transport.updateConfig(config);
    this.setData({
      config,
      baseUrl: boardBaseUrl(config) || "未配置",
      connectionMessage: "正在连接"
    });
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
      this.stopRefresh(true);
    } else {
      this.startRefresh();
    }
  },

  enterSingleView(e) {
    const side = e.currentTarget.dataset.side === "right" ? "right" : "left";
    this.setData({ focusSide: side });
    this.startRefresh();
  },

  exitSingleView() {
    this.setData({ focusSide: "" });
    this.startRefresh();
  },

  startRefresh() {
    this.stopRefresh(false);
    if (this.data.paused || !this.transport || !boardBaseUrl(this.transport.config)) {
      return;
    }
    const generation = ++this.refreshGeneration;
    SIDES.forEach((side) => this.scheduleSnapshot(side, 0, generation));
    this.scheduleStatus(0, generation);
  },

  stopRefresh(clearImages) {
    this.refreshGeneration = (this.refreshGeneration || 0) + 1;
    SIDES.forEach((side) => {
      if (this.snapshotTimers && this.snapshotTimers[side]) {
        clearTimeout(this.snapshotTimers[side]);
        this.snapshotTimers[side] = null;
      }
      this.snapshotInFlight[side] = false;
      this.snapshotGeneration[side] = 0;
      const task = this.statusTasks && this.statusTasks[side];
      if (task && typeof task.abort === "function") {
        task.abort();
      }
      if (this.statusTasks) {
        this.statusTasks[side] = null;
      }
    });
    if (this.statusTimer) {
      clearTimeout(this.statusTimer);
      this.statusTimer = null;
    }
    if (clearImages) {
      this.setData({ "left.imageUrl": "", "right.imageUrl": "" });
    }
  },

  scheduleSnapshot(side, delayMs, generation) {
    if (generation !== this.refreshGeneration || this.data.paused) {
      return;
    }
    if (this.snapshotTimers[side]) {
      clearTimeout(this.snapshotTimers[side]);
    }
    this.snapshotTimers[side] = setTimeout(() => {
      this.snapshotTimers[side] = null;
      this.requestSnapshot(side, generation);
    }, Math.max(0, delayMs));
  },

  requestSnapshot(side, generation) {
    if (generation !== this.refreshGeneration || this.snapshotInFlight[side]) {
      return;
    }
    this.snapshotInFlight[side] = true;
    this.snapshotGeneration[side] = generation;
    const cacheKey = Date.now() + "-" + side;
    this.setData({
      [side + ".imageUrl"]: this.transport.snapshotUrl(side, cacheKey),
      [side + ".endpoint"]: this.transport.snapshotUrl(side, "")
    });
  },

  onSnapshotLoad(e) {
    this.finishSnapshot(e.currentTarget.dataset.side, true);
  },

  onSnapshotError(e) {
    this.finishSnapshot(e.currentTarget.dataset.side, false);
  },

  finishSnapshot(side, success) {
    if (!SIDES.includes(side)) {
      return;
    }
    this.snapshotInFlight[side] = false;
    if (this.snapshotGeneration[side] !== this.refreshGeneration) {
      return;
    }
    this.snapshotBackoffMs[side] = success
      ? 0
      : Math.min(10000, Math.max(500, (this.snapshotBackoffMs[side] || 250) * 2));
    const baseMs = Math.max(100, Math.round(1000 / this.transport.config.refreshFps));
    const focusPenalty = this.data.focusSide && this.data.focusSide !== side ? 5 : 1;
    this.scheduleSnapshot(
      side,
      Math.max(baseMs * focusPenalty, this.snapshotBackoffMs[side]),
      this.refreshGeneration
    );
  },

  scheduleStatus(delayMs, generation) {
    if (generation !== this.refreshGeneration || this.data.paused) {
      return;
    }
    this.statusTimer = setTimeout(() => this.refreshStatuses(generation), Math.max(0, delayMs));
  },

  refreshStatuses(generation) {
    let remaining = SIDES.length;
    let failures = 0;
    const complete = () => {
      remaining -= 1;
      if (remaining > 0 || generation !== this.refreshGeneration) {
        return;
      }
      this.statusBackoffMs = failures
        ? Math.min(10000, Math.max(1000, (this.statusBackoffMs || 500) * 2))
        : 0;
      this.scheduleStatus(Math.max(1000, this.statusBackoffMs), generation);
    };
    SIDES.forEach((side) => {
      const task = this.transport.status(side);
      this.statusTasks[side] = task;
      task.then((status) => {
        if (generation === this.refreshGeneration) {
          this.applyStatus(side, status);
        }
      }).catch((error) => {
        failures += 1;
        if (generation === this.refreshGeneration) {
          this.setData({
            [side + ".online"]: false,
            [side + ".active"]: false,
            [side + ".frameState"]: "offline",
            [side + ".statusText"]: "离线",
            connectionMessage: error.errMsg || error.message || "连接失败"
          });
        }
      }).then(() => {
        if (this.statusTasks[side] === task) {
          this.statusTasks[side] = null;
        }
        complete();
      });
    });
  },

  applyStatus(side, status) {
    const normalized = normalizeCameraStatus(status);
    const now = new Date();
    const updatedAt = ("0" + now.getHours()).slice(-2) + ":" +
      ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
    this.setData({
      [side + ".online"]: normalized.online,
      [side + ".active"]: normalized.active,
      [side + ".frameState"]: normalized.frameState,
      [side + ".statusText"]: normalized.statusText,
      [side + ".captureFps"]: this.formatMetric(normalized.captureFps),
      [side + ".inferenceFps"]: this.formatMetric(normalized.inferenceFps),
      [side + ".lastFrameAge"]: this.formatMetric(normalized.lastFrameAgeMs),
      [side + ".observationGap"]: this.formatMetric(normalized.observationGapMs),
      [side + ".riskName"]: status.risk_name || "SAFE",
      [side + ".riskLevel"]: Number(status.risk_level) || 0,
      [side + ".device"]: status.device || "--",
      [side + ".jpegQuality"]: Number.isFinite(Number(status.jpeg_quality)) ? String(status.jpeg_quality) : "--",
      [side + ".sliceId"]: typeof status.slice_id === "undefined" ? "--" : status.slice_id,
      [side + ".updatedAt"]: updatedAt,
      connectionMessage: "状态已更新"
    });
  },

  formatMetric(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(1) : "--";
  }
});
