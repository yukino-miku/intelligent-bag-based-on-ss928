const FEATURE_ENTRIES = [
  {
    key: "health",
    title: "板子健康数据",
    subtitle: "电量 / 运行状态",
    icon: "电",
    tone: "green",
    route: "/pages/monitor/index"
  },
  {
    key: "alerts",
    title: "危险报警历史",
    subtitle: "报警记录 / 时间线",
    icon: "警",
    tone: "red",
    route: "/pages/monitor/index"
  },
  {
    key: "tracks",
    title: "儿童安全轨迹跟踪",
    subtitle: "位置轨迹 / 实时查看",
    icon: "轨",
    tone: "blue",
    route: "/pages/tracks/index"
  },
  {
    key: "posture",
    title: "姿态分析和记录",
    subtitle: "姿态识别 / 历史记录",
    icon: "姿",
    tone: "purple",
    route: "/pages/index/index"
  }
];

Page({
  data: {
    featureEntries: FEATURE_ENTRIES,
    onlineCount: 1,
    battery: 86,
    systemState: "正常",
    monitorState: "实时监控中"
  },

  openFeature(e) {
    const route = e.currentTarget.dataset.route;
    if (!route) {
      return;
    }
    wx.navigateTo({ url: route });
  }
});
