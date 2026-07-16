# IMU Fall / Impact Detector

Pure Python fall and impact detection for an embedded Linux program. Input is one
IMU frame at a time:

```text
t, ax, ay, az, gx, gy, gz
```

Units:

- `t`: seconds, monotonic timestamp preferred
- `ax/ay/az`: g
- `gx/gy/gz`: deg/s

The default configuration targets 50 Hz sampling and uses a threshold + finite
state machine design.

## Files

- `imu_fall_detector.py`: importable detector module.
- `run_detector.py`: stdin JSONL/CSV runner that prints compact JSON events.
- `config.example.json`: tunable thresholds.
- `tests/`: stdlib `unittest` coverage for fall, impact-only, filtering, JSON,
  and stdin parsing.

## State Machine

States are fixed to:

```text
NORMAL -> POSSIBLE_FALL -> IMPACT -> POSTURE_CHANGED -> FALL_CONFIRMED
NORMAL -> IMPACT -> IMPACT_ONLY
```

The detector emits JSON only when it enters an event state. Normal frames return
no event.

- `POSSIBLE_FALL`: low-g or fast rotation plus jerk is held long enough.
- `IMPACT`: acceleration, jerk, or gyro exceeds impact thresholds.
- `POSTURE_CHANGED`: gravity/posture vector changes beyond `posture_delta_deg`
  after impact and is held for `posture_hold_s`.
- `FALL_CONFIRMED`: posture changed and the IMU becomes stationary.
- `IMPACT_ONLY`: impact happened but no fall posture followed before timeout.

## Metrics

Each update computes:

- sliding-window filtered accel and gyro
- resultant acceleration, `accel_g`
- resultant angular velocity, `gyro_dps`
- vector jerk, `jerk_gps`
- roll and pitch from the gravity vector
- posture angle change versus the pre-event baseline
- stationary detection from accel near 1 g, low gyro, and low jerk

Raw resultant values are also included in event metrics so impact spikes are not
hidden by the smoothing window.

## Import API

```python
from imu_fall_detector import DetectorConfig, FallImpactDetector, ImuSample

cfg = DetectorConfig(sample_hz=50.0)
detector = FallImpactDetector(cfg)

sample = ImuSample(t=123.0, ax=0.0, ay=0.0, az=1.0, gx=0.0, gy=0.0, gz=0.0)
for event in detector.update(sample):
    handle_event(event)

features = detector.last_features  # latest filtered metrics for logging
```

Compact JSON output:

```python
from imu_fall_detector import event_to_json
print(event_to_json(event))
```

## Runner

CSV input:

```sh
printf '0,0,0,1,0,0,0\n0.02,0,0,3.2,0,0,0\n' \
  | python3 run_detector.py --config config.example.json
```

JSONL input:

```sh
printf '{"t":0,"a":[0,0,1],"w":[0,0,0]}\n' \
  | python3 run_detector.py
```

Built-in synthetic fall demo:

```sh
python3 run_detector.py --simulate
```

Example event shape:

```json
{"type":"imu_fall_event","event":"fall_confirmed","state":"FALL_CONFIRMED","severity":"high","reason":"posture changed and became stationary","t":1.08,"sample_hz":50.0,"metrics":{"accel_g":1.0,"gyro_dps":0.0,"jerk_gps":0.0,"raw_accel_g":1.0,"raw_gyro_dps":0.0,"raw_jerk_gps":0.0,"roll_deg":90.0,"pitch_deg":0.0,"posture_delta_deg":90.0,"stationary":true,"stationary_time_s":0.46},"sample":{"accel_unit":"g","gyro_unit":"deg/s","a":[0.0,1.0,0.0],"g":[0.0,0.0,0.0]},"fsm":{"fall_started_t":0.58,"impact_t":0.68,"state_since_t":1.08}}
```

## SS928 Integration Notes

If your main program already reads BMI270 data, construct `ImuSample` directly
from the measured six-axis values. For the existing BMI270 backpack JSON stream,
`a` is acceleration in g and `w` is angular velocity in deg/s, so it can feed the
runner's JSONL parser directly once a timestamp `t` is added.

Keep the first board test simple:

1. Run `python3 run_detector.py --simulate` to verify Python/runtime behavior.
2. Pipe a short real IMU log into `run_detector.py` and inspect JSON events.
3. Tune `config.example.json` thresholds with real mounting orientation and use
   case data.

These defaults are starting thresholds, not a medical or safety certification.
Tune them with real falls, non-fall impacts, and ordinary use motion.

## Tests

```sh
python -m unittest discover -s tests
```

From the workspace root:

```sh
python -m unittest discover -s 06_software/board_runtime/imu_fall_detector/tests
```
