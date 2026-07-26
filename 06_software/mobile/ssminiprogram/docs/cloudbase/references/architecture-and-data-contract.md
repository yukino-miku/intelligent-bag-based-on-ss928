# Architecture and Data Contract

## Contents

1. Channel model
2. Collections
3. Telemetry payload
4. Domain objects
5. Query patterns
6. Realtime strategy

## 1. Channel model

The product must support both channels:

- BLE: local, low-latency, nearby operation and configuration
- Cloud: remote status, tracks, alarms, and caregiver access

Keep transport details below a domain-service layer. A page should receive the same normalized status shape whether it came from BLE or CloudBase.

## 2. Collections

Use names already present in the project when compatible. Otherwise prefer:

### `devices`

One document per physical device.

```json
{
  "_id": "bag001",
  "displayName": "智能安全背包 001",
  "enabled": true,
  "secretVersion": 1,
  "lastSeenAt": "server date",
  "createdAt": "server date"
}
```

Do not store plaintext device secrets in a client-readable collection.

### `device_bindings`

Maps a Mini Program user to a device.

```json
{
  "deviceId": "bag001",
  "openid": "server-injected openid",
  "role": "owner",
  "enabled": true,
  "createdAt": "server date"
}
```

Recommended index: `(openid, deviceId, enabled)`.

### `device_status`

One latest-state document per device; use `deviceId` as the stable document key when practical.

```json
{
  "_id": "bag001",
  "schemaVersion": 1,
  "deviceId": "bag001",
  "deviceTimestampMs": 1784160000000,
  "receivedAt": "server date",
  "location": {
    "latitude": 30.000001,
    "longitude": 104.000001,
    "accuracyM": 8.5,
    "valid": true
  },
  "attitude": {
    "rollDeg": 1.2,
    "pitchDeg": -3.4,
    "yawDeg": 92.1
  },
  "risk": {
    "level": 2,
    "type": "rear_vehicle",
    "direction": "left_rear"
  },
  "batteryPercent": 82,
  "network": {
    "type": "5g-redcap",
    "rssiDbm": -81
  }
}
```

### `track_points`

Append-only GNSS history.

Recommended indexes:

- `(deviceId, receivedAt desc)`
- `(deviceId, deviceTimestampMs desc)` when device time is trustworthy

Use cursor pagination; do not download an unbounded route.

### `alarm_history`

Append-only safety events.

```json
{
  "schemaVersion": 1,
  "deviceId": "bag001",
  "alarmId": "device-generated-or-server-generated-id",
  "type": "rear_vehicle",
  "level": 3,
  "direction": "left_rear",
  "deviceTimestampMs": 1784160000000,
  "receivedAt": "server date",
  "location": {
    "latitude": 30.000001,
    "longitude": 104.000001
  },
  "details": {}
}
```

Recommended index: `(deviceId, receivedAt desc)`.

## 3. Telemetry payload

Preferred upload route:

```text
POST /v1/device/telemetry
Content-Type: application/json
X-Device-Id: bag001
X-Timestamp: 1784160000
X-Nonce: unique-random-value
X-Signature: hex-or-base64-hmac
```

Example body:

```json
{
  "schemaVersion": 1,
  "deviceId": "bag001",
  "deviceTimestampMs": 1784160000000,
  "status": {
    "location": {
      "latitude": 30.000001,
      "longitude": 104.000001,
      "accuracyM": 8.5,
      "valid": true
    },
    "attitude": {
      "rollDeg": 1.2,
      "pitchDeg": -3.4,
      "yawDeg": 92.1
    },
    "risk": {
      "level": 2,
      "type": "rear_vehicle",
      "direction": "left_rear"
    },
    "batteryPercent": 82
  },
  "trackPoints": [],
  "alarms": []
}
```

Define the signature message exactly and keep it stable, for example:

```text
METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + SHA256(BODY_BYTES)
```

The function must calculate the signature from the exact raw request body bytes. Reject requests outside the permitted clock-skew window and reused nonces.

## 4. Domain objects

Normalize BLE and cloud responses to stable objects:

```javascript
{
  source: "ble" | "cloud",
  deviceId: "bag001",
  observedAtMs: 1784160000000,
  location: null | {
    latitude: 30.000001,
    longitude: 104.000001,
    accuracyM: 8.5,
    valid: true
  },
  attitude: null | {
    rollDeg: 1.2,
    pitchDeg: -3.4,
    yawDeg: 92.1
  },
  risk: {
    level: 2,
    type: "rear_vehicle",
    direction: "left_rear"
  },
  batteryPercent: 82,
  stale: false
}
```

Do not expose database `_id`, `_openid`, or transport packet fields directly to pages unless the page genuinely needs them.

## 5. Query patterns

### Latest status

1. Event Function obtains `OPENID`.
2. Verify an enabled `device_bindings` record.
3. Read `device_status/{deviceId}`.
4. Return a normalized public object.

### Tracks and alarms

Use cursor pagination ordered by server receive time. Return:

```json
{
  "items": [],
  "nextCursor": null,
  "hasMore": false
}
```

Limit page size and reject excessive date ranges.

## 6. Realtime strategy

For the first competition-ready implementation, use short polling with a visible refresh interval and stale indicator unless CloudBase realtime watch has been proven stable in the target Mini Program environment.

Do not claim true realtime when the implementation is periodic polling. Keep the service interface flexible so polling can later be replaced by watch, WebSocket, or MQTT-backed delivery.
