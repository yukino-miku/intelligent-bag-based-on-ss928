# BMI270 Backpack Posture Calibration Analysis v1

Date: 2026-07-05
Data source: board `/root/bmi270_calibration`, copied to `work/linux_bmi270_backpack/calibration_data`.

## Data Files

- bend_pickup: 2 files, 3004 rows
- hunch: 2 files, 1504 rows
- hunch_walk: 2 files, 3004 rows
- straight: 4 files, 3008 rows
- straight_walk: 2 files, 3004 rows
- Total: 12 files, 13524 rows

## Mounting Zero

Using all `straight` captures after the first second:

- `roll_zero_deg = 0.080`
- `pitch_zero_deg = -10.605`
- `yaw_zero_deg = 0.0`

Runtime corrected values:

- `roll_deg = raw_roll_deg - 0.080`
- `pitch_deg = raw_pitch_deg - (-10.605)`
- `yaw_deg = raw_yaw_deg - 0.0`

## Final v1 Threshold

Automatic separation initially suggested `hunch_pitch_deg = -12.5`, but that was a bit sensitive.
A very conservative `-18.0` avoided false positives but missed the milder `hunch_02` sample.
Final v1 uses the middle ground requested by the user:

- Trigger `HUNCH` when corrected `pitch_deg < -15.5`
- Require continuous hold: `3.0 s`
- Motion gate: `gyro_dps <= 30.0`
- Acceleration gate: `0.75 <= accel_g <= 1.25`
- Disable old generic tilt/speed/impact/freefall alerts in `config.ss928_ble.json` for now to avoid noisy first-version posture alarms.

## Replay Result with `hunch_pitch_deg = -15.5`

| file | mode | HUNCH events | first event | last event |
| --- | --- | ---: | --- | --- |
| bend_pickup_01.csv | bend_pickup | 0 | - | - |
| bend_pickup_02.csv | bend_pickup | 0 | - | - |
| hunch_01.csv | hunch | 3 | 3.02s | 13.02s |
| hunch_02.csv | hunch | 2 | 8.48s | 13.48s |
| hunch_walk_01.csv | hunch_walk | 3 | 3.02s | 18.98s |
| hunch_walk_02.csv | hunch_walk | 3 | 3.02s | 13.02s |
| straight_01.csv | straight | 0 | - | - |
| straight_02.csv | straight | 0 | - | - |
| straight_03.csv | straight | 0 | - | - |
| straight_04.csv | straight | 0 | - | - |
| straight_walk_01.csv | straight_walk | 0 | - | - |
| straight_walk_02.csv | straight_walk | 0 | - | - |

## Notes

- `-15.5` catches all collected hunch/hunch-walk files while keeping collected straight, straight-walk, and bend-pickup files at zero triggers.
- Bend-pickup false positives were avoided mainly by the gyro/accel gate, not only by pitch threshold.
- If real use still feels too sensitive, try `-17.0`; if it feels too hard to trigger, try `-14.5` or reduce `hunch_hold_s` from `3.0` to `2.0`.
