const FUNCTION_NAME = "smartbag-app-api";

const call = (action, data) => wx.cloud.callFunction({
  name: FUNCTION_NAME,
  data: Object.assign({ action }, data || {})
}).then((response) => {
  const result = response && response.result;
  if (!result || result.ok !== true) {
    const error = (result && result.error) || { code: "CLOUD_CALL_FAILED", message: "CLOUD_CALL_FAILED" };
    return Promise.reject(error);
  }
  return result.data;
});

const getLatestStatus = () => call("getLatestStatus");
const getRealtimePosture = () => call("getRealtimePosture");
const getDailyPosture = (date) => call("getDailyPosture", { date });
const getTrackPoints = () => call("getTrackPoints");
const getAlarmHistory = () => call("getAlarmHistory");
const saveTrafficAlert = (item) => {
  const alert = Object.assign({}, item.raw || {}, {
    event_id: item.eventId,
    level: item.level,
    local_image_uploaded: false
  });
  const upload = item.localImagePath && wx.cloud && wx.cloud.uploadFile
    ? wx.cloud.uploadFile({
      cloudPath: "traffic-alerts/" + encodeURIComponent(item.eventId) + ".jpg",
      filePath: item.localImagePath
    }).then((result) => { alert.image_file_id = result.fileID; alert.local_image_uploaded = true; })
    : Promise.resolve();
  return upload.then(() => call("saveTrafficAlert", { alert }));
};

module.exports = {
  getAlarmHistory,
  getDailyPosture,
  getLatestStatus,
  getRealtimePosture,
  getTrackPoints,
  saveTrafficAlert
};
