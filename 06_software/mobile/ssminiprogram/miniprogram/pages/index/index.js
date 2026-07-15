const TARGET_DEVICE_NAME = "SS928-SmartBag";
const NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E";

const CAPTURE_MODES = [
  { key: "straight", title: "站直", duration: 15, fileHint: "straight_01.csv", detail: "背书包站直" },
  { key: "hunch", title: "驼背", duration: 15, fileHint: "hunch_01.csv", detail: "背书包驼背" },
  { key: "straight_walk", title: "站直走动", duration: 30, fileHint: "straight_walk_01.csv", detail: "正常站姿/走几步" },
  { key: "hunch_walk", title: "驼背走动", duration: 30, fileHint: "hunch_walk_01.csv", detail: "驼背状态走几步" },
  { key: "bend_pickup", title: "弯腰动作", duration: 30, fileHint: "bend_pickup_01.csv", detail: "捡东西或调整书包" }
];

const EMPTY_POSE = {
  roll: "--",
  pitch: "--",
  yaw: "--",
  accelG: "--",
  gyroDps: "--",
  stationary: "--",
  lastUpdate: "未收到"
};

const normalizeUuid = (uuid) => String(uuid || "").toUpperCase();
const isSameUuid = (left, right) => normalizeUuid(left) === normalizeUuid(right);
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const pad2 = (value) => ("0" + value).slice(-2);
const formatTime = (date) => pad2(date.getHours()) + ":" + pad2(date.getMinutes()) + ":" + pad2(date.getSeconds());

Page({
  data: {
    targetName: TARGET_DEVICE_NAME,
    adapterReady: false,
    scanning: false,
    connecting: false,
    connected: false,
    statusText: "未连接",
    statusLevel: "idle",
    scanButtonText: "扫描设备",
    deviceId: "",
    deviceName: "",
    deviceLabel: "未连接",
    devices: [],
    hasDevices: false,
    connectingDeviceId: "",
    modes: CAPTURE_MODES,
    selectedModeKey: CAPTURE_MODES[0].key,
    selectedMode: CAPTURE_MODES[0],
    recording: false,
    recordModeLabel: "未开始",
    recordFile: "--",
    recordElapsed: "0.0",
    recordRows: 0,
    recordDuration: CAPTURE_MODES[0].duration,
    recordProgressStyle: "width: 0%;",
    lastCompleted: "无",
    latestPose: EMPTY_POSE,
    sampleHz: "0",
    frameCount: 0,
    commandResponse: "等待连接",
    logs: []
  },

  onLoad() {
    this.deviceMap = {};
    this.activeDeviceId = "";
    this.serviceId = "";
    this.txCharacteristicId = "";
    this.rxCharacteristicId = "";
    this.receiveText = "";
    this.sampleTimes = [];

    wx.onBluetoothDeviceFound((res) => this.handleDeviceFound(res));
    wx.onBLECharacteristicValueChange((res) => this.handleCharacteristicValue(res));
    wx.onBLEConnectionStateChange((res) => this.handleConnectionStateChange(res));
    wx.onBluetoothAdapterStateChange((res) => {
      if (!res.available) {
        this.resetConnection("手机蓝牙不可用");
        this.setData({ adapterReady: false, scanning: false, scanButtonText: "扫描设备", statusLevel: "warn" });
      }
    });
  },

  onUnload() {
    this.stopScan(true);
    if (this.activeDeviceId) {
      wx.closeBLEConnection({ deviceId: this.activeDeviceId });
    }
    if (this.data.adapterReady) {
      wx.closeBluetoothAdapter({});
    }
  },

  goMonitor() {
    wx.redirectTo({ url: "/pages/monitor/index" });
  },

  selectMode(e) {
    const key = e.currentTarget.dataset.key;
    const mode = this.findMode(key);
    if (!mode || this.data.recording) {
      return;
    }
    this.setData({ selectedModeKey: key, selectedMode: mode, recordDuration: mode.duration, recordProgressStyle: "width: 0%;" });
  },

  openAdapter() {
    if (this.data.adapterReady) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      wx.openBluetoothAdapter({
        success: () => {
          this.setData({ adapterReady: true, statusText: "蓝牙已打开", statusLevel: "idle" });
          resolve();
        },
        fail: (err) => {
          this.setData({ statusText: "请打开手机蓝牙后重试", statusLevel: "warn" });
          reject(err);
        }
      });
    });
  },

  startScan() {
    if (this.data.scanning) {
      return;
    }
    this.openAdapter().then(() => {
      this.deviceMap = {};
    this.setData({ devices: [], hasDevices: false, scanning: true, connecting: false, scanButtonText: "扫描中", statusText: "正在扫描 SS928-SmartBag", statusLevel: "busy" });
      wx.startBluetoothDevicesDiscovery({
        allowDuplicatesKey: true,
        success: () => {},
        fail: (err) => {
          this.setData({ scanning: false, scanButtonText: "扫描设备", statusText: "扫描失败 " + (err.errMsg || "未知错误"), statusLevel: "warn" });
        }
      });
    }).catch(() => {});
  },

  stopScan(silent) {
    if (!this.data.scanning) {
      return;
    }
    wx.stopBluetoothDevicesDiscovery({
      complete: () => {
        const patch = { scanning: false, scanButtonText: "扫描设备" };
        if (silent !== true) {
          patch.statusText = this.data.connected ? "已连接" : "扫描已停止";
          patch.statusLevel = this.data.connected ? "connected" : "idle";
        }
        this.setData(patch);
      }
    });
  },

  handleDeviceFound(res) {
    const devices = res.devices || [];
    let changed = false;
    for (let i = 0; i < devices.length; i += 1) {
      const item = devices[i];
      const name = item.name || item.localName || "";
      const serviceList = item.advertisServiceUUIDs || [];
      let hasNusService = false;
      for (let j = 0; j < serviceList.length; j += 1) {
        if (isSameUuid(serviceList[j], NUS_SERVICE_UUID)) {
          hasNusService = true;
          break;
        }
      }
      if (name.indexOf(TARGET_DEVICE_NAME) === -1 && !hasNusService) {
        continue;
      }
      this.deviceMap[item.deviceId] = { deviceId: item.deviceId, name: name || TARGET_DEVICE_NAME, rssi: typeof item.RSSI === "number" ? item.RSSI : -100, hasNusService };
      changed = true;
    }
    if (!changed) {
      return;
    }
    const list = Object.keys(this.deviceMap).map((key) => this.deviceMap[key]);
    list.sort((left, right) => right.rssi - left.rssi);
    this.setData({ devices: list, hasDevices: list.length > 0, statusText: "发现 " + list.length + " 个设备", statusLevel: "busy" });
  },

  connectFromTap(e) {
    const deviceId = e.currentTarget.dataset.deviceId;
    const deviceName = e.currentTarget.dataset.deviceName || TARGET_DEVICE_NAME;
    if (!deviceId || this.data.connecting) {
      return;
    }
    this.connectToDevice(deviceId, deviceName);
  },

  connectToDevice(deviceId, deviceName) {
    this.stopScan(true);
    this.receiveText = "";
    this.sampleTimes = [];
    this.setData({ connecting: true, connectingDeviceId: deviceId, statusText: "连接 " + deviceName, statusLevel: "busy", deviceLabel: deviceName });
    wx.createBLEConnection({
      deviceId,
      timeout: 10000,
      success: () => {
        this.activeDeviceId = deviceId;
        this.setData({ deviceId, deviceName, deviceLabel: deviceName, statusText: "发现服务中" });
        setTimeout(() => this.setupNus(deviceId, deviceName), 500);
      },
      fail: (err) => {
        this.setData({ connecting: false, connectingDeviceId: "", statusText: "连接失败 " + (err.errMsg || "未知错误"), statusLevel: "warn" });
      }
    });
  },

  setupNus(deviceId, deviceName) {
    this.getServices(deviceId).then((services) => {
      const service = this.pickService(services);
      if (!service) {
        throw new Error("未找到 NUS 服务");
      }
      this.serviceId = service.uuid;
      return this.getCharacteristics(deviceId, service.uuid);
    }).then((characteristics) => {
      const picked = this.pickCharacteristics(characteristics);
      if (!picked.tx) {
        throw new Error("未找到 TX notify 特征");
      }
      if (!picked.rx) {
        throw new Error("未找到 RX write 特征");
      }
      this.txCharacteristicId = picked.tx.uuid;
      this.rxCharacteristicId = picked.rx.uuid;
      return this.enableNotify(deviceId, this.serviceId, this.txCharacteristicId);
    }).then(() => {
      this.setData({ connecting: false, connected: true, connectingDeviceId: "", deviceId, deviceName, deviceLabel: deviceName, statusText: "已连接，正在收数据", statusLevel: "connected", commandResponse: "已开启 TX notify" });
      this.writeCommand("C?");
    }).catch((err) => {
      wx.closeBLEConnection({ deviceId });
      this.resetConnection("初始化失败 " + err.message);
      this.setData({ statusLevel: "warn" });
    });
  },

  getServices(deviceId) {
    return new Promise((resolve, reject) => wx.getBLEDeviceServices({ deviceId, success: (res) => resolve(res.services || []), fail: reject }));
  },

  getCharacteristics(deviceId, serviceId) {
    return new Promise((resolve, reject) => wx.getBLEDeviceCharacteristics({ deviceId, serviceId, success: (res) => resolve(res.characteristics || []), fail: reject }));
  },

  enableNotify(deviceId, serviceId, characteristicId) {
    return new Promise((resolve, reject) => wx.notifyBLECharacteristicValueChange({ deviceId, serviceId, characteristicId, state: true, success: resolve, fail: reject }));
  },

  pickService(services) {
    for (let i = 0; i < services.length; i += 1) {
      if (isSameUuid(services[i].uuid, NUS_SERVICE_UUID)) {
        return services[i];
      }
    }
    return null;
  },

  pickCharacteristics(characteristics) {
    let tx = null;
    let rx = null;
    for (let i = 0; i < characteristics.length; i += 1) {
      const item = characteristics[i];
      const props = item.properties || {};
      if (isSameUuid(item.uuid, NUS_TX_UUID)) {
        tx = item;
      }
      if (isSameUuid(item.uuid, NUS_RX_UUID)) {
        rx = item;
      }
      if (!tx && (props.notify || props.indicate)) {
        tx = item;
      }
      if (!rx && (props.write || props.writeNoResponse)) {
        rx = item;
      }
    }
    return { tx, rx };
  },

  handleCharacteristicValue(res) {
    if (this.activeDeviceId && res.deviceId !== this.activeDeviceId) {
      return;
    }
    if (this.txCharacteristicId && !isSameUuid(res.characteristicId, this.txCharacteristicId)) {
      return;
    }
    this.receiveText += this.arrayBufferToString(res.value);
    const lines = this.receiveText.split("\n");
    this.receiveText = lines.pop() || "";
    for (let i = 0; i < lines.length; i += 1) {
      this.handleIncomingLine(lines[i]);
    }
  },

  handleIncomingLine(line) {
    const text = String(line || "").trim();
    if (!text) {
      return;
    }
    if (text.charAt(0) === "{") {
      try {
        const frame = JSON.parse(text);
        if (typeof frame.r !== "undefined" && typeof frame.p !== "undefined" && typeof frame.y !== "undefined") {
          this.updateFrame(frame);
        } else {
          this.handleCommandResponse(text);
        }
      } catch (err) {
        this.addLog("JSON 解析失败 " + text.slice(0, 40));
      }
      return;
    }
    this.handleCommandResponse(text);
  },

  updateFrame(frame) {
    const roll = this.numberOr(frame.r, 0);
    const pitch = this.numberOr(frame.p, 0);
    const yaw = this.numberOr(frame.y, 0);
    const now = Date.now();
    this.sampleTimes.push(now);
    while (this.sampleTimes.length && now - this.sampleTimes[0] > 1000) {
      this.sampleTimes.shift();
    }
    const patch = {
      "latestPose.roll": roll.toFixed(1),
      "latestPose.pitch": pitch.toFixed(1),
      "latestPose.yaw": yaw.toFixed(1),
      "latestPose.accelG": this.numberOr(frame.ag, 0).toFixed(2),
      "latestPose.gyroDps": this.numberOr(frame.gyr, 0).toFixed(1),
      "latestPose.stationary": frame.st ? "静止" : "运动",
      "latestPose.lastUpdate": formatTime(new Date(now)),
      frameCount: this.data.frameCount + 1,
      sampleHz: String(this.sampleTimes.length)
    };
    if (frame.rec) {
      this.applyRecordStatus(frame.rec, patch);
    }
    if (!patch.statusText && this.data.connected && !this.data.recording) {
      patch.statusText = "正在接收姿态";
      patch.statusLevel = "connected";
    }
    this.setData(patch);
  },

  applyRecordStatus(rec, patch) {
    const active = Number(rec.a) === 1;
    const mode = this.findMode(rec.m);
    const duration = this.numberOr(rec.d, mode ? mode.duration : this.data.recordDuration);
    const elapsed = this.numberOr(rec.e, 0);
    const rows = Number(rec.n || 0);
    const progress = duration > 0 ? clamp(elapsed / duration * 100, 0, 100) : 0;
    if (active) {
      patch.recording = true;
      patch.recordModeLabel = mode ? mode.title : String(rec.m || "采集中");
      patch.recordFile = rec.f || "--";
      patch.recordElapsed = elapsed.toFixed(1);
      patch.recordRows = rows;
      patch.recordDuration = duration;
      patch.recordProgressStyle = "width: " + progress.toFixed(0) + "%;";
      patch.statusText = "采集 " + patch.recordModeLabel;
      patch.statusLevel = "recording";
      return;
    }
    if (rec.done) {
      patch.recording = false;
      patch.recordModeLabel = "未开始";
      patch.recordFile = rec.f || this.data.recordFile;
      patch.recordElapsed = elapsed.toFixed(1);
      patch.recordRows = rows;
      patch.recordDuration = duration || this.data.recordDuration;
      patch.recordProgressStyle = "width: 100%;";
      patch.lastCompleted = (rec.f || "CSV") + "，" + rows + " 行";
      patch.statusText = "采集完成";
      patch.statusLevel = "connected";
    }
  },

  handleCommandResponse(text) {
    const patch = { commandResponse: text };
    if (text.indexOf("OK cal_start") === 0) {
      patch.recording = true;
      patch.recordFile = this.extractToken(text, "file") || this.data.recordFile;
      patch.statusText = "采集已开始";
      patch.statusLevel = "recording";
      patch.recordProgressStyle = "width: 0%;";
    } else if (text.indexOf("OK cal_stop") === 0) {
      const file = this.extractToken(text, "file") || this.data.recordFile;
      const rows = Number(this.extractToken(text, "rows") || this.data.recordRows || 0);
      patch.recording = false;
      patch.recordModeLabel = "未开始";
      patch.recordFile = file;
      patch.recordRows = rows;
      patch.lastCompleted = file + "，" + rows + " 行";
      patch.statusText = "采集完成";
      patch.statusLevel = "connected";
      patch.recordProgressStyle = "width: 100%;";
    } else if (text.indexOf("ERR") === 0) {
      patch.statusText = text;
      patch.statusLevel = "warn";
    }
    this.setData(patch);
    this.addLog(text);
  },

  startCapture() {
    if (!this.data.connected) {
      this.setData({ commandResponse: "请先连接设备" });
      return;
    }
    if (this.data.recording) {
      return;
    }
    const mode = this.findMode(this.data.selectedModeKey) || CAPTURE_MODES[0];
    this.setData({ recordModeLabel: mode.title, recordFile: mode.fileHint, recordElapsed: "0.0", recordRows: 0, recordDuration: mode.duration, recordProgressStyle: "width: 0%;", commandResponse: "正在发送采集命令" });
    this.writeCommand("CS " + mode.key + " " + mode.duration);
  },

  stopCapture() {
    if (!this.data.connected) {
      this.setData({ commandResponse: "请先连接设备" });
      return;
    }
    this.writeCommand("CE");
  },

  sendStatus() {
    this.writeCommand("C?");
  },

  writeCommand(command) {
    if (!this.data.connected || !this.activeDeviceId || !this.serviceId || !this.rxCharacteristicId) {
      this.setData({ commandResponse: "未连接，无法发送 " + command });
      return;
    }
    wx.writeBLECharacteristicValue({
      deviceId: this.activeDeviceId,
      serviceId: this.serviceId,
      characteristicId: this.rxCharacteristicId,
      value: this.stringToArrayBuffer(command + "\n"),
      success: () => this.setData({ commandResponse: "已发送 " + command }),
      fail: (err) => this.setData({ commandResponse: "发送失败 " + (err.errMsg || command), statusLevel: "warn" })
    });
  },

  disconnectDevice() {
    const deviceId = this.activeDeviceId || this.data.deviceId;
    if (!deviceId) {
      this.resetConnection("未连接");
      return;
    }
    wx.closeBLEConnection({ deviceId, complete: () => this.resetConnection("已断开") });
  },

  handleConnectionStateChange(res) {
    if (!this.activeDeviceId || res.deviceId !== this.activeDeviceId) {
      return;
    }
    if (!res.connected) {
      this.resetConnection("连接已断开");
      this.setData({ statusLevel: "warn" });
    }
  },

  resetConnection(statusText) {
    this.activeDeviceId = "";
    this.serviceId = "";
    this.txCharacteristicId = "";
    this.rxCharacteristicId = "";
    this.receiveText = "";
    this.sampleTimes = [];
    this.setData({ connecting: false, connected: false, recording: false, connectingDeviceId: "", deviceId: "", deviceName: "", deviceLabel: "未连接", statusText, statusLevel: "idle", sampleHz: "0" });
  },

  findMode(key) {
    for (let i = 0; i < CAPTURE_MODES.length; i += 1) {
      if (CAPTURE_MODES[i].key === key) {
        return CAPTURE_MODES[i];
      }
    }
    return null;
  },

  extractToken(text, key) {
    const match = String(text).match(new RegExp(key + "=([^ ]+)"));
    return match ? match[1] : "";
  },

  addLog(text) {
    const logs = [text].concat(this.data.logs || []);
    this.setData({ logs: logs.slice(0, 5) });
  },

  numberOr(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  },

  arrayBufferToString(buffer) {
    const data = new Uint8Array(buffer);
    let text = "";
    for (let i = 0; i < data.length; i += 1) {
      text += String.fromCharCode(data[i]);
    }
    return text;
  },

  stringToArrayBuffer(text) {
    const buffer = new ArrayBuffer(text.length);
    const data = new Uint8Array(buffer);
    for (let i = 0; i < text.length; i += 1) {
      data[i] = text.charCodeAt(i) & 0xff;
    }
    return buffer;
  }
});
