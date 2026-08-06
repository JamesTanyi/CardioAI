// pages/doctor/patient-list/patient-list.js
// ★ 新建：医生端的新入口——医生登录/绑定后，第一眼看到的是患者列表工作台，
//   而不是直接进入某一个患者的详情。列表字段只有：序号、姓名、年龄、性别、状态，
//   按风险状态动态排序（后端已排好序，前端不做二次排序判断）。
//   点击某一行姓名，才进入该患者的医生仪表盘（后端三角色语言报告）。
const app = getApp();

Page({
  data: {
    patients: [],
    loading: false,
    // ★ 新增：留言未读汇总——不是临床判断，纯粹是"有几位患者/几条消息"的数量统计，
    //   跟已有的"共 X 人"是同一类前端展示层面的计数，不涉及风险等级这类需要后端算的判断
    unreadPatientCount: 0,
    unreadTotalCount: 0
  },

  onShow() {
    this._loadPatients();
    this._maybeShowAddToDesktopTip();
  },

  /**
   * ★ 新增：引导医生把小程序添加到桌面/我的小程序，方便以后直接打开就能看到患者列表，
   *   不用每次都靠患者重新发邀请链接。
   *   注：微信平台不允许小程序代码直接触发"添加到桌面"这个动作（出于安全考虑，
   *   这个操作必须由用户自己点击右上角"..."菜单完成），这里只能做文字引导，
   *   不能自动帮用户完成这一步。只在医生第一次进入患者列表页时提示一次，不重复打扰。
   */
  _maybeShowAddToDesktopTip() {
    const hasShown = wx.getStorageSync('has_shown_add_desktop_tip');
    if (hasShown) return;

    wx.showModal({
      title: '方便下次快速查看',
      content: '建议点击右上角"···"菜单，选择"添加到我的小程序"或"添加到桌面"，以后打开更方便，不用每次都通过链接进入',
      confirmText: '知道了',
      showCancel: false,
      success: () => {
        wx.setStorageSync('has_shown_add_desktop_tip', true);
      }
    });
  },

  onPullDownRefresh() {
    app.refreshBindings(() => {
      this._loadPatients(() => wx.stopPullDownRefresh());
    });
  },

  /**
   * ★ 修复：未读数字这类会频繁变化的字段，不能只在"本地缓存为空"时才去后端刷新——
   *   之前只要 app.globalData.bindings 已经缓存过(哪怕是很早之前打开过一次)，
   *   就会一直用那份旧缓存并直接 return，永远不会再主动刷新，导致患者发了新留言，
   *   医生这边的未读数字永远看不到更新，除非缓存恰好被清空过。
   *   现在改成：如果有缓存，先用缓存秒开一次(避免转圈等待)，但每次进页面
   *   都无条件再主动调用 app.refreshBindings() 刷新一次，保证未读数字是最新的。
   */
  _loadPatients(callback) {
    this.setData({ loading: true });
    const bindings = app.globalData.bindings;

    if (bindings && bindings.hasDoctorBinding && bindings.doctorPatients) {
      // ★ 直接使用后端已经排好序的 doctorPatients，前端不重新排序、不重新判断风险等级
      this.setData({ patients: bindings.doctorPatients, loading: false });
      this._summarizeUnread(bindings.doctorPatients);
      // 注意：这里不再 return——即使有缓存可以秒开，也要继续往下刷新一次
    }

    app.refreshBindings((freshBindings) => {
      const list = (freshBindings && freshBindings.doctorPatients) || [];
      this.setData({ patients: list, loading: false });
      this._summarizeUnread(list);
      if (callback) callback();
    });
  },

  /**
   * ★ 新增：算一下"有几位患者有未读留言"+"总共几条未读"，显示在列表顶部。
   * 这里只是数一遍后端已经给好的 unreadFeedbackCount 字段，纯计数汇总，
   * 不涉及"哪个患者更严重"这类需要 riskLevel 才能判断的临床问题，
   * 跟已有的"共 X 人"是同一层级的前端展示统计。
   */
  _summarizeUnread(patients) {
    let unreadPatientCount = 0;
    let unreadTotalCount = 0;
    (patients || []).forEach((p) => {
      const c = p.unreadFeedbackCount || 0;
      if (c > 0) unreadPatientCount++;
      unreadTotalCount += c;
    });
    this.setData({ unreadPatientCount, unreadTotalCount });
  },

  /**
   * 点击某一行，进入该患者的医生仪表盘（三角色语言报告页）
   */
  onSelectPatient(e) {
    const { patientId, patientName } = e.currentTarget.dataset;
    wx.setStorageSync('last_viewed_patient', patientId);
    wx.setStorageSync('last_viewed_patient_name', patientName);
    wx.navigateTo({
      url: `/pages/doctor/dashboard/dashboard?patientId=${patientId}&patientName=${encodeURIComponent(patientName)}`
    });
  },

  goHome() {
    wx.navigateBack({
      fail: () => wx.redirectTo({ url: '/pages/index/index' })
    });
  }
});