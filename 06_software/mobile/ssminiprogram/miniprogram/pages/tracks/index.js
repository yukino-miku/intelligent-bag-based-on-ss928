const trackUtils = require("../../utils/track-utils");

const NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E";
const TARGET_NAMES = ["SS928-SmartBag"];
const MAX_MAP_POINTS = 800;

const normalizeUuid = (uuid) => String(uuid || "").toUpperCase();
const isSameUuid = (left, right) => normalizeUuid(left) === normalizeUuid(right);

Page({
  data: {
    targetName: "SS928-SmartBag",
    adapterReady: false,
    scanning: false,
    connecting: false,
    connected: false,
    statusText: "未连接",
    statusLevel: "idle",
    scanButtonText: "扫描",
    deviceId: "",
    deviceName: "",
    deviceLabel: "未连接",
    devices: [],
    hasDevices: false,
    connectingDeviceId: "",
    trackItems: [],
    hasTrackItems: false,
    selectedTrackIndex: -1,
    currentTrackLabel: "未选择轨迹",
    loadingTrack: false,
    pointCount: 0,
    displayCount: 0,
    hasTrack: false,
    latestMeta: "等待轨迹数据",
    latitude: 31.23042,
    longitude: 121.4737,
    scale: 16,
    markers: [],
    polyline: [],
    liveEnabled: false,
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
    this.trackPoints = [];
    this.trackIndex = -1;

    wx.onBluetoothDeviceFound((res) => this.handleDeviceFound(res));
    wx.onBLECharacteristicValueChange((res) => this.handleCharacteristicValue(res));
    wx.onBLEConnectionStateChange((res) => this.handleConnectionStateChange(res));
    wx.onBluetoothAdapterStateChange((res) => {
      if (!res.available) {
        this.resetConnection("手机蓝牙不可用");
        this.setData({ adapterReady: false, scanning: false, scanButtonText: "扫描", statusLevel: "warn" });
      }
    });
  },

  onUnload() {
    if (this.data.liveEnabled && this.data.connected) {
      this.writeCommand("GNSS TF 0", true);
    }
    this.stopScan(true);
    if (this.activeDeviceId) {
      wx.closeBLEConnection({ deviceId: this.activeDeviceId });
    }
    if (this.data.adapterReady) {
      wx.closeBluetoothAdapter({});
    }
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
      this.setData({
        devices: [],
        hasDevices: false,
        scanning: true,
        connecting: false,
        scanButtonText: "扫描中",
        statusText: "正在扫描轨迹设备",
        statusLevel: "busy"
      });
      wx.startBluetoothDevicesDiscovery({
        allowDuplicatesKey: true,
        services: [NUS_SERVICE_UUID],
        success: () => {},
        fail: (err) => {
          this.setData({
            scanning: false,
            scanButtonText: "扫描",
            statusText: "扫描失败 " + (err.errMsg || "未知错误"),
            statusLevel: "warn"
          });
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
        const patch = { scanning: false, scanButtonText: "扫描" };
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
      if (!this.matchesTargetName(name) && !hasNusService) {
        continue;
      }
      this.deviceMap[item.deviceId] = {
        deviceId: item.deviceId,
        name: name || "SS928-SmartBag",
        rssi: typeof item.RSSI === "number" ? item.RSSI : -100,
        hasNusService
      };
      changed = true;
    }
    if (!changed) {
      return;
    }
    const list = Object.keys(this.deviceMap).map((key) => this.deviceMap[key]);
    list.sort((left, right) => right.rssi - left.rssi);
    this.setData({ devices: list, hasDevices: list.length > 0, statusText: "发现 " + list.length + " 个设备", statusLevel: "busy" });
  },

  matchesTargetName(name) {
    for (let i = 0; i < TARGET_NAMES.length; i += 1) {
      if (String(name || "").indexOf(TARGET_NAMES[i]) !== -1) {
        return true;
      }
    }
    return false;
  },

  connectFromTap(e) {
    const deviceId = e.currentTarget.dataset.deviceId;
    const deviceName = e.currentTarget.dataset.deviceName || "SS928-SmartBag";
    if (!deviceId || this.data.connecting) {
      return;
    }
    this.connectToDevice(deviceId, deviceName);
  },

  connectToDevice(deviceId, deviceName) {
    this.stopScan(true);
    this.receiveText = "";
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
      this.setData({
        connecting: false,
        connected: true,
        connectingDeviceId: "",
        deviceId,
        deviceName,
        deviceLabel: deviceName,
        statusText: "已连接，准备拉取轨迹",
        statusLevel: "connected",
        commandResponse: "已开启 TX notify"
      });
      this.requestTrackList();
      this.requestStatus();
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
    const parsed = trackUtils.appendBleText(this.receiveText, this.arrayBufferToString(res.value));
    this.receiveText = parsed.buffer;
    for (let i = 0; i < parsed.lines.length; i += 1) {
      this.handleIncomingLine(parsed.lines[i]);
    }
  },

  handleIncomingLine(line) {
    const text = String(line || "").trim();
    if (!text) {
      return;
    }
    if (text.charAt(0) !== "{") {
      this.setData({ commandResponse: text });
      this.addLog(text);
      return;
    }
    try {
      const frame = JSON.parse(text);
      this.handleFrame(frame, text);
    } catch (err) {
      this.addLog("JSON 解析失败 " + text.slice(0, 42));
    }
  },

  handleFrame(frame, text) {
    if (frame.typ === "tl") {
      this.applyTrackList(frame.items || []);
      return;
    }
    if (frame.typ === "trk") {
      this.applyTrackChunk(frame);
      return;
    }
    if (frame.typ === "loc") {
      this.applyLiveLocation(frame);
      return;
    }
    if (frame.typ === "ts" || frame.typ === "st") {
      this.setData({ commandResponse: text, statusText: "状态已更新", statusLevel: this.data.connected ? "connected" : "idle" });
      this.addLog(text);
      return;
    }
    this.setData({ commandResponse: text });
    this.addLog(text);
  },

  applyTrackList(items) {
    const list = [];
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i] || {};
      list.push({
        listIndex: i,
        i: typeof item.i === "number" ? item.i : i,
        id: item.id || "track-" + i,
        n: Number(item.n || 0),
        start: Number(item.start || 0),
        end: Number(item.end || 0),
        title: item.id || ("轨迹 " + (i + 1)),
        timeRange: trackUtils.formatTrackTime(item.start) + " - " + trackUtils.formatTrackTime(item.end)
      });
    }
    this.setData({
      trackItems: list,
      hasTrackItems: list.length > 0,
      statusText: list.length ? "已获取轨迹列表" : "暂无本地轨迹",
      statusLevel: this.data.connected ? "connected" : "idle",
      commandResponse: "TL 返回 " + list.length + " 条轨迹"
    });
  },

  applyTrackChunk(frame) {
    const merged = trackUtils.mergeTrackChunk(this.trackPoints, frame);
    this.trackPoints = merged.points;
    this.renderTrack(false);
    if (!merged.done && merged.nextOffset !== null) {
      this.requestTrackChunk(frame.i, merged.nextOffset);
      return;
    }
    this.setData({ loadingTrack: false, statusText: "轨迹加载完成", statusLevel: "connected", commandResponse: "轨迹点 " + this.trackPoints.length + " 个" });
  },

  applyLiveLocation(frame) {
    const point = trackUtils.normalizeTrackPoint(frame);
    if (!point) {
      this.addLog("忽略无效实时定位点");
      return;
    }
    this.trackPoints = trackUtils.mergeTrackChunk(this.trackPoints, { pts: [[point.time, point.rawLatitude, point.rawLongitude, point.accuracy, point.speed, point.course]], done: 1 }).points;
    this.renderTrack(true);
    this.setData({ statusText: "实时位置已更新", statusLevel: "connected" });
  },

  renderTrack(keepScale) {
    const display = trackUtils.downsampleTrackPoints(this.trackPoints, MAX_MAP_POINTS);
    const patch = {
      pointCount: this.trackPoints.length,
      displayCount: display.length,
      hasTrack: display.length > 0,
      markers: trackUtils.buildMarkers(display),
      polyline: trackUtils.buildPolyline(display)
    };
    if (display.length) {
      const last = display[display.length - 1];
      patch.latitude = last.latitude;
      patch.longitude = last.longitude;
      patch.latestMeta = trackUtils.formatTrackTime(last.time) + "  精度 " + this.formatNumber(last.accuracy, "--") + "m  速度 " + this.formatNumber(last.speed, "--") + "m/s";
      if (!keepScale) {
        patch.scale = display.length > 1 ? 15 : 17;
      }
    } else {
      patch.latestMeta = "等待轨迹数据";
      patch.markers = [];
      patch.polyline = [];
    }
    this.setData(patch);
  },

  requestTrackList() {
    this.writeCommand("GNSS TL");
  },

  requestStatus() {
    this.writeCommand("GNSS TS");
  },

  selectTrack(e) {
    const listIndex = Number(e.currentTarget.dataset.listIndex);
    const item = this.data.trackItems[listIndex];
    if (!item || !this.data.connected) {
      return;
    }
    this.trackIndex = item.i;
    this.trackPoints = [];
    this.setData({
      selectedTrackIndex: listIndex,
      currentTrackLabel: item.title,
      loadingTrack: true,
      hasTrack: false,
      pointCount: 0,
      displayCount: 0,
      markers: [],
      polyline: [],
      latestMeta: "正在加载轨迹",
      commandResponse: "请求 " + item.title
    });
    this.requestTrackChunk(item.i, 0);
  },

  requestTrackChunk(trackIndex, offset) {
    this.writeCommand("GNSS TG " + trackIndex + " " + offset, true);
  },

  toggleLive() {
    if (!this.data.connected) {
      this.setData({ commandResponse: "请先连接设备" });
      return;
    }
    const next = !this.data.liveEnabled;
    this.setData({ liveEnabled: next, commandResponse: next ? "开启实时位置" : "关闭实时位置" });
    this.writeCommand(next ? "GNSS TF 1" : "GNSS TF 0");
  },

  clearTrack() {
    this.trackPoints = [];
    this.setData({
      loadingTrack: false,
      selectedTrackIndex: -1,
      currentTrackLabel: "未选择轨迹",
      pointCount: 0,
      displayCount: 0,
      hasTrack: false,
      markers: [],
      polyline: [],
      latestMeta: "等待轨迹数据",
      commandResponse: "已清空本地轨迹显示"
    });
  },

  centerMap() {
    if (!this.trackPoints.length) {
      return;
    }
    const last = this.trackPoints[this.trackPoints.length - 1];
    this.setData({ latitude: last.latitude, longitude: last.longitude, scale: 16 });
  },

  disconnectDevice() {
    const deviceId = this.activeDeviceId || this.data.deviceId;
    if (!deviceId) {
      this.resetConnection("未连接");
      return;
    }
    if (this.data.liveEnabled) {
      this.writeCommand("GNSS TF 0", true);
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

  writeCommand(command, silent) {
    if (!this.data.connected || !this.activeDeviceId || !this.serviceId || !this.rxCharacteristicId) {
      if (silent !== true) {
        this.setData({ commandResponse: "未连接，无法发送 " + command });
      }
      return;
    }
    wx.writeBLECharacteristicValue({
      deviceId: this.activeDeviceId,
      serviceId: this.serviceId,
      characteristicId: this.rxCharacteristicId,
      value: this.stringToArrayBuffer(command + "\n"),
      success: () => {
        if (silent !== true) {
          this.setData({ commandResponse: "已发送 " + command });
        }
      },
      fail: (err) => this.setData({ commandResponse: "发送失败 " + (err.errMsg || command), statusLevel: "warn" })
    });
  },

  resetConnection(statusText) {
    this.activeDeviceId = "";
    this.serviceId = "";
    this.txCharacteristicId = "";
    this.rxCharacteristicId = "";
    this.receiveText = "";
    this.setData({
      connecting: false,
      connected: false,
      scanning: false,
      liveEnabled: false,
      loadingTrack: false,
      connectingDeviceId: "",
      deviceId: "",
      deviceName: "",
      deviceLabel: "未连接",
      statusText,
      statusLevel: "idle",
      scanButtonText: "扫描"
    });
  },

  addLog(text) {
    const logs = [text].concat(this.data.logs || []);
    this.setData({ logs: logs.slice(0, 5) });
  },

  formatNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num.toFixed(1) : fallback;
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
