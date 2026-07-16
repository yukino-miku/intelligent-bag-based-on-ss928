const LEVEL_NAMES = ["SAFE", "ATTENTION", "CAUTION", "DANGER", "EMERGENCY"];

const emptySide = (side) => ({
  side,
  level: 0,
  name: "SAFE",
  score: null,
  trackId: null,
  className: "",
  distanceM: null,
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
  const receivedAt = ("0" + now.getHours()).slice(-2) + ":" +
    ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
  const item = {
    key: String(now.getTime()) + "-" + frame.side + "-" + (currentState.history || []).length,
    side: frame.side,
    level,
    name: frame.name || LEVEL_NAMES[level],
    score: typeof frame.score === "number" ? frame.score : null,
    trackId: typeof frame.track_id === "number" ? frame.track_id : null,
    className: frame.class || "",
    distanceM: typeof frame.distance_m === "number" ? frame.distance_m : null,
    sourceTs: frame.ts,
    receivedAt
  };
  const next = {
    current: Object.assign({}, currentState.current),
    history: (currentState.history || []).slice()
  };
  next.current[frame.side] = item;
  if (level > 0) {
    next.history.unshift(item);
    next.history = next.history.slice(0, Math.max(1, Number(maxHistory) || 40));
  }
  return next;
};

module.exports = { LEVEL_NAMES, createAlertState, applyAlertFrame };
