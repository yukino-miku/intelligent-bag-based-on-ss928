const { envList } = require("./envList");

App({
  globalData: {
    appName: "智能安全背包"
  },
  onLaunch() {
    const configured = Array.isArray(envList) && envList.length ? envList[0] : null;
    const env = configured && (configured.envId || configured.id || configured.env);
    if (wx.cloud && env) {
      wx.cloud.init({ env, traceUser: true });
      this.globalData.cloudEnabled = true;
    } else {
      this.globalData.cloudEnabled = false;
    }
  }
});
