const assert = require("assert");
const path = require("path");
const { createDeviceDataService } = require(path.join(__dirname, "../miniprogram/services/device-data-service"));

const ble = {
  getLatestStatus: () => Promise.resolve({ source: "ble", data: { levels: { left: 2 } } }),
  getRealtimePosture: () => Promise.resolve({ source: "ble", data: null }),
  getTrackPoints: () => Promise.resolve({ source: "ble", items: [] }),
  getAlarmHistory: () => Promise.resolve({ source: "ble", items: [{ level: 2 }] })
};

const disabledCloud = { enabled: () => false };
createDeviceDataService({ cloud: disabledCloud, ble }).getLatestStatus().then((result) => {
  assert.strictEqual(result.source, "ble");
  const failingCloud = {
    enabled: () => true,
    getLatestStatus: () => Promise.reject(new Error("offline")),
    getRealtimePosture: () => Promise.reject(new Error("offline")),
    getTrackPoints: () => Promise.reject(new Error("offline")),
    getAlarmHistory: () => Promise.reject(new Error("offline")),
    getDailyPosture: () => Promise.reject(new Error("offline"))
  };
  return createDeviceDataService({ cloud: failingCloud, ble }).getAlarmHistory();
}).then((result) => {
  assert.strictEqual(result.source, "ble");
  assert.strictEqual(result.cloudError, "offline");
  console.log("device data service tests passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
