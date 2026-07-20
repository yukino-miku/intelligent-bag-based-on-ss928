const cloudConfig = require("./config/cloud");

App({
  globalData: {
    appName: "智能安全背包"
  },
  onLaunch() {
    if (cloudConfig.enabled && cloudConfig.envId && wx.cloud) {
      wx.cloud.init({ env: cloudConfig.envId, traceUser: true });
    }
  }
});
