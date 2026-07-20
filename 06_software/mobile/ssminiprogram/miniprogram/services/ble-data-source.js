const createBleDataSource = (options) => {
  const getStorage = options && options.getStorage || ((key) => wx.getStorageSync(key));
  return {
    getLatestStatus: () => Promise.resolve({ ok: true, source: "ble", data: getStorage("smartbagSystemStatus") || null, stale: false }),
    getAlarmHistory: () => Promise.resolve({ ok: true, source: "ble", items: getStorage("smartbagAlertHistory") || [], cursor: null }),
    getTrackPoints: () => Promise.resolve({ ok: true, source: "ble", items: getStorage("smartbagTrackPoints") || [], cursor: null }),
    getRealtimePosture: () => Promise.resolve({ ok: true, source: "ble", data: getStorage("smartbagPosture") || null, stale: false })
  };
};

module.exports = { createBleDataSource };
