const cloudDataSource = require("../../services/cloud-data-source");
const postureUtils = require("../../utils/posture-utils");
const REFRESH_INTERVAL_MS = 1000;
const OFFLINE_AFTER_MS = 60000;
Page({
  data: { deviceLabel: "SS928-SmartBag", statusText: "设备离线", statusLevel: "offline", postureKey: "unknown", postureText: "暂无数据", postureDetail: "未收到设备的最新姿态状态", updateTime: "--:--:--", showReminder: false, reminderHistory: [] },
  onShow() { this.loadRealtimePosture(); this.startRefresh(); },
  onHide() { this.stopRefresh(); },
  onUnload() { this.stopRefresh(); },
  goAnalysis() { wx.redirectTo({ url: "/pages/posture-analysis/index" }); },
  startRefresh() { if (!this.refreshTimer) this.refreshTimer = setInterval(() => this.loadRealtimePosture(), REFRESH_INTERVAL_MS); },
  stopRefresh() { if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; } },
  loadRealtimePosture() {
    return Promise.all([cloudDataSource.getRealtimePosture(), cloudDataSource.getAlarmHistory()]).then(([statusResult, alarmResult]) => {
      const display = postureUtils.toRealtimeDisplay(postureUtils.normalizeRealtimePosture(statusResult && statusResult.posture), Date.now(), OFFLINE_AFTER_MS);
      const reminderHistory = ((alarmResult && alarmResult.items) || []).map(postureUtils.normalizeHunchReminder).filter(Boolean).slice(0, 10);
      this.setData(Object.assign(display, { reminderHistory }));
    }).catch((error) => console.error("realtime posture cloud read failed", error && error.code));
  }
});
