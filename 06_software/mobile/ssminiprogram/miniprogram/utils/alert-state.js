const LEVEL_NAMES = ["安全", "提醒", "警戒", "危险", "紧急"];
const DEFAULT_HISTORY_LIMIT = 100;
const DUPLICATE_WINDOW_MS = 2000;

const emptySide = (side) => ({
  side,
  level: 0,
  name: "SAFE",
  score: null,
  trackId: null,
  className: "",
  distanceM: null,
  ttcS: null,
  source: "unknown",
  sourceId: null,
  effectiveLevel: 0,
  hapticLevel: 0,
  lightMode: "off",
  audioClip: null,
  audioEnabled: false,
  clearReason: null,
  sourceTs: null,
  dataSource: "BLE",
  receivedAt: "--"
});

const createAlertState = () => ({
  current: { left: emptySide("left"), right: emptySide("right") },
  history: []
});

const valueOrNull = (value) => typeof value === "number" ? value : null;

const applyAlertFrame = (state, frame, maxHistory, dataSource) => {
  const currentState = state || createAlertState();
  if (!frame || frame.typ !== "alert" || (frame.side !== "left" && frame.side !== "right")) {
    return currentState;
  }
  if (frame.event_kind === "heartbeat") return currentState;
  const level = Math.max(0, Math.min(4, Number(frame.level) || 0));
  const now = new Date();
  const receivedAt = ("0" + now.getHours()).slice(-2) + ":" +
    ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
  const item = {
    key: String(now.getTime()) + "-" + frame.side + "-" + (currentState.history || []).length,
    side: frame.side,
    level,
    name: frame.name_zh || LEVEL_NAMES[level],
    rawName: frame.name || "",
    score: valueOrNull(frame.score),
    trackId: valueOrNull(frame.track_id),
    className: frame.class || "",
    distanceM: valueOrNull(frame.distance_m),
    ttcS: valueOrNull(frame.ttc_s),
    source: frame.source || "unknown",
    sourceId: frame.source_id || null,
    effectiveLevel: typeof frame.effective_level === "number" ? frame.effective_level : level,
    hapticLevel: typeof frame.haptic_level === "number" ? frame.haptic_level : level,
    lightMode: frame.light_mode || "off",
    audioClip: frame.audio_clip || null,
    audioEnabled: Boolean(frame.audio_enabled),
    clearReason: frame.clear_reason || null,
    sourceTs: frame.ts,
    receivedTs: typeof frame.received_ts === "number" ? frame.received_ts : null,
    receivedAt,
    receivedEpochMs: now.getTime(),
    dataSource: dataSource || "BLE",
    eventKind: frame.event_kind || "state_change"
  };
  item.signature = [
    item.side, item.level, item.effectiveLevel, item.hapticLevel, item.lightMode,
    item.audioClip || "", item.source, item.sourceId || "", item.clearReason || ""
  ].join("|");
  const next = {
    current: Object.assign({}, currentState.current),
    history: (currentState.history || []).slice()
  };
  next.current[frame.side] = item;
  const isStateChange = item.eventKind === "state_change";
  const shouldPersist = isStateChange && (level > 0 || Boolean(item.clearReason));
  const newest = next.history[0];
  const isDuplicate = Boolean(
    newest && newest.signature === item.signature &&
    now.getTime() - Number(newest.receivedEpochMs || 0) < DUPLICATE_WINDOW_MS
  );
  if (shouldPersist && !isDuplicate) {
    next.history.unshift(item);
    next.history = next.history.slice(0, Math.max(1, Number(maxHistory) || DEFAULT_HISTORY_LIMIT));
  }
  return next;
};

module.exports = { LEVEL_NAMES, DEFAULT_HISTORY_LIMIT, createAlertState, applyAlertFrame };
