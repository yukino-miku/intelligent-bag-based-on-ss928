const cloudDataSource = require("../../services/cloud-data-source");
const postureUtils = require("../../utils/posture-utils");
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

Page({
  data: {
    deviceLabel: "SS928-SmartBag",
    statusText: "等待云端数据",
    statusLevel: "offline",
    stats: { goodPercent: 100, badPercent: 0, wearingDuration: "0秒", goodDuration: "0秒", badDuration: "0秒", updatedTime: "--:--:--", hasValidData: true },
    dataMessage: "今日暂无有效姿态数据"
  },
  onShow() { this.loadDailyPosture(); this.startRefresh(); },
  onHide() { this.stopRefresh(); },
  onUnload() { this.stopRefresh(); },
  goMonitor() { wx.redirectTo({ url: "/pages/posture-live/index" }); },
  startRefresh() { if (!this.refreshTimer) this.refreshTimer = setInterval(() => this.loadDailyPosture(), REFRESH_INTERVAL_MS); },
  stopRefresh() { if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; } },
  loadDailyPosture() {
    return cloudDataSource.getDailyPosture(postureUtils.getLocalDate()).then((result) => {
      const posture = postureUtils.normalizeDailyPosture(result && result.posture);
      if (!posture || !posture.hasValidData) {
        this.setData({
          statusText: "设备在线", statusLevel: "connected", dataMessage: "今日暂无有效姿态数据",
          stats: { goodPercent: 100, badPercent: 0, wearingDuration: "0秒", goodDuration: "0秒", badDuration: "0秒", updatedTime: "--:--:--", hasValidData: true }
        }, () => this.drawPosturePie());
        return;
      }
      this.setData({
        statusText: "设备在线", statusLevel: "connected", dataMessage: "",
        stats: { goodPercent: posture.goodPercent, badPercent: posture.badPercent, wearingDuration: postureUtils.formatDuration(posture.wearingSeconds), goodDuration: postureUtils.formatDuration(posture.goodSeconds), badDuration: postureUtils.formatDuration(posture.badSeconds), updatedTime: postureUtils.formatClock(posture.updatedAtMs), hasValidData: true }
      }, () => this.drawPosturePie());
    }).catch((error) => { console.error("daily posture cloud read failed", error && error.code); this.setData({ dataMessage: "数据更新失败" }); });
  },
  drawPosturePie() {
    if (typeof wx === "undefined" || !wx.createCanvasContext) return;
    const ctx = wx.createCanvasContext("posturePie", this); const center = 90; const radius = 74; const startAngle = -Math.PI / 2; const stats = this.data.stats; const goodAngle = Math.PI * 2 * stats.goodPercent / 100;
    ctx.setFillStyle("#eef3f7"); ctx.beginPath(); ctx.arc(center, center, radius, 0, Math.PI * 2); ctx.fill();
    if (stats.hasValidData) { ctx.setFillStyle("#18a058"); ctx.beginPath(); ctx.moveTo(center, center); ctx.arc(center, center, radius, startAngle, startAngle + goodAngle); ctx.closePath(); ctx.fill(); ctx.setFillStyle("#e5534b"); ctx.beginPath(); ctx.moveTo(center, center); ctx.arc(center, center, radius, startAngle + goodAngle, startAngle + Math.PI * 2); ctx.closePath(); ctx.fill(); }
    ctx.setFillStyle("#ffffff"); ctx.beginPath(); ctx.arc(center, center, 42, 0, Math.PI * 2); ctx.fill(); ctx.setFillStyle("#17212b"); ctx.setFontSize(16); ctx.setTextAlign("center"); ctx.fillText("今日", center, center - 4); ctx.setFontSize(13); ctx.fillText("姿态", center, center + 18); ctx.draw();
  }
});
