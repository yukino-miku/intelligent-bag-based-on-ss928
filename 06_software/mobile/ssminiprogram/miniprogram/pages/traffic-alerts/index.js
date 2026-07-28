const { BoardApi } = require("../../utils/board-api");
const historyStore = require("../../utils/traffic-alert-history");

Page({
  data: { events: [], loading: false, statusText: "本地记录", selected: null },

  onLoad() {
    this.api = new BoardApi(wx.getStorageSync("smartbagCameraConfig") || {}, wx);
  },

  onShow() {
    this.loadLocal();
    this.syncHistory();
  },

  loadLocal() {
    this.setData({ events: formatEvents(historyStore.loadHistory(wx)) });
  },

  syncHistory() {
    this.setData({ loading: true, statusText: "正在同步板端" });
    this.api.getAlertHistory(0, 50, 3).then((result) => {
      const events = result.events || [];
      events.forEach((item) => historyStore.upsertEvent(wx, item));
      return events.reduce(
        (chain, item) => chain.then(() => historyStore.syncTrafficAlert(wx, this.api, item)),
        Promise.resolve()
      );
    }).then(() => {
      this.setData({ loading: false, statusText: "板端同步完成", events: formatEvents(historyStore.loadHistory(wx)) });
    }).catch(() => this.setData({ loading: false, statusText: "板端不可访问，显示本地记录" }));
  },

  retrySync(e) {
    const eventId = e.currentTarget.dataset.id;
    const item = historyStore.loadHistory(wx).find((entry) => entry.eventId === eventId);
    if (!item) return;
    this.setData({ loading: true, statusText: "正在重试图片" });
    historyStore.syncTrafficAlert(wx, this.api, item).then(() => {
      this.setData({ loading: false, statusText: "重试完成", events: formatEvents(historyStore.loadHistory(wx)) });
    });
  },

  previewImage(e) {
    const path = e.currentTarget.dataset.path;
    if (path) wx.previewImage({ current: path, urls: [path] });
  }
});

const formatEvents = (events) => events.map((item) => Object.assign({}, item, {
  sideText: item.side === "left" ? "左侧" : "右侧",
  timeText: new Date(item.startTime * 1000).toLocaleString(),
  distanceText: item.distanceM === null ? "--" : item.distanceM.toFixed(1) + " m",
  speedText: item.speedMps === null ? "--" : item.speedMps.toFixed(1) + " m/s",
  ttcText: item.ttcS === null ? "--" : item.ttcS.toFixed(1) + " s"
}));

module.exports = { formatEvents };
