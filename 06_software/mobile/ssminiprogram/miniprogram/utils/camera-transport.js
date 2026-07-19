const DEFAULT_CAMERA_CONFIG = {
  boardHost: "",
  videoPort: 8080,
  accessToken: "",
  refreshFps: 5,
  viewMode: "overlay",
  leftPath: "/api/v1/camera/left",
  rightPath: "/api/v1/camera/right"
};

const normalizeConfig = (input) => {
  const source = input || {};
  const config = Object.assign({}, DEFAULT_CAMERA_CONFIG, source);
  config.boardHost = String(config.boardHost || "").trim().replace(/\/+$/, "");
  config.videoPort = Math.max(1, Math.min(65535, Number(config.videoPort) || 8080));
  config.refreshFps = Math.max(1, Math.min(10, Number(config.refreshFps) || 5));
  config.viewMode = config.viewMode === "raw" ? "raw" : "overlay";
  config.leftPath = normalizePath(config.leftPath, DEFAULT_CAMERA_CONFIG.leftPath);
  config.rightPath = normalizePath(config.rightPath, DEFAULT_CAMERA_CONFIG.rightPath);
  return config;
};

const normalizePath = (value, fallback) => {
  const path = String(value || fallback).trim().replace(/\/+$/, "");
  return path.charAt(0) === "/" ? path : "/" + path;
};

const boardBaseUrl = (config) => {
  const normalized = normalizeConfig(config);
  if (!normalized.boardHost) {
    return "";
  }
  if (/^https?:\/\//i.test(normalized.boardHost)) {
    const parsed = normalized.boardHost.replace(/:\d+$/, "");
    return parsed + ":" + normalized.videoPort;
  }
  return "http://" + normalized.boardHost + ":" + normalized.videoPort;
};

const cameraPath = (config, side) => side === "left" ? config.leftPath : config.rightPath;

const appendQuery = (url, params) => {
  const parts = [];
  Object.keys(params).forEach((key) => {
    if (params[key] !== "" && params[key] !== null && typeof params[key] !== "undefined") {
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(params[key])));
    }
  });
  return parts.length ? url + (url.indexOf("?") === -1 ? "?" : "&") + parts.join("&") : url;
};

const normalizeCameraStatus = (input) => {
  const status = input || {};
  const online = status.online === true;
  const active = online && status.active === true;
  let frameState = String(status.frame_state || "").toLowerCase();
  if (!["live", "cached", "offline"].includes(frameState)) {
    frameState = online ? (active ? "live" : "cached") : "offline";
  }
  const statusText = frameState === "live" ? "正在采集" :
    frameState === "cached" ? "缓存帧" : "离线";
  return {
    online,
    active,
    frameState,
    statusText,
    captureFps: typeof status.capture_fps !== "undefined" ? status.capture_fps : status.effective_fps
  };
};

class CameraTransport {
  constructor(config, wxApi) {
    this.config = normalizeConfig(config);
    this.wxApi = wxApi;
  }

  updateConfig(config) {
    this.config = normalizeConfig(config);
  }
}

class SnapshotHttpTransport extends CameraTransport {
  snapshotUrl(side, cacheKey) {
    const base = boardBaseUrl(this.config);
    if (!base) {
      return "";
    }
    return appendQuery(base + cameraPath(this.config, side) + "/snapshot.jpg", {
      view: this.config.viewMode,
      token: this.config.accessToken,
      t: cacheKey
    });
  }

  mjpegUrl(side) {
    const base = boardBaseUrl(this.config);
    return base ? appendQuery(base + cameraPath(this.config, side) + "/mjpeg", {
      view: this.config.viewMode,
      token: this.config.accessToken
    }) : "";
  }

  status(side) {
    const base = boardBaseUrl(this.config);
    if (!base || !this.wxApi) {
      return Promise.reject(new Error("boardHost is not configured"));
    }
    const url = appendQuery(base + cameraPath(this.config, side) + "/status", {
      token: this.config.accessToken
    });
    return new Promise((resolve, reject) => {
      this.wxApi.request({
        url,
        method: "GET",
        timeout: 1500,
        success: (response) => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve(response.data || {});
          } else {
            reject(new Error("HTTP " + response.statusCode));
          }
        },
        fail: reject
      });
    });
  }
}

module.exports = {
  DEFAULT_CAMERA_CONFIG,
  CameraTransport,
  SnapshotHttpTransport,
  normalizeConfig,
  boardBaseUrl,
  normalizeCameraStatus
};
