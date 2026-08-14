// pages/doctor/dashboard/dashboard.js — 医生仪表盘（APP式接口：启动即自动加载患者列表+预警）
const cloudService = require('../../../utils/cloudService.js');
const app = getApp();

Page({
  data: {
    userInfo: {},
    reportDate: '',
    statistics: {
      avgSbp: '--', avgDbp: '--', maxSbp: '--', validDays: 0, abnormalRate: 0,
      sbpRange: '--', dbpRange: '--', ppRange: '--', hrRange: '--'
    },
    doctorReport: [], // 解析后的医生建议（按 ## 分区分组）
    reportCharts: [], // 从报告里提取出来的图表，展示在趋势图后面
    logs: [],
    // 图表数据
    trendCanvasWidth: 300,
    trendScrollLeft: 0,
    chartSource: [],
    trendChartSource: [],
    // 患者列表相关
    patients: [],
    selectedPatientId: '',
    selectedPatientName: '', // ★ 新增：当前查看患者的展示名（姓名+出生日期），顶部下拉框用它渲染，不再直接显示内部ID
    showPatientPicker: false,
    isViewingPatient: false,
    // 分页相关
    patientPage: 1,
    patientPageSize: 20,
    patientTotal: 0,
    patientHasMore: false,
    patientLoading: false,
    // 搜索
    searchKeyword: '',
    // 风险汇总
    highRiskCount: 0,
    moderateRiskCount: 0,
    unmonitoredCount: 0,
    patientRiskMap: {},
    patientUnreadMap: {},
    selectedPatientUnread: 0
  },

  /**
   * ★ onLoad：优先从 app.globalData 获取患者列表，无数据时从后端加载
   */
  onLoad(options) {
    // URL 参数（从分享链接跳入时用）
    if (options.patientId) {
      const patientName = options.patientName ? decodeURIComponent(options.patientName) : options.patientId;
      this.setData({
        selectedPatientId: options.patientId,
        selectedPatientName: patientName, // ★ 新增
        isViewingPatient: true
      });
      wx.setStorageSync('last_viewed_patient', options.patientId);
      wx.setStorageSync('last_viewed_patient_name', patientName);
    }

    // ★ 新增：单独注册一个App级前台监听——onShow/onHide只覆盖"页面导航切换"
    // 这一种场景，覆盖不了"手机锁屏/切到别的App再回来"这种情况(小程序页面
    // 计时器很可能被系统暂停，导航栈没变化时onShow不一定会重新触发，30秒
    // 轮询就这样悄悄停摆，页面显示还在但数据早就不刷新了)。wx.onAppShow
    // 跟着整个App前后台切换走，不受页面导航栈状态影响，用它兜底触发一次
    // 真正的刷新。绑定的函数引用要保存下来，onUnload时才能正确注销。
    this._onAppShowHandler = () => {
      // ★ App从后台恢复(比如锁屏解锁、切回微信)，不管距上次刷新过了多久，
      // 直接强制刷新一次——这个场景下我们不知道后台期间过去了多长时间，
      // 也不知道页面计时器有没有被系统暂停，索性不依赖阈值判断，直接刷新最可靠。
      if (this.data.isViewingPatient) {
        this._preBindThenLoad();
        this._startAutoRefresh();
      }
    };
    wx.onAppShow(this._onAppShowHandler);
    this._lastRefreshAt = Date.now();
  },

  onUnload() {
    if (this._onAppShowHandler) {
      wx.offAppShow(this._onAppShowHandler);
      this._onAppShowHandler = null;
    }
  },

  onShow() {
    this._preBindThenLoad();
    this._startAutoRefresh();
  },

  onHide() {
    this._stopAutoRefresh();
  },

  /** ★ v6：30秒自动轮询（静默刷新，不显示loading） */
  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._refreshTimer = setInterval(() => {
      if (this.data.selectedPatientId || this.data.isViewingPatient) {
        this._silentRefresh();
      }
    }, 30000);
  },

  _stopAutoRefresh() {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  },

  /** ★ 静默刷新：不弹 loading，不干扰用户操作 */
  _silentRefresh() {
    const userId = this.getViewUserId();
    const doctorId = this.getCurrentDoctorId();
    const viewerId = this.data.isViewingPatient ? doctorId : '';
    cloudService.getHistory(userId, viewerId, 90)
      .then((res) => {
        if (res.code === 0 && res.data && res.data.length > 0) {
          const serverRecords = res.data.map(item => ({
            ...item, datetime: item.datetime || item.date || item.created_at
          }));
          const localHistory = wx.getStorageSync('measure_history') || [];
          const merged = this.mergeAndDeduplicate(serverRecords, localHistory);
          merged.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || b.date));
          this.processHistoryData(merged);
          this._lastRefreshAt = Date.now(); // ★ 新增：记录这次静默刷新成功完成的时间
        }
      })
      .catch(() => {});
  },

  /**
   * ★ v7：intro 已确保 API 绑定完成才跳转，此处仅恢复患者ID + 加载数据
   */
  _preBindThenLoad() {
    const app = getApp();
    // 恢复当前选中患者（URL > storage > 全局绑定首选）
    let patientId = this.data.selectedPatientId || wx.getStorageSync('last_viewed_patient') || '';
    if (!patientId) {
      const bindings = app.globalData.bindings;
      if (bindings && bindings.hasDoctorBinding && bindings.doctorPatients && bindings.doctorPatients.length > 0) {
        // ★ 改：后端字段名是 riskLevel，不是 risk——原代码这里永远匹配不到，预警优先跳转从未生效
        const highP = bindings.doctorPatients.find(p => p.riskLevel === 'high' || p.riskLevel === 'critical');
        const modP = bindings.doctorPatients.find(p => p.riskLevel === 'moderate');
        const firstP = highP || modP || bindings.doctorPatients[0];
        patientId = firstP.patientId;
        // ★ 改：同步记录展示名，不再只有ID
        this.setData({ selectedPatientId: patientId, selectedPatientName: firstP.patientName || patientId, isViewingPatient: true });
      }
    }

    app.refreshBindings(() => {
      this._restoreFromBindings();
    });
  },

  /**
   * ★ 从 app 全局绑定数据恢复患者列表
   */
  _restoreFromBindings() {
    // ★ 新增：记录"最近一次真正完成刷新"的时间，方便排查时确认刷新有没有正常在跑
    this._lastRefreshAt = Date.now();
    const app = getApp();
    const bindings = app.globalData.bindings;

    const urlPid = this.data.selectedPatientId;
    const localBindMatch = wx.getStorageSync('has_doctor_binding') && wx.getStorageSync('last_viewed_patient') === urlPid;
    if (urlPid && (!bindings || !bindings.hasDoctorBinding) && localBindMatch) {
      app.refreshBindings(() => {
        this._restoreFromBindings();
      });
      return;
    }

    if (bindings && bindings.hasDoctorBinding && bindings.doctorPatients && bindings.doctorPatients.length > 0) {
      const { doctorPatients } = bindings;

      const patients = doctorPatients.map(p => ({
        patient_id: p.patientId,
        displayName: p.patientName || p.patientId,   // ★ 改：优先用姓名(出生日期)，查不到就退回原始ID
        doctor_name: p.doctorName || '',
        hospital: p.hospital || '',
        department: p.department || ''
      }));

      // ★ 新增：unreadFeedbackCount 后端本来就返回了，之前 map 的时候漏掉了，
      //   导致"留言"按钮永远不知道当前选中患者有没有未读——不是被提前标记已读，
      //   是这份数据从一开始就没被带过来。这里单独存一份 patientId -> 未读数
      //   的映射，跟 patientRiskMap 是同一个模式。
      const patientUnreadMap = {};
      doctorPatients.forEach(p => {
        patientUnreadMap[p.patientId] = p.unreadFeedbackCount || 0;
      });

      // ★ 改：riskMap 用正确的字段名 riskLevel（原来读 p.risk，永远是 undefined）
      const riskMap = {};
      doctorPatients.forEach(p => {
        riskMap[p.patientId] = { risk: p.riskLevel, sbp: p.sbp, dbp: p.dbp, date: p.date };
      });

      // ★ 改：bindings.doctorAlertSummary 后端从未返回过这个字段（一直是 undefined），
      //   这里改成直接用已经拿到的 doctorPatients（带 riskLevel，后端已按风险排序）本地统计，
      //   不改变"数值来源于后端 riskLevel"这一点，只是把汇总这一步挪到前端做（原来就是前端做，只是源头数据一直取不到）
      let highRiskCount = 0, moderateRiskCount = 0, unmonitoredCount = 0;
      doctorPatients.forEach(p => {
        if (p.riskLevel === 'high' || p.riskLevel === 'critical') highRiskCount++;
        else if (p.riskLevel === 'moderate') moderateRiskCount++;
        else if (p.riskLevel === 'none') unmonitoredCount++;
      });

      let autoSelect = this.data.selectedPatientId;
      let autoSelectName = this.data.selectedPatientName;
      if (!autoSelect && !this.data.isViewingPatient) {
        // ★ 改：同样修正字段名；doctorPatients 后端已按风险排序，[0] 就是最需要关注的患者
        const highPatient = doctorPatients.find(p => p.riskLevel === 'high' || p.riskLevel === 'critical');
        const moderatePatient = doctorPatients.find(p => p.riskLevel === 'moderate');
        const firstPatient = doctorPatients[0];
        const picked = highPatient || moderatePatient || firstPatient;
        autoSelect = picked.patientId;
        autoSelectName = picked.patientName || picked.patientId;
      }

      this.setData({
        patients,
        patientTotal: doctorPatients.length,
        patientHasMore: false,
        patientRiskMap: riskMap,
        patientUnreadMap,
        selectedPatientId: autoSelect || '',
        selectedPatientName: autoSelectName || autoSelect || '', // ★ 新增
        selectedPatientUnread: patientUnreadMap[autoSelect] || 0, // ★ 新增：喂给"留言"按钮的角标
        isViewingPatient: !!autoSelect,
        highRiskCount,
        moderateRiskCount,
        unmonitoredCount
      });

      if (autoSelect) {
        wx.setStorageSync('last_viewed_patient', autoSelect);
        wx.setStorageSync('last_viewed_patient_name', autoSelectName || autoSelect);
        wx.setStorageSync('has_doctor_binding', true);
      }

      this.generateMedicalReport();
      this.loadBoundPatients(false);
    } else if (app.globalData.bindingsReady) {
      this._fallbackLoadPatients();
    } else {
      this._fallbackLoadPatients();
    }
  },

  /**
   * 兜底：从后端直接加载患者列表
   */
  _fallbackLoadPatients() {
    this.loadBoundPatients(true, () => {
      this.generateMedicalReport();
    });
  },

  /**
   * 下拉刷新患者列表（同步全局绑定 + 刷新后端）
   */
  onPullDownRefresh() {
    const app = getApp();
    app.refreshBindings((bindings) => {
      if (bindings) {
        this._restoreFromBindings();
      } else {
        this.loadBoundPatients(true, () => {
          this.generateMedicalReport();
        });
      }
      wx.stopPullDownRefresh();
    });
  },

  /**
   * 上拉加载更多患者
   */
  onReachBottom() {
    if (!this.data.showPatientPicker) return;
    if (!this.data.patientHasMore || this.data.patientLoading) return;
    const nextPage = this.data.patientPage + 1;
    this.setData({ patientPage: nextPage });
    this.loadBoundPatients(false);
  },

  /**
   * 加载已绑定的患者列表（支持分页）
   * ★ 注：cloudService.getDoctorPatients 对应的后端路由 /get_doctor_patients
   *   目前尚未在 binding_views.py 中实现（已知的"幽灵接口"之一），
   *   这个函数在实际环境下会走 .catch() 静默失败，主体患者列表数据
   *   来自 _restoreFromBindings()（走 get_binding_status，已验证可用），不受影响。
   *   这里只修正 displayName 兜底逻辑，保持与其他地方一致，不改变其他行为。
   */
  loadBoundPatients(reset, callback) {
    const doctorId = wx.getStorageSync('app_user_id');
    if (!doctorId) {
      if (callback) callback();
      return;
    }
    if (this.data.patientLoading) return;
    this.setData({ patientLoading: true });

    const keyword = this.data.searchKeyword.trim();
    const page = this.data.patientPage;
    const pageSize = this.data.patientPageSize;

    cloudService.getDoctorPatients(doctorId, page, pageSize, keyword)
      .then((res) => {
        this.setData({ patientLoading: false });
        if (res.code === 0 && res.data) {
          const newPatients = res.data.map(p => ({
            ...p,
            displayName: p.patientName || p.patient_id || '未知患者' // ★ 改：优先姓名(出生日期)，其余不变
          }));

          const patients = reset ? newPatients : [...this.data.patients, ...newPatients];

          const targetId = this.data.selectedPatientId;
          if (targetId && !patients.find(p => p.patient_id === targetId)) {
            patients.unshift({
              patient_id: targetId,
              displayName: this.data.selectedPatientName || targetId, // ★ 改：优先用已知展示名
              doctor_name: '',
              hospital: '',
              department: ''
            });
          }

          this.setData({
            patients,
            patientTotal: res.total || patients.length,
            patientHasMore: res.hasMore || false
          });
        } else {
          this.setData({ patientHasMore: false });
        }
        if (callback) callback();
      })
      .catch(() => {
        this.setData({ patientLoading: false, patientHasMore: false });
        if (callback) callback();
      });
  },

  /**
   * 搜索患者（防抖）
   */
  onSearchInput(e) {
    const keyword = e.detail.value;
    this.setData({ searchKeyword: keyword });
    if (this._searchTimer) clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => {
      this.setData({ patientPage: 1, patients: [], patientHasMore: false });
      this.loadBoundPatients(true);
    }, 400);
  },

  /**
   * 清除搜索
   */
  clearSearch() {
    this.setData({ searchKeyword: '', patientPage: 1, patients: [], patientHasMore: false });
    this.loadBoundPatients(true);
  },

  /**
   * 切换患者选择器
   * ★ 注：原本这里还有一个 loadPatientRisk() 函数，调用已清理的 getPatientsRiskSummary 接口，
   *   现在风险汇总统计已经在 _restoreFromBindings() 里用 doctorPatients 的 riskLevel 本地算好了，
   *   这个函数连同调用一并删除，避免维护两套风险汇总逻辑。
   */
  togglePatientPicker() {
    const opening = !this.data.showPatientPicker;
    this.setData({ showPatientPicker: opening });
    if (opening && this.data.patients.length === 0) {
      this.setData({ patientPage: 1, patientHasMore: false });
      this.loadBoundPatients(true);
    }
  },

  // ★ 新增：跳转到三方留言板，带上当前正在查看的患者ID/姓名——
  //   feedback 页面靠这两个参数确定"进的是哪个患者的留言线"
  goToFeedback() {
    const { selectedPatientId, selectedPatientName } = this.data;
    if (!selectedPatientId) {
      wx.showToast({ title: '请先选择一位患者', icon: 'none' });
      return;
    }
    const nameParam = selectedPatientName ? `&patientName=${encodeURIComponent(selectedPatientName)}` : '';
    wx.navigateTo({ url: `/feedback/feedback?patientId=${encodeURIComponent(selectedPatientId)}${nameParam}` });
  },

  /**
   * 选择患者
   * ★ 改：同步更新 selectedPatientName，顶部"当前查看"才能正确显示展示名
   */
  selectPatient(e) {
    const patientId = e.currentTarget.dataset.patientId;
    const patientName = e.currentTarget.dataset.patientName || patientId;
    this.setData({
      selectedPatientId: patientId,
      selectedPatientName: patientName, // ★ 新增
      selectedPatientUnread: this.data.patientUnreadMap[patientId] || 0, // ★ 新增：切换患者时角标跟着换
      showPatientPicker: false,
      isViewingPatient: patientId !== ''
    });
    wx.setStorageSync('last_viewed_patient', patientId);
    wx.setStorageSync('last_viewed_patient_name', patientName);
    this.generateMedicalReport();
  },

  /**
   * 查看自己的数据
   */
  viewOwnData() {
    this.setData({
      selectedPatientId: '',
      selectedPatientName: '',
      selectedPatientUnread: 0, // ★ 新增
      showPatientPicker: false,
      isViewingPatient: false
    });
    this.generateMedicalReport();
  },

  /**
   * 获取当前查看的用户ID
   */
  getViewUserId() {
    if (this.data.selectedPatientId) {
      return this.data.selectedPatientId;
    }
    return wx.getStorageSync('app_user_id') || 'Guest';
  },

  /**
   * 获取当前登录用户ID
   */
  getCurrentDoctorId() {
    return wx.getStorageSync('app_user_id') || 'Guest';
  },

  generateMedicalReport() {
    const userId = this.getViewUserId();
    const doctorId = this.getCurrentDoctorId();
    const now = new Date();

    this.setData({
      userInfo: { id: userId },
      reportDate: `${now.getFullYear()}/${now.getMonth()+1}/${now.getDate()} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`
    });

    wx.showLoading({ title: '加载中...', mask: false });

    const localHistory = wx.getStorageSync('measure_history') || [];
    const viewerId = this.data.isViewingPatient ? doctorId : '';

    cloudService.getHistory(userId, viewerId, 90)
      .then((res) => {
        wx.hideLoading();
        if (res.code === 0 && res.data && Array.isArray(res.data) && res.data.length > 0) {
          const serverRecords = res.data.map(item => ({
            ...item,
            datetime: item.datetime || item.date || item.created_at
          }));

          const merged = this.mergeAndDeduplicate(serverRecords, localHistory);
          merged.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || b.date));
          if (!this.data.isViewingPatient) {
            wx.setStorageSync('measure_history', merged);
          }
          this.processHistoryData(merged);
        } else {
          if (res.error && res.error.includes('权限')) {
            wx.showToast({ title: '暂无权限查看该患者数据，请确认绑定关系', icon: 'none' });
          }
          if (localHistory.length === 0) return;
          this.processHistoryData(localHistory);
        }
      })
      .catch(() => {
        wx.hideLoading();
        if (localHistory.length === 0) return;
        this.processHistoryData(localHistory);
      });
  },

  // 合并并去重数据
  mergeAndDeduplicate(serverData, localData) {
    const map = new Map();
    serverData.forEach(item => {
      const key = item.datetime || item.date;
      if (key) map.set(key, item);
    });
    localData.forEach(item => {
      const key = item.datetime || item.date;
      if (key && !map.has(key)) {
        map.set(key, item);
      }
    });
    return Array.from(map.values());
  },

  // 处理历史数据（核心逻辑）
  processHistoryData(history) {
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    const validData = history.filter(item => {
      const d = new Date(((item.datetime || item.date) || '').replace(/-/g, '/'));
      return d >= thirtyDaysAgo;
    });

    let totalSbp = 0, totalDbp = 0, abnormalCount = 0;
    let maxSbp = -Infinity, minSbp = Infinity;
    let maxDbp = -Infinity, minDbp = Infinity;
    let maxPp = -Infinity, minPp = Infinity;
    let maxHr = -Infinity, minHr = Infinity;

    const logs = validData.map(item => {
      const sbp = parseInt(item.sbp);
      const dbp = parseInt(item.dbp);
      const hr = parseInt(item.hr) || 0;
      const pp = sbp - dbp;

      totalSbp += sbp;
      totalDbp += dbp;
      if (sbp > maxSbp) maxSbp = sbp;
      if (sbp < minSbp) minSbp = sbp;
      if (dbp > maxDbp) maxDbp = dbp;
      if (dbp < minDbp) minDbp = dbp;
      if (pp > maxPp) maxPp = pp;
      if (pp < minPp) minPp = pp;
      if (hr) {
        if (hr > maxHr) maxHr = hr;
        if (hr < minHr) minHr = hr;
      }
      if (sbp >= 140 || dbp >= 90) abnormalCount++;

      return {
        ...item,
        sbp, dbp, hr, pp,
        dateSimple: (item.datetime || item.date || '').substring(0, 16)
      };
    });

    const count = validData.length;
    // ★ 修复：之前 statistics 里没有 sbpRange/dbpRange/ppRange/hrRange 这几个字段，
    //   但 wxml 里"血压分布与摘要"卡片绑定的就是这几个字段名，导致范围数值一直是空白
    const fmtRange = (min, max) => {
      if (min === Infinity || max === -Infinity) return '--';
      return min === max ? `${min}` : `${min}-${max}`;
    };
    const stats = {
      avgSbp: count ? Math.round(totalSbp / count) : '--',
      avgDbp: count ? Math.round(totalDbp / count) : '--',
      maxSbp: count ? maxSbp : '--',
      validDays: count,
      abnormalRate: count ? Math.round((abnormalCount / count) * 100) : 0,
      sbpRange: count ? fmtRange(minSbp, maxSbp) : '--',
      dbpRange: count ? fmtRange(minDbp, maxDbp) : '--',
      ppRange: count ? fmtRange(minPp, maxPp) : '--',
      hrRange: count && minHr !== Infinity ? fmtRange(minHr, maxHr) : '--'
    };

    // ★ 改：真实存储结构是 analysis.doctor（分析引擎直接返回的四个角色报告平铺在 analysis 对象里），
    //   不是 analysis.details.reports.doctor 这种嵌套两层的路径——之前这里路径写错了，
    //   导致即使有真实报告数据，也一直落到"暂无临床分析数据"这个兜底文案
    const latestAnalysis = history.find(item => item.analysis && item.analysis.doctor);
    let parsedReport = [];

    if (latestAnalysis) {
      const rawReport = latestAnalysis.analysis.doctor;
      parsedReport = this.parseDoctorReport(rawReport);
    } else {
      parsedReport = [{ title: '', items: [{ type: 'p', content: '暂无基于后端AI模型的临床分析数据。' }] }];
    }

    // ★ 改：把报告里的 "Charts" 分区单独拆出来，挪到趋势图后面单独展示一张卡片，
    //   不再让两张图深埋在一大段文字报告的最底部、要滚很久才能看到
    let reportCharts = [];
    const doctorReport = parsedReport.filter((section) => {
      if (section.title === 'Charts') {
        reportCharts = section.items.filter((item) => item.type === 'img');
        return false;
      }
      return true;
    });

    const chartSource = [...logs].reverse();
    const sysInfo = wx.getSystemInfoSync();
    const minWidth = sysInfo.windowWidth - 80;

    // ★ 改：趋势图默认只看最近2周，而不是把30天数据全塞进一张要横向滚很久的图里
    const latestPointDt = chartSource.length
      ? new Date((chartSource[chartSource.length - 1].datetime || chartSource[chartSource.length - 1].date || '').replace(/-/g, '/'))
      : now;
    const fourteenDaysAgo = new Date(latestPointDt.getTime() - 14 * 24 * 60 * 60 * 1000);
    const trendChartSource = chartSource.filter((item) => {
      const d = new Date((item.datetime || item.date || '').replace(/-/g, '/'));
      return d >= fourteenDaysAgo;
    });
    // ★ 改：canvas宽度固定为容器宽度，不再按点数撑宽——不管这2周里有多少条记录，
    //   都完整压缩进一屏展示，不需要横向滚动；drawChart内部按点数自动收窄间距和点的大小
    const trendCanvasWidth = minWidth;

    this.setData({
      logs: logs,
      statistics: stats,
      doctorReport: doctorReport,
      reportCharts: reportCharts,
      chartSource: chartSource,
      trendChartSource: trendChartSource,
      trendCanvasWidth: trendCanvasWidth,
      trendScrollLeft: 0
    });

    setTimeout(() => {
      this.initChart(trendChartSource);
      this.initDistChart(chartSource);
    }, 200);
  },

  // 解析医生报告文本
  // ★ 改：不再用关键词猜每一行是"建议"还是"警示"给它上色——
  //   医生只看后端生成的事实原文，怎么判断是医生的事，前端不做分类/不做描述
  // ★ 改：识别后端 language.py 本来就用 Markdown 语法标出来的结构
  //   （## 大标题 / ### 小标题 / - 列表 / <img src="..."> 图表 / --- 分隔线），
  //   并按两层分组还原视觉层级：
  //   1) 紧跟在 "- 列表项:" 后面、没有 "-" 前缀的普通段落，视为该列表项的补充数据，
  //      收进 detailsText 里缩进展示（纯粹是"这几行属于上一条"的结构关系，不判断内容含义）
  //   2) 按 "## " 大标题切成一个个报告分区，每个分区单独成一张卡片，
  //      避免整份报告变成一整块无差别的文字墙
  //   全程只做结构还原，不对内容本身做任何语义判断或分类。
  parseDoctorReport(text) {
    if (!text) return [];
    const lines = text.split('\n');
    const flat = [];

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;

      // <img src="..."> —— 提取图片链接，交给 <image> 组件渲染
      const imgMatch = line.match(/<img\s+src="([^"]+)"/);
      if (imgMatch) {
        flat.push({ type: 'img', src: imgMatch[1] });
        continue;
      }

      if (line.startsWith('### ')) {
        flat.push({ type: 'h3', content: line.slice(4) });
        continue;
      }
      if (line.startsWith('## ')) {
        flat.push({ type: 'h2', content: line.slice(3) });
        continue;
      }
      if (line.startsWith('- ')) {
        flat.push({ type: 'li', content: line.slice(2) });
        continue;
      }
      if (line === '---') {
        flat.push({ type: 'hr' });
        continue;
      }

      flat.push({ type: 'p', content: line });
    }

    // 第一遍分组：紧跟在列表项后面的普通段落，收进该列表项的 detailsText
    const grouped = [];
    let i = 0;
    while (i < flat.length) {
      const item = flat[i];
      if (item.type === 'li') {
        const details = [];
        let j = i + 1;
        while (j < flat.length && flat[j].type === 'p') {
          details.push(flat[j].content);
          j++;
        }
        grouped.push({ type: 'li', content: item.content, detailsText: details.join('   ') });
        i = j;
      } else {
        grouped.push(item);
        i++;
      }
    }

    // 第二遍分组：按 "## " 大标题切成报告分区，每个分区单独成卡片
    const sections = [];
    let current = { title: '', items: [] };
    for (const item of grouped) {
      if (item.type === 'h2') {
        if (current.title || current.items.length) sections.push(current);
        current = { title: item.content, items: [] };
      } else {
        current.items.push(item);
      }
    }
    if (current.title || current.items.length) sections.push(current);

    return sections;
  },

  // 初始化 Canvas
  initChart(data) {
    const query = wx.createSelectorQuery();
    query.select('#doctorChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0]) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = wx.getSystemInfoSync().pixelRatio;
        canvas.width = res[0].width * dpr;
        canvas.height = res[0].height * dpr;
        ctx.scale(dpr, dpr);
        this.drawChart(ctx, data, res[0].width, res[0].height);
      });
  },

  drawChart(ctx, data, width, height) {
    if (data.length === 0) return;

    const ratio = height / 300;
    const padding = { top: 22 * ratio, bottom: 56 * ratio, left: 32 * ratio, right: 20 * ratio };
    const drawHeight = height - padding.top - padding.bottom;
    const stepX = (width - padding.left - padding.right) / Math.max(1, data.length - 1);

    // ★ 修复：纵轴范围不再写死 60~180——真实血压可能超过180或低于60，
    //   写死的范围会把超出的读数直接拍扁画在顶边/底边（比如200会画得跟180一样高），
    //   看起来失真、掩盖了真实的严重程度。改成按这2周实际最高最低值往外扩一点动态计算。
    const allVals = [];
    data.forEach((item) => { allVals.push(item.sbp, item.dbp); });
    const rawMin = Math.min(...allVals);
    const rawMax = Math.max(...allVals);
    const minVal = Math.floor((rawMin - 10) / 10) * 10;
    const maxVal = Math.ceil((rawMax + 10) / 10) * 10;
    const valRange = Math.max(20, maxVal - minVal);

    const getY = (val) => {
      const clampedVal = Math.max(minVal, Math.min(maxVal, val));
      return padding.top + drawHeight * (1 - (clampedVal - minVal) / valRange);
    };

    // 纵轴刻度：按动态范围切成约5档整数刻度（10的倍数，好读）
    const rawStep = valRange / 5;
    const tickStep = Math.max(10, Math.round(rawStep / 10) * 10);
    const ticks = [];
    for (let v = minVal; v <= maxVal; v += tickStep) ticks.push(v);

    ctx.clearRect(0, 0, width, height);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    ctx.strokeStyle = '#F5F5F5';
    ctx.lineWidth = 1;
    ticks.forEach((val) => {
      const y = getY(val);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    });

    // ★ 新增：纵轴刻度数字直接画在canvas上（不再用页面上单独固定的一列文字），
    //   这样数字永远跟当前的动态范围对齐，不会跟固定文字对不上
    ctx.fillStyle = '#999';
    ctx.font = `${Math.max(9, 10 * ratio)}px sans-serif`;
    ctx.textAlign = 'right';
    ticks.forEach((val) => {
      const y = getY(val);
      ctx.fillText(String(val), padding.left - 6, y + 3);
    });

    // ★ 改：线宽和点的大小按数据密度自适应——固定宽度的画面里，2周数据可能是3个点也可能是20多个点，
    //   固定的线宽/点大小要么点数少时显得太细太小，要么点数多时挤成一团
    const dotRadius = data.length > 14 ? 2 : data.length > 8 ? 2.5 : 3;
    const lineWidth = data.length > 14 ? 1.5 : 2;

    const drawLine = (key, color) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      data.forEach((item, index) => {
        const x = padding.left + index * stepX;
        const y = getY(item[key]);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.fillStyle = '#fff';
      ctx.lineWidth = Math.max(1, lineWidth - 0.5);
      data.forEach((item, index) => {
        const x = padding.left + index * stepX;
        const y = getY(item[key]);
        ctx.beginPath();
        ctx.arc(x, y, dotRadius, 0, 2 * Math.PI);
        ctx.fill();
        ctx.stroke();
      });
    };

    drawLine('sbp', '#FF6B6B');
    drawLine('dbp', '#4A90E2');

    // ★ 新增：x轴日期刻度——之前这张图完全没有时间轴，只能靠横向滚动猜时间
    //   数据点多时（超过约6个）只挑着显示一部分标签，避免日期文字挤在一起看不清
    ctx.fillStyle = '#999';
    ctx.font = `${Math.max(9, 10 * ratio)}px sans-serif`;
    ctx.textAlign = 'center';
    const maxLabels = 6;
    const labelStep = Math.max(1, Math.ceil(data.length / maxLabels));
    data.forEach((item, index) => {
      const showLabel = index % labelStep === 0 || index === data.length - 1;
      if (!showLabel) return;
      const x = padding.left + index * stepX;
      const dateStr = (item.dateSimple || '').substring(5, 10); // MM-DD
      ctx.fillText(dateStr, x, height - padding.bottom + 20 * ratio);
    });
  },

  // ★ 新增：给"血压分布与摘要"卡片里的 distChart 画布补上散点图
  //   之前这个 canvas 一直是空的——wxml 里有节点，但 js 里从没写过任何绘制逻辑
  initDistChart(data) {
    const query = wx.createSelectorQuery();
    query.select('#distChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0]) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = wx.getSystemInfoSync().pixelRatio;
        canvas.width = res[0].width * dpr;
        canvas.height = res[0].height * dpr;
        ctx.scale(dpr, dpr);
        this.drawDistChart(ctx, data, res[0].width, res[0].height);
      });
  },

  // SBP(x) vs DBP(y) 散点图：只按 140/90 这条已有的异常线上色区分，不做额外的临床分类
  drawDistChart(ctx, data, width, height) {
    ctx.clearRect(0, 0, width, height);
    if (!data.length) return;

    const padding = 42; // 比之前留宽一点，给刻度数字腾地方
    const minVal = 50, maxVal = 200;
    const range = maxVal - minVal;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;

    const clamp = (v) => Math.max(minVal, Math.min(maxVal, v));
    const getX = (v) => padding + (clamp(v) - minVal) / range * plotW;
    const getY = (v) => height - padding - (clamp(v) - minVal) / range * plotH;

    const ticks = [60, 90, 120, 150, 180];

    // 网格线
    ctx.strokeStyle = '#F0F0F0';
    ctx.lineWidth = 1;
    ticks.forEach((v) => {
      const y = getY(v);
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.stroke();

      const x = getX(v);
      ctx.beginPath();
      ctx.moveTo(x, padding);
      ctx.lineTo(x, height - padding);
      ctx.stroke();
    });

    // 坐标轴
    ctx.strokeStyle = '#CCC';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.stroke();

    // 散点：沿用页面已有的"收缩压≥140 或 舒张压≥90 记为异常"这条线来配色，不新增判断规则
    data.forEach((item) => {
      const x = getX(item.sbp);
      const y = getY(item.dbp);
      const abnormal = item.sbp >= 140 || item.dbp >= 90;
      ctx.fillStyle = abnormal ? 'rgba(217,83,79,0.75)' : 'rgba(74,144,226,0.6)';
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, 2 * Math.PI);
      ctx.fill();
    });

    // ★ 新增：纵轴（DBP）和横轴（SBP）的具体刻度数值，之前只有网格线没有数字，看不出坐标含义
    ctx.fillStyle = '#999';
    ctx.font = '9px sans-serif';
    ticks.forEach((v) => {
      const y = getY(v);
      ctx.textAlign = 'right';
      ctx.fillText(v, padding - 6, y + 3);

      const x = getX(v);
      ctx.textAlign = 'center';
      ctx.fillText(v, x, height - padding + 14);
    });

    // 坐标轴说明
    ctx.textAlign = 'left';
    ctx.fillText('DBP', 4, padding - 10);
    ctx.fillText('SBP', width - padding - 20, height - 4);
  }
});