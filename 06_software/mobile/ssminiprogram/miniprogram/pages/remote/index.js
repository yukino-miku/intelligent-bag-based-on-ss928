const NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";
const NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E";
const TARGET_NAME = "SS928-SmartBag";

const normalizeUuid = (uuid) => String(uuid || "").toUpperCase();
const isSameUuid = (left, right) => normalizeUuid(left) === normalizeUuid(right);

Page({
  data: {
    adapterReady: false,
    scanning: false,
    connecting: false,
    connected: false,
    statusText: "未连接",
    statusLevel: "idle",
    scanButtonText: "扫描设备",
    devices: [],
    deviceId: "",
    deviceName: "",
    deviceLabel: "未连接设备",
    commandResponse: "请先扫描并连接 SS928-SmartBag",
    alertGroups: [
      { side: "left", title: "左侧预警", commands: [{ code: "AL L1", level: 1 }, { code: "AL L2", level: 2 }, { code: "AL L3", level: 3 }, { code: "AL L4", level: 4 }] },
      { side: "right", title: "右侧预警", commands: [{ code: "AL R1", level: 1 }, { code: "AL R2", level: 2 }, { code: "AL R3", level: 3 }, { code: "AL R4", level: 4 }] }
    ]
  },

  onLoad() {
    this.deviceMap = {};
    this.activeDeviceId = "";
    this.serviceId = "";
    this.txCharacteristicId = "";
    this.rxCharacteristicId = "";
    this.receiveText = "";
    wx.onBluetoothDeviceFound((res) => this.handleDeviceFound(res));
    wx.onBLECharacteristicValueChange((res) => this.handleCharacteristicValue(res));
    wx.onBLEConnectionStateChange((res) => this.handleConnectionStateChange(res));
  },

  onUnload() {
    this.stopScan(true);
    if (this.activeDeviceId && this.serviceId && this.txCharacteristicId) {
      wx.notifyBLECharacteristicValueChange({ deviceId: this.activeDeviceId, serviceId: this.serviceId, characteristicId: this.txCharacteristicId, state: false });
    }
    if (this.activeDeviceId) {
      wx.closeBLEConnection({ deviceId: this.activeDeviceId });
    }
    if (this.data.adapterReady) {
      wx.closeBluetoothAdapter({});
    }
  },

  openAdapter() {
    if (this.data.adapterReady) return Promise.resolve();
    return new Promise((resolve, reject) => wx.openBluetoothAdapter({
      success: () => { this.setData({ adapterReady: true, statusText: "蓝牙已打开", statusLevel: "idle" }); resolve(); },
      fail: (err) => { this.setData({ statusText: "请打开手机蓝牙后重试", statusLevel: "warn", commandResponse: err.errMsg || "蓝牙不可用" }); reject(err); }
    }));
  },

  startScan() {
    if (this.data.scanning || this.data.connecting) return;
    this.openAdapter().then(() => {
      this.deviceMap = {};
      this.setData({ devices: [], scanning: true, scanButtonText: "扫描中", statusText: "正在扫描 SS928-SmartBag", statusLevel: "busy" });
      wx.startBluetoothDevicesDiscovery({
        allowDuplicatesKey: true,
        services: [NUS_SERVICE_UUID],
        fail: (err) => this.setData({ scanning: false, scanButtonText: "扫描设备", statusText: "扫描失败", statusLevel: "warn", commandResponse: err.errMsg || "未知错误" })
      });
    }).catch(() => {});
  },

  stopScan(silent) {
    if (!this.data.scanning) return;
    wx.stopBluetoothDevicesDiscovery({ complete: () => this.setData({ scanning: false, scanButtonText: "扫描设备", statusText: silent ? this.data.statusText : (this.data.connected ? "已连接" : "扫描已停止"), statusLevel: this.data.connected ? "connected" : "idle" }) });
  },

  handleDeviceFound(res) {
    const devices = res.devices || [];
    for (let i = 0; i < devices.length; i += 1) {
      const item = devices[i];
      const name = item.name || item.localName || "";
      if (name !== TARGET_NAME) continue;
      this.deviceMap[item.deviceId] = { deviceId: item.deviceId, name: name || TARGET_NAME, rssi: typeof item.RSSI === "number" ? item.RSSI : -100 };
    }
    const list = Object.keys(this.deviceMap).map((key) => this.deviceMap[key]).sort((left, right) => right.rssi - left.rssi);
    this.setData({ devices: list, statusText: list.length ? "发现 " + list.length + " 个设备" : this.data.statusText });
  },

  connectFromTap(e) {
    const deviceId = e.currentTarget.dataset.deviceId;
    const deviceName = e.currentTarget.dataset.deviceName || TARGET_NAME;
    if (!deviceId || this.data.connecting) return;
    this.stopScan(true);
    this.setData({ connecting: true, statusText: "正在连接 " + deviceName, statusLevel: "busy", deviceLabel: deviceName });
    wx.createBLEConnection({
      deviceId,
      timeout: 10000,
      success: () => { this.activeDeviceId = deviceId; setTimeout(() => this.setupNus(deviceId, deviceName), 400); },
      fail: (err) => this.setData({ connecting: false, statusText: "连接失败", statusLevel: "warn", commandResponse: err.errMsg || "未知错误" })
    });
  },

  setupNus(deviceId, deviceName) {
    this.getServices(deviceId).then((services) => {
      const service = services.find((item) => isSameUuid(item.uuid, NUS_SERVICE_UUID));
      if (!service) throw new Error("未找到 NUS 服务");
      this.serviceId = service.uuid;
      return this.getCharacteristics(deviceId, service.uuid);
    }).then((characteristics) => {
      const tx = characteristics.find((item) => isSameUuid(item.uuid, NUS_TX_UUID));
      const rx = characteristics.find((item) => isSameUuid(item.uuid, NUS_RX_UUID));
      if (!tx || !rx) throw new Error("未找到 NUS 收发特征");
      this.txCharacteristicId = tx.uuid;
      this.rxCharacteristicId = rx.uuid;
      return this.enableNotify(deviceId, this.serviceId, tx.uuid);
    }).then(() => this.setData({ connecting: false, connected: true, deviceId, deviceName, deviceLabel: deviceName, statusText: "已连接，可发送预警", statusLevel: "connected", commandResponse: "已开启板端回复" })).catch((err) => {
      wx.closeBLEConnection({ deviceId });
      this.resetConnection("初始化失败", err.message);
    });
  },

  getServices(deviceId) { return new Promise((resolve, reject) => wx.getBLEDeviceServices({ deviceId, success: (res) => resolve(res.services || []), fail: reject })); },
  getCharacteristics(deviceId, serviceId) { return new Promise((resolve, reject) => wx.getBLEDeviceCharacteristics({ deviceId, serviceId, success: (res) => resolve(res.characteristics || []), fail: reject })); },
  enableNotify(deviceId, serviceId, characteristicId) { return new Promise((resolve, reject) => wx.notifyBLECharacteristicValueChange({ deviceId, serviceId, characteristicId, state: true, success: resolve, fail: reject })); },

  disconnectDevice() {
    const deviceId = this.activeDeviceId;
    if (!deviceId) return this.resetConnection("未连接设备");
    wx.closeBLEConnection({ deviceId, complete: () => this.resetConnection("已断开连接") });
  },

  handleConnectionStateChange(res) {
    if (this.activeDeviceId && res.deviceId === this.activeDeviceId && !res.connected) this.resetConnection("连接已断开");
  },

  sendAlert(e) { this.writeCommand(e.currentTarget.dataset.command); },
  stopAlert() { this.writeCommand("AL CLEAR"); },
  triggerFall() { this.writeCommand("AL FALL"); },

  writeCommand(command) {
    if (!this.data.connected || !this.activeDeviceId || !this.serviceId || !this.rxCharacteristicId) {
      this.setData({ commandResponse: "请先连接设备" });
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

  handleCharacteristicValue(res) {
    if (res.deviceId !== this.activeDeviceId || !isSameUuid(res.characteristicId, this.txCharacteristicId)) return;
    const parts = (this.receiveText + this.arrayBufferToString(res.value)).split("\n");
    this.receiveText = parts.pop() || "";
    for (let i = 0; i < parts.length; i += 1) {
      const line = parts[i].replace(/\r$/, "").trim();
      if (line) this.setData({ commandResponse: line });
    }
  },

  arrayBufferToString(buffer) { return Array.from(new Uint8Array(buffer)).map((value) => String.fromCharCode(value)).join(""); },
  stringToArrayBuffer(text) { const bytes = new Uint8Array(String(text).split("").map((char) => char.charCodeAt(0))); return bytes.buffer; },

  resetConnection(statusText, response) {
    this.activeDeviceId = "";
    this.serviceId = "";
    this.txCharacteristicId = "";
    this.rxCharacteristicId = "";
    this.receiveText = "";
    this.setData({ connecting: false, connected: false, deviceId: "", deviceName: "", deviceLabel: "未连接设备", statusText, statusLevel: "idle", commandResponse: response || "请先扫描并连接 SS928-SmartBag" });
  }
});
