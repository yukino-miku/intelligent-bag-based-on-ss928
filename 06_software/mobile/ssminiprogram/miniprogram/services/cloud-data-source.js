const defaultConfig = require("../config/cloud");

const withTimeout = (promise, timeoutMs) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("CloudBase request timeout")), timeoutMs);
  promise.then((value) => {
    clearTimeout(timer);
    resolve(value);
  }).catch((error) => {
    clearTimeout(timer);
    reject(error);
  });
});

const createCloudDataSource = (options) => {
  const config = Object.assign({}, defaultConfig, options && options.config || {});
  const callFunction = options && options.callFunction || ((request) => wx.cloud.callFunction(request));
  const call = (action, extra) => {
    if (!config.enabled || !config.deviceId) return Promise.reject(new Error("CloudBase disabled or deviceId missing"));
    const data = Object.assign({ action, deviceId: config.deviceId }, extra || {});
    return withTimeout(callFunction({ name: config.functionName, data }), config.timeoutMs).then((result) => {
      const response = result && typeof result.result !== "undefined" ? result.result : result;
      if (!response || response.ok !== true) throw new Error(response && response.error || "CloudBase request failed");
      return response;
    });
  };
  return {
    enabled: () => Boolean(config.enabled && config.deviceId),
    getLatestStatus: () => call("getLatestStatus"),
    getRealtimePosture: () => call("getRealtimePosture"),
    getDailyPosture: (date) => call("getDailyPosture", { date }),
    getTrackPoints: (cursor, limit) => call("getTrackPoints", { cursor: cursor || null, limit: limit || 50 }),
    getAlarmHistory: (cursor, limit) => call("getAlarmHistory", { cursor: cursor || null, limit: limit || 50 })
  };
};

module.exports = { createCloudDataSource, withTimeout };
