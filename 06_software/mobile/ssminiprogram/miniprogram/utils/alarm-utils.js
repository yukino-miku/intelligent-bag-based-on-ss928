const ALARM_RECORDS = [
  {
    id: "alarm-20260701",
    dateLabel: "7.1",
    title: "危险报警",
    typeText: "碰撞报警",
    timeText: "2026-07-01 08:32",
    timeDetail: "2026年7月1日 08:32",
    locationText: "成都·青羊区",
    addressText: "青羊区宽窄巷子附近",
    latitude: 30.66973,
    longitude: 104.05889
  },
  {
    id: "alarm-20260705",
    dateLabel: "7.5",
    title: "危险报警",
    typeText: "异常停留报警",
    timeText: "2026-07-05 18:47",
    timeDetail: "2026年7月5日 18:47",
    locationText: "成都·高新区",
    addressText: "高新区交子大道附近",
    latitude: 30.57546,
    longitude: 104.06854
  },
  {
    id: "alarm-20260706",
    dateLabel: "7.6",
    title: "危险报警",
    typeText: "主动求助报警",
    timeText: "2026-07-06 21:16",
    timeDetail: "2026年7月6日 21:16",
    locationText: "成都·锦江区",
    addressText: "锦江区春熙路附近",
    latitude: 30.65736,
    longitude: 104.0832
  }
];

const cloneRecord = (item) => Object.assign({}, item);

const getAlarmRecords = () => ALARM_RECORDS.map(cloneRecord);

const findAlarmById = (id) => {
  const match = ALARM_RECORDS.find((item) => item.id === id);
  return cloneRecord(match || ALARM_RECORDS[ALARM_RECORDS.length - 1]);
};

const buildAlarmMarker = (item) => {
  if (!item) {
    return [];
  }

  return [
    {
      id: 1,
      latitude: item.latitude,
      longitude: item.longitude,
      title: item.typeText,
      callout: {
        content: item.typeText + " · 危险报警",
        color: "#101820",
        fontSize: 13,
        borderRadius: 6,
        bgColor: "#FFFFFF",
        padding: 8,
        display: "ALWAYS"
      }
    }
  ];
};

module.exports = {
  buildAlarmMarker,
  findAlarmById,
  getAlarmRecords
};
