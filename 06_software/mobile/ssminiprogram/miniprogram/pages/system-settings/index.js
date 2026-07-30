const { BoardApi } = require("../../utils/board-api");

const STORAGE_KEY = "smartbagCameraConfig";
const SIDE_FIELDS = [
  { key: "camera_mount_y_m", label: "摄像头高度 m" },
  { key: "radar_mount_y_m", label: "雷达高度 m" },
  { key: "camera_mount_x_m", label: "摄像头横向偏移 m" },
  { key: "radar_mount_x_m", label: "雷达横向偏移 m" },
  { key: "camera_yaw_deg", label: "摄像头 yaw deg" },
  { key: "camera_pitch_deg", label: "摄像头 pitch deg" },
  { key: "radar_yaw_deg", label: "雷达 yaw deg" },
  { key: "camera_horizontal_fov_deg", label: "摄像头水平 FOV deg" }
];
const ASSOCIATION_FIELDS = [
  { key: "projection_half_width_px", label: "雷达投影半宽 px" },
  { key: "projection_half_width_ratio", label: "投影比例半宽" },
  { key: "bbox_expand_ratio", label: "检测框扩展比例" },
  { key: "association_max_time_delta_s", label: "最大时间差 s" },
  { key: "max_center_distance_px", label: "最大中心距离 px" },
  { key: "max_association_cost", label: "最大匹配代价" },
  { key: "ambiguity_cost_gap", label: "歧义代价间隔" }
];
const RISK_FIELDS = [
  { key: "bicycle_risk_multiplier", label: "自行车权重" },
  { key: "motorcycle_risk_multiplier", label: "摩托/电动车权重" },
  { key: "car_risk_multiplier", label: "汽车权重" },
  { key: "truck_risk_multiplier", label: "卡车权重" },
  { key: "bus_risk_multiplier", label: "公交权重" },
  { key: "unknown_risk_multiplier", label: "未知车型权重" }
];

Page({
  data: {
    sideFields: SIDE_FIELDS,
    associationFields: ASSOCIATION_FIELDS,
    riskFields: RISK_FIELDS,
    settings: {
      left: {}, right: {}, association: {}, risk: {},
      effective_parameters: { left: {}, right: {} }
    },
    version: "--",
    loading: false,
    statusText: "等待读取板端参数",
    online: false
  },

  onLoad() {
    this.api = new BoardApi(wx.getStorageSync(STORAGE_KEY) || {}, wx);
  },

  onShow() {
    this.loadSettings();
  },

  loadSettings() {
    this.setData({ loading: true, statusText: "正在读取" });
    this.api.getRuntimeSettings().then((settings) => {
      this.setData({ settings, version: settings.version, loading: false, online: true, statusText: "参数已同步" });
    }).catch((error) => {
      this.setData({ loading: false, online: false, statusText: "板端离线: " + (error.errMsg || error.message || "连接失败") });
    });
  },

  updateValue(e) {
    const section = e.currentTarget.dataset.section;
    const key = e.currentTarget.dataset.key;
    if (!section || !key) return;
    this.setData({ ["settings." + section + "." + key]: e.detail.value });
  },

  updateSensitivity(e) {
    this.setData({ "settings.risk.warning_sensitivity": Number(e.detail.value).toFixed(2) });
  },

  saveSettings() {
    const settings = this.data.settings || {};
    const payload = {
      left: numericObject(settings.left),
      right: numericObject(settings.right),
      association: numericObject(settings.association),
      risk: numericObject(settings.risk)
    };
    this.setData({ loading: true, statusText: "正在应用" });
    this.api.patchRuntimeSettings(payload).then((applied) => {
      this.setData({ settings: applied, version: applied.version, loading: false, online: true, statusText: "已原子应用并持久化" });
    }).catch((error) => {
      this.setData({ loading: false, statusText: "应用失败: " + (error.errMsg || error.message || "参数校验失败") });
    });
  },

  resetSettings() {
    this.setData({ loading: true, statusText: "正在恢复默认值" });
    this.api.resetRuntimeSettings().then((applied) => {
      this.setData({ settings: applied, version: applied.version, loading: false, online: true, statusText: "默认值已恢复" });
    }).catch((error) => {
      this.setData({ loading: false, statusText: "恢复失败: " + (error.errMsg || error.message || "连接失败") });
    });
  }
});

const numericObject = (source) => {
  const output = {};
  Object.keys(source || {}).forEach((key) => { output[key] = Number(source[key]); });
  return output;
};

module.exports = { SIDE_FIELDS, ASSOCIATION_FIELDS, RISK_FIELDS, numericObject };
