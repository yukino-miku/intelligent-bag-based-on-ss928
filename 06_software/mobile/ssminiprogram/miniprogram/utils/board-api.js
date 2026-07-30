const { normalizeConfig, boardBaseUrl } = require("./camera-transport");

const appendToken = (url, token) => {
  if (!token) return url;
  return url + (url.indexOf("?") === -1 ? "?" : "&") + "token=" + encodeURIComponent(token);
};

class BoardApi {
  constructor(config, wxApi) {
    this.config = normalizeConfig(config || {});
    this.wxApi = wxApi;
  }

  updateConfig(config) {
    this.config = normalizeConfig(config || {});
  }

  request(path, method, data) {
    const base = boardBaseUrl(this.config);
    if (!base) return Promise.reject(new Error("boardHost is not configured"));
    return new Promise((resolve, reject) => {
      this.wxApi.request({
        url: base + path,
        method: method || "GET",
        data: data || undefined,
        timeout: 2500,
        header: Object.assign(
          { "content-type": "application/json" },
          this.config.accessToken ? { "X-SmartBag-Token": this.config.accessToken } : {}
        ),
        success: (response) => {
          if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data || {});
          else reject(new Error((response.data && response.data.error) || ("HTTP " + response.statusCode)));
        },
        fail: reject
      });
    });
  }

  getRuntimeSettings() {
    return this.request("/api/v1/settings/runtime", "GET");
  }

  patchRuntimeSettings(patch) {
    return this.request("/api/v1/settings/runtime", "PATCH", patch);
  }

  resetRuntimeSettings() {
    return this.request("/api/v1/settings/runtime/reset", "POST", {});
  }

  getFusionStatus() {
    return this.request("/api/v1/fusion/status", "GET");
  }

  getAlertHistory(offset, limit, minLevel) {
    return this.request(
      "/api/v1/alerts/history?offset=" + (Number(offset) || 0) +
      "&limit=" + (Number(limit) || 50) +
      "&min_level=" + (Number(minLevel) || 3),
      "GET"
    );
  }

  getAlert(eventId) {
    return this.request("/api/v1/alerts/" + encodeURIComponent(eventId), "GET");
  }

  downloadAlertImage(eventId) {
    const base = boardBaseUrl(this.config);
    if (!base) return Promise.reject(new Error("boardHost is not configured"));
    const url = base + "/api/v1/alerts/" + encodeURIComponent(eventId) + "/image.jpg";
    return new Promise((resolve, reject) => {
      this.wxApi.downloadFile({
        url,
        header: this.config.accessToken ? { "X-SmartBag-Token": this.config.accessToken } : {},
        timeout: 5000,
        success: (response) => response.statusCode === 200
          ? resolve(response.tempFilePath)
          : reject(new Error("HTTP " + response.statusCode)),
        fail: reject
      });
    });
  }
}

module.exports = { BoardApi, appendToken };
