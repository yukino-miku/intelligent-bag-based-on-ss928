const { createBleDataSource } = require("./ble-data-source");
const { createCloudDataSource } = require("./cloud-data-source");

const createDeviceDataService = (options) => {
  const cloud = options && options.cloud || createCloudDataSource();
  const ble = options && options.ble || createBleDataSource();
  const fallback = (cloudMethod, bleMethod, args) => {
    if (!cloud.enabled()) return ble[bleMethod].apply(ble, args || []);
    return cloud[cloudMethod].apply(cloud, args || []).catch((error) => {
      return ble[bleMethod].apply(ble, args || []).then((result) => Object.assign({}, result, { cloudError: error.message }));
    });
  };
  return {
    getLatestStatus: () => fallback("getLatestStatus", "getLatestStatus"),
    getRealtimePosture: () => fallback("getRealtimePosture", "getRealtimePosture"),
    getTrackPoints: (cursor, limit) => fallback("getTrackPoints", "getTrackPoints", [cursor, limit]),
    getAlarmHistory: (cursor, limit) => fallback("getAlarmHistory", "getAlarmHistory", [cursor, limit]),
    getDailyPosture: (date) => cloud.getDailyPosture(date)
  };
};

module.exports = { createDeviceDataService };
