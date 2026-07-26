# SmartBag telemetry v1 upload contract

## Endpoint

```text
POST https://cloud1-d7gdmg27139f4fbf2.service.tcloudbase.com/smartbag-device-ingest/v1/device/telemetry
Content-Type: application/json
X-Upload-Token: <competition upload token>
```

The token is read from `SMARTBAG_UPLOAD_TOKEN`. Keep `deviceId` fixed as
`bag001`. Every timestamp is Unix time in milliseconds. The top-level request
and every appended track/alarm record need a non-empty `requestId`.

## DX-GP21-A track

MT5710 supplies network transport only. GNSS data comes from DX-GP21-A and is
uploaded after a valid point is appended to the local track store.

```json
{
  "version": 1,
  "deviceId": "bag001",
  "requestId": "track-dxgp21-1784554468130-ab12cd34",
  "reportedAt": 1784554468130,
  "status": { "reportedAt": 1784554468130, "location": { "latitude": 30.65736, "longitude": 104.0832, "accuracyM": 8, "valid": true } },
  "trackPoints": [
    {
      "requestId": "track-dxgp21-1784554468130-ab12cd34",
      "reportedAt": 1784554468130,
      "location": { "latitude": 30.65736, "longitude": 104.0832, "accuracyM": 8, "valid": true },
      "speed": 1.2,
      "heading": 92,
      "altitudeM": 510,
      "source": "dx_gp21",
      "coordinateSystem": "wgs84"
    }
  ],
  "alarms": []
}
```

## Processed BMI270 posture and daily totals

Upload the result of the existing HUNCH hold/motion rule: `good` or `bad`.
Calibrated roll/pitch/yaw may be included as a diagnostic snapshot, but raw
accelerometer and gyroscope arrays must not be uploaded.

```json
{
  "version": 1,
  "deviceId": "bag001",
  "requestId": "posture-1784554468130-ab12cd34",
  "reportedAt": 1784554468130,
  "status": {
    "reportedAt": 1784554468130,
    "posture_status": "bad",
    "is_wearing": true,
    "reminder_active": true,
    "attitude": { "rollDeg": 1.2, "pitchDeg": -18.4, "yawDeg": 92.1 }
  },
  "postureDaily": {
    "device_id": "bag001",
    "date": "2026-07-20",
    "wearing_seconds": 20,
    "good_seconds": 15,
    "bad_seconds": 5,
    "updated_at": 1784554468130
  },
  "trackPoints": [],
  "alarms": []
}
```

Daily fields are absolute totals for the local date. They overwrite the stable
document `bag001_<date>`; they are not increments.

## Final fall alarm

Only upload the final event already emitted by the existing detector when both
`signal == "FALL_ALARM"` and `alarmType == "fall_detected"`. Do not upload
FREEFALL, IMPACT, pending states, camera warnings, or MR20 warnings. Include a
DX-GP21-A location only while its cache is fresh.

```json
{
  "version": 1,
  "deviceId": "bag001",
  "requestId": "fall-1784554468130-ab12cd34",
  "reportedAt": 1784554468130,
  "status": {
    "reportedAt": 1784554468130,
    "risk": { "level": 3, "type": "fall_detected" },
    "location": { "latitude": 30.65736, "longitude": 104.0832, "accuracyM": 8, "valid": true }
  },
  "trackPoints": [],
  "alarms": [
    {
      "requestId": "fall-1784554468130-ab12cd34",
      "alarmId": "fall-1784554468130-ab12cd34",
      "alarmType": "fall_detected",
      "riskLevel": 3,
      "message": "检测到用户摔倒",
      "reportedAt": 1784554468130,
      "details": { "signal": "FALL_ALARM", "conditions": { "impact": true, "posture": true, "stillness": true } },
      "location": { "latitude": 30.65736, "longitude": 104.0832, "accuracyM": 8, "valid": true }
    }
  ]
}
```

## Repository implementation

Use `work/smartbag_cloud_uploader/telemetry_client.py` instead of duplicating
request and payload code. Its background client uses a bounded event queue, a
replaceable latest-status slot, a short timeout, and redacted failures so a
CloudBase outage does not terminate a sensor loop.
