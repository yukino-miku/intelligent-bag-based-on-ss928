const LEVEL_NAMES = ["SAFE", "ATTENTION", "CAUTION", "DANGER", "EMERGENCY"];

const emptySide = (side) => ({
  side,
  level: 0,
  name: "SAFE",
  score: null,
  trackId: null,
  className: "",
  classWeight: null,
  classSource: "",
  distanceM: null,
  speedMps: null,
  ttcS: null,
  radarTargetId: null,
  radarTrackKey: "",
  associationState: "",
  associationScore: null,
  eventKind: "clear",
  receivedAt: "--"
});

const createAlertState = () => ({
  current: { left: emptySide("left"), right: emptySide("right") },
  history: []
});

const applyAlertFrame = (state, frame, maxHistory) => {
  const currentState = state || createAlertState();
  if (!frame || frame.typ !== "alert" || (frame.side !== "left" && frame.side !== "right")) {
    return currentState;
  }
  const level = Math.max(0, Math.min(4, Number(frame.level) || 0));
  const now = new Date();
  const vxMps = typeof frame.vx_mps === "number" ? frame.vx_mps : null;
  const vzMps = typeof frame.vz_mps === "number" ? frame.vz_mps : null;
  const inferredSpeed = vxMps !== null && vzMps !== null
    ? Math.sqrt(vxMps * vxMps + vzMps * vzMps)
    : null;
  const speedMps = typeof frame.speed_mps === "number" ? frame.speed_mps : inferredSpeed;
  const ttcS = typeof frame.ttc_s === "number" ? frame.ttc_s : null;
  const receivedAt = ("0" + now.getHours()).slice(-2) + ":" +
    ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
  const item = {
    key: String(now.getTime()) + "-" + frame.side + "-" + (currentState.history || []).length,
    side: frame.side,
    level,
    name: frame.name || LEVEL_NAMES[level],
    score: typeof frame.score === "number" ? frame.score : null,
    trackId: (typeof frame.track_id === "number" || typeof frame.track_id === "string") ? frame.track_id : null,
    className: frame.class || "",
    classWeight: typeof frame.class_weight === "number" ? frame.class_weight : null,
    classSource: frame.class_source || "",
    distanceM: typeof frame.distance_m === "number" ? frame.distance_m : null,
    speedMps,
    speedText: speedMps === null ? "--" : speedMps.toFixed(1) + "m/s",
    ttcS,
    ttcText: ttcS === null ? "--" : ttcS.toFixed(1) + "s",
    radarTargetId: typeof frame.radar_target_id === "number" ? frame.radar_target_id : null,
    radarTrackKey: frame.radar_track_key || "",
    associationState: frame.association_state || "",
    associationScore: typeof frame.association_score === "number" ? frame.association_score : null,
    eventKind: frame.event_kind || (level > 0 ? "alert" : "clear"),
    sourceTs: frame.ts,
    receivedAt
  };
  const next = {
    current: Object.assign({}, currentState.current),
    history: (currentState.history || []).slice()
  };
  next.current[frame.side] = item;
  if (level > 0 && item.eventKind !== "heartbeat") {
    next.history.unshift(item);
    next.history = next.history.slice(0, Math.max(1, Number(maxHistory) || 40));
  }
  return next;
};

module.exports = { LEVEL_NAMES, createAlertState, applyAlertFrame };
