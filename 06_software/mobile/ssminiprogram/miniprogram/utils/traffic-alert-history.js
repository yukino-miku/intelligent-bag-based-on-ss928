const STORAGE_KEY = "smartbagTrafficAlertHistory";
const DEFAULT_LIMIT = 80;
const DEFAULT_IMAGE_LIMIT = 30;

const normalizeEvent = (input) => {
  const item = input || {};
  const raw = Object.assign({}, item.raw || {}, item);
  delete raw.raw;
  const eventId = String(item.event_id || item.eventId || "");
  return {
    eventId,
    event_id: eventId,
    side: item.side || "unknown",
    level: Math.max(0, Math.min(4, Number(item.level) || 0)),
    className: item.class_name || item.class || "unknown",
    distanceM: numberOrNull(item.distance_m),
    speedMps: numberOrNull(item.speed_mps),
    ttcS: numberOrNull(item.ttc_s),
    effectiveScore: numberOrNull(item.effective_score),
    startTime: Number(item.start_time || item.startTime || Date.now() / 1000),
    lastSeenTime: Number(item.last_seen_time || item.lastSeenTime || item.start_time || Date.now() / 1000),
    localImagePath: item.localImagePath || "",
    imageStatus: item.image_status || item.imageStatus || "pending",
    syncStatus: item.syncStatus || "metadata_only",
    raw
  };
};

const loadHistory = (wxApi) => {
  const stored = wxApi.getStorageSync(STORAGE_KEY);
  return Array.isArray(stored) ? stored.map(normalizeEvent).filter((item) => item.eventId) : [];
};

const saveHistory = (wxApi, items, options) => {
  const config = Object.assign({ limit: DEFAULT_LIMIT, imageLimit: DEFAULT_IMAGE_LIMIT }, options || {});
  const normalized = (items || []).map(normalizeEvent).filter((item) => item.eventId);
  normalized.sort((left, right) => right.startTime - left.startTime);
  const kept = normalized.slice(0, config.limit);
  let imagesKept = 0;
  kept.forEach((item) => {
    if (!item.localImagePath) return;
    imagesKept += 1;
    if (imagesKept > config.imageLimit) {
      if (wxApi.removeSavedFile) wxApi.removeSavedFile({ filePath: item.localImagePath, fail() {} });
      item.localImagePath = "";
      item.imageStatus = "pruned";
    }
  });
  const removed = normalized.slice(config.limit);
  removed.forEach((item) => {
    if (item.localImagePath && wxApi.removeSavedFile) {
      wxApi.removeSavedFile({ filePath: item.localImagePath, fail() {} });
    }
  });
  wxApi.setStorageSync(STORAGE_KEY, kept);
  return kept;
};

const upsertEvent = (wxApi, incoming, options) => {
  const item = normalizeEvent(incoming);
  if (!item.eventId) return loadHistory(wxApi);
  const history = loadHistory(wxApi);
  const index = history.findIndex((current) => current.eventId === item.eventId);
  if (index >= 0) history[index] = Object.assign({}, history[index], item, { raw: Object.assign({}, history[index].raw, item.raw) });
  else history.unshift(item);
  return saveHistory(wxApi, history, options);
};

const syncTrafficAlert = (wxApi, boardApi, incoming, options) => {
  const base = normalizeEvent(incoming);
  upsertEvent(wxApi, base, options);
  if (!base.eventId) return Promise.resolve(base);
  return boardApi.getAlert(base.eventId).then((detail) => {
    const merged = normalizeEvent(Object.assign({}, base.raw, detail, { eventId: base.eventId, syncStatus: "detail_synced" }));
    upsertEvent(wxApi, merged, options);
    if (detail.image_status !== "saved") return merged;
    return boardApi.downloadAlertImage(base.eventId).then((tempFilePath) => new Promise((resolve) => {
      wxApi.saveFile({
        tempFilePath,
        success: (saved) => {
          merged.localImagePath = saved.savedFilePath;
          merged.imageStatus = "saved_local";
          merged.syncStatus = "complete";
          upsertEvent(wxApi, merged, options);
          resolve(merged);
        },
        fail: () => {
          merged.imageStatus = "save_failed";
          merged.syncStatus = "retry_pending";
          upsertEvent(wxApi, merged, options);
          resolve(merged);
        }
      });
    })).catch(() => {
      merged.imageStatus = "download_failed";
      merged.syncStatus = "retry_pending";
      upsertEvent(wxApi, merged, options);
      return merged;
    });
  }).then((item) => {
    const uploader = options && options.cloudUploader;
    if (typeof uploader === "function") Promise.resolve(uploader(item)).catch(() => {});
    return item;
  }).catch(() => {
    base.syncStatus = "retry_pending";
    upsertEvent(wxApi, base, options);
    return base;
  });
};

const numberOrNull = (value) => {
  if (value === null || typeof value === "undefined" || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

module.exports = {
  STORAGE_KEY,
  normalizeEvent,
  loadHistory,
  saveHistory,
  upsertEvent,
  syncTrafficAlert
};
