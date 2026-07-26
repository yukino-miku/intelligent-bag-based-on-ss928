# Smartbag CloudBase read and display guide

## Existing call chain

```text
Page
  -> miniprogram/services/cloud-data-source.js
  -> wx.cloud.callFunction({ name: "smartbag-app-api", data: { action } })
  -> CloudBase collection
```

Collections remain `ADMINONLY`. Pages never read them directly.

## Minimal service usage

Adjust the import path to the target page depth:

```javascript
const cloudDataSource = require("../../services/cloud-data-source");
```

### Latest status

```javascript
async loadLatestStatus() {
  try {
    const status = await cloudDataSource.getLatestStatus();
    this.setData({
      latestStatus: status || null,
      cloudError: "",
    });
  } catch (error) {
    console.error("loadLatestStatus failed", error);
    this.setData({
      latestStatus: null,
      cloudError: "云端状态加载失败",
    });
  }
}
```

### Track history

```javascript
async loadTrackPoints() {
  try {
    const points = await cloudDataSource.getTrackPoints();
    this.setData({
      trackPoints: Array.isArray(points) ? points : [],
      cloudError: "",
    });
  } catch (error) {
    console.error("loadTrackPoints failed", error);
    this.setData({
      trackPoints: [],
      cloudError: "云端轨迹加载失败",
    });
  }
}
```

### Alarm history

```javascript
function formatTime(timestamp) {
  if (!timestamp) return "时间未知";
  const date = new Date(timestamp);
  const pad = value => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function mapAlarm(record) {
  const location = record.location || {};
  const isFall = record.alarmType === "fall_detected";

  return {
    ...record,
    title: isFall ? "检测到摔倒" : (record.message || "安全报警"),
    riskText: Number(record.riskLevel) >= 3 ? "高风险" : "风险提醒",
    timeText: formatTime(record.reportedAt || record.receivedAt),
    locationText:
      location.latitude != null && location.longitude != null
        ? `${location.latitude}, ${location.longitude}`
        : "暂无定位",
  };
}

Page({
  data: {
    alarmRecords: [],
    loading: false,
    cloudError: "",
  },

  onShow() {
    this.loadAlarmHistory();
  },

  async loadAlarmHistory() {
    this.setData({ loading: true, cloudError: "" });
    try {
      const records = await cloudDataSource.getAlarmHistory();
      const alarmRecords = (Array.isArray(records) ? records : [])
        .map(mapAlarm)
        .sort((a, b) =>
          Number(b.reportedAt || b.receivedAt || 0) -
          Number(a.reportedAt || a.receivedAt || 0)
        );

      this.setData({ alarmRecords, loading: false });
    } catch (error) {
      console.error("loadAlarmHistory failed", error);
      this.setData({
        alarmRecords: [],
        loading: false,
        cloudError: "云端记录加载失败",
      });
    }
  },
});
```

If `cloud-data-source.js` returns an object such as `{ records: [...] }`, unwrap it there or adapt the page to the actual result. Do not guess; inspect the service function first.

## Minimal WXML pattern

```xml
<view wx:if="{{loading}}">加载中...</view>
<view wx:elif="{{cloudError}}">{{cloudError}}</view>
<view wx:elif="{{alarmRecords.length === 0}}">暂无报警记录</view>

<view wx:for="{{alarmRecords}}" wx:key="_id" class="alarm-card">
  <view class="alarm-title">{{item.title}}</view>
  <view>{{item.timeText}}</view>
  <view>{{item.riskText}}</view>
  <view>位置：{{item.locationText}}</view>
  <view>{{item.message}}</view>
</view>
```

## Direct developer-tools checks

```javascript
wx.cloud.callFunction({
  name: "smartbag-app-api",
  data: { action: "getLatestStatus" }
}).then(console.log).catch(console.error)
```

```javascript
wx.cloud.callFunction({
  name: "smartbag-app-api",
  data: { action: "getTrackPoints" }
}).then(console.log).catch(console.error)
```

```javascript
wx.cloud.callFunction({
  name: "smartbag-app-api",
  data: { action: "getAlarmHistory" }
}).then(console.log).catch(console.error)
```

Use these checks only for debugging. Production page code should call `cloud-data-source.js`.
