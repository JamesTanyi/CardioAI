const app = getApp();
const cloudService = require('../../utils/cloudService.js');

Page({
  data: {
    sbp: '',
    dbp: '',
    userId: '',
    displayName: '',
    isUserIdLocked: false,
    hr: '',
    currentRole: 'user',
    showAlert: false,
    alertBg: '',
    alertDot: '',
    alertColor: '',
    alertMsg: '',
    // ★ 新增：未读留言数(基础线+各医生诊疗线汇总)，显示在"更多功能"入口旁边的角标
    selfUnreadFeedbackCount: 0,

    symptoms: [
      { label: '头晕',         value: 'dizzy',           selected: false },
      { label: '胸闷',         value: 'chest_tightness',  selected: false },
      { label: '心悸',         value: 'palpitations',     selected: false },
      { label: '胸痛',         value: 'chest_pain',       selected: false },
      { label: '乏力',         value: 'fatigue',          selected: false },
      { label: '呼吸困难',     value: 'short_breath',     selected: false },
      { label: '视物模糊',     value: 'vision_loss',      selected: false },
      { label: '焦虑紧张',     value: 'anxiety',          selected: false },
      { label: '单侧肢体无力', value: 'limb_weakness',    selected: false },
      { label: '语言不清',     value: 'slurred_speech',   selected: false },
      { label: '头痛',         value: 'headache',         selected: false },
      { label: '异常疲劳',     value: 'abnormal_fatigue', selected: false },
    ]
  },

  onLoad() {
    this.checkUserId();
    const role = (app && typeof app.getRole === 'function')
      ? app.getRole()
      : (wx.getStorageSync('currentRole') || 'user');
    this.setData({ currentRole: role });
    this.checkAlertStatus();
    this._autoRouteToDashboard(role);
  },

  onShow() {
    const storedId = wx.getStorageSync('app_user_id') || wx.getStorageSync('userId');
    if (storedId) {
      this.setData({ userId: storedId, isUserIdLocked: true });
    }
    this._syncDisplayName();
    const role = (app && typeof app.getRole === 'function')
      ? app.getRole()
      : (wx.getStorageSync('currentRole') || 'user');
    this.setData({ currentRole: role });
    this.checkAlertStatus();
    this._autoRouteToDashboard(role);
    this._syncUnreadFeedback();
  },

  // ★ 新增：同步"健康反馈"未读数——跟 more.js 读的是同一份数据源
  //   (app.js 的 syncAllBindings 从 get_binding_status 同步好的
  //   selfUnreadFeedbackCount，已经把基础线+各医生诊疗线的未读都汇总在内)，
  //   不用自己再发一次请求
  _syncUnreadFeedback() {
    const readFromGlobal = () => {
      const badge = (app.globalData && app.globalData.alertBadge) || {};
      this.setData({ selfUnreadFeedbackCount: badge.selfUnreadFeedbackCount || 0 });
    };
    if (app.globalData && app.globalData.bindingsReady) {
      readFromGlobal();
    } else if (app && typeof app.syncAllBindings === 'function') {
      app.syncAllBindings(() => readFromGlobal());
    }
  },

  /**
   * ★ 新增：统一计算展示名——"姓名(出生日期)"，不再只显示姓名
   *   这样患者本人这一端和家属/医生端看到的格式保持一致，
   *   同时也不再需要暴露/编辑内部 user_id（见 index.wxml 的改动）。
   */
  _syncDisplayName() {
    const profile = wx.getStorageSync('userProfile') || {};
    if (!profile.name) return;
    const displayName = profile.birthDate ? `${profile.name}(${profile.birthDate})` : profile.name;
    this.setData({ displayName });
  },

  _autoRouteToDashboard(role) {
    if (role !== 'family' && role !== 'doctor') return;
    const pages = getCurrentPages();
    if (pages.length > 0) {
      const currentPagePath = pages[pages.length - 1].route;
      if (currentPagePath.indexOf('dashboard') !== -1) return;
    }
    // ★ 修复：原来这里要求 role 对上"且" has_family_binding/family_patient_id
    //   这类本地缓存标记也同时齐全，才会真正跳转——多一层条件就多一个
    //   静默失败的机会，家属/医生账号只要缺了某个缓存标记，就会卡在这个
    //   录入血压页面出不去(这正是这次排查到的实际bug现象)。现在只要角色
    //   本身是family/doctor就立刻转走，patientId缺失时退回各自的兜底页面，
    //   不再要求额外标记齐全才生效。
    if (role === 'family') {
      const localPid = wx.getStorageSync('family_patient_id') || '';
      if (localPid) {
        const localPname = wx.getStorageSync('family_patient_name') || localPid;
        wx.reLaunch({ url: `/pages/family/dashboard/dashboard?patientId=${localPid}&patientName=${encodeURIComponent(localPname)}` });
      } else {
        wx.reLaunch({ url: '/pages/family/family/family' });
      }
      return;
    }
    if (role === 'doctor') {
      // ★ 改：医生的默认落地页统一为患者列表工作台，不是某个具体患者的详情——
      //   跟项目里其他地方(app.js/bind-confirm.js)已经确立的设计保持一致，
      //   这里原来是跳去某个"上次看的患者"详情页，不统一，也容易在没有
      //   "上次看的患者"记录时又静默失败
      wx.reLaunch({ url: '/pages/doctor/patient-list/patient-list' });
      return;
    }
  },

  checkUserId() {
    const storedId = wx.getStorageSync('app_user_id') || wx.getStorageSync('userId');
    if (storedId) {
      this.setData({ userId: storedId, isUserIdLocked: true });
      this._syncDisplayName();
    } else {
      wx.reLaunch({ url: '/pages/onboarding/UserProfile/UserProfile' });
    }
  },

  onInputSbp(e) { this.setData({ sbp: e.detail.value }); },
  onInputDbp(e) { this.setData({ dbp: e.detail.value }); },
  onInputHr(e) { this.setData({ hr: e.detail.value }); },

  toggleSymptom(e) {
    const index = e.currentTarget.dataset.index;
    const key = `symptoms[${index}].selected`;
    this.setData({ [key]: !this.data.symptoms[index].selected });
  },

  // ====================================================
  // ★ measure_bp.analyze_measurement 是"自给自足"接口——
  //   后端自己查历史、自己跑分析引擎、自己把这条记录存进数据库，
  //   前端只需要传本次这一条测量数据（扁平结构），不再需要：
  //   1) 客户端先查历史再传给后端
  //   2) analyze 成功后再单独调 save_history 存一次
  //      （否则会导致同一条记录在 measurements 表里存两遍）
  // ====================================================
  async submitAnalysis() {
    const sbp = parseInt(this.data.sbp);
    const dbp = parseInt(this.data.dbp);
    if (!sbp || !dbp) {
      wx.showToast({ title: '请输入血压值', icon: 'none' });
      return;
    }
    if (sbp <= dbp) {
      wx.showToast({ title: '高压必须大于低压', icon: 'none' });
      return;
    }
    if (!this.data.userId) {
      wx.showToast({ title: '用户ID不能为空', icon: 'none' });
      return;
    }

    wx.showLoading({ title: 'AI 分析中...', mask: true });

    try {
      const selectedSymptoms = this.data.symptoms.filter(item => item.selected).map(item => item.value);
      const now = new Date();
      const fullDateTime = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:00`;

      const payload = {
        userId: this.data.userId,
        sbp, dbp,
        hr: parseInt(this.data.hr) || 75,
        symptoms: selectedSymptoms
      };

      // ★ 新增：外键约束失败(MySQL 1452)是账号身份数据问题(比如这台设备
      // 本地缓存的user_id指向一个服务器上已经不存在的账号)，不是网络
      // 问题，重试解决不了，反而白白多等好几秒才失败。检测到这种情况
      // 直接引导用户重新登录，不进入下面的重试循环。
      const isStaleIdentityError = (err) => {
        const msg = (err && err.message) || '';
        return msg.indexOf('FOREIGN KEY') !== -1 || msg.indexOf('foreign key constraint') !== -1 || msg.indexOf('1452') !== -1;
      };

      const requestWithRetry = (retries) => {
        cloudService.analyze(payload)
          .then((res) => {
            wx.hideLoading();
            if (res && res.code === 0) {
              const resultData = res.data;
              const newRecord = {
                userId: this.data.userId,
                datetime: fullDateTime,
                sbp, dbp,
                hr: parseInt(this.data.hr) || 75,
                symptoms: selectedSymptoms,
                riskLevel: resultData.riskLevel || 'normal',
                riskText: resultData.message || resultData.riskLevel || '',
                analysis: resultData
              };
              const currentHistory = wx.getStorageSync('measure_history') || [];
              currentHistory.unshift(newRecord);
              wx.setStorageSync('measure_history', currentHistory);
              const resultStr = encodeURIComponent(JSON.stringify(resultData));
              wx.navigateTo({ url: `/pages/measure/result/result?data=${resultStr}` });
            } else {
              wx.showModal({ title: '分析失败', content: (res && res.msg) || '服务异常，请重试' });
            }
          })
          .catch((err) => {
            if (isStaleIdentityError(err)) {
              wx.hideLoading();
              console.error('[submitAnalysis] 账号身份数据已失效(外键约束拒绝)', err);
              wx.showModal({
                title: '账号信息已失效',
                content: '本地保存的账号信息已经不存在，需要重新登录后才能继续测量。',
                showCancel: false,
                confirmText: '重新登录',
                success: () => {
                  wx.removeStorageSync('app_user_id');
                  wx.removeStorageSync('userId');
                  wx.removeStorageSync('userProfile');
                  wx.removeStorageSync('currentRole');
                  wx.reLaunch({ url: '/pages/onboarding/UserProfile/UserProfile' });
                }
              });
              return;
            }
            if (retries > 0) {
              setTimeout(() => requestWithRetry(retries - 1), 2000);
            } else {
              wx.hideLoading();
              wx.showToast({ title: '网络请求失败', icon: 'none' });
              console.error('analyze request failed', err);
            }
          });
      };
      requestWithRetry(3);
    } catch (err) {
      wx.hideLoading();
      console.error(err);
    }
  },

  goToMore() { wx.navigateTo({ url: '/pages/more/more' }); },

  goToFamilyDashboard() {
    const pid = wx.getStorageSync('family_patient_id') || '';
    const pname = wx.getStorageSync('family_patient_name') || pid;
    wx.navigateTo({ url: `/pages/family/dashboard/dashboard?patientId=${pid}&patientName=${encodeURIComponent(pname)}` });
  },

  goToDoctorDashboard() {
    // ★ 改：医生的默认落地页是患者列表，不是某一个患者的详情
    wx.navigateTo({ url: '/pages/doctor/patient-list/patient-list' });
  },

  goToLatestResult() {
    const history = wx.getStorageSync('measure_history') || [];
    if (history.length > 0) {
      const latest = history[0];
      if (latest.analysis) {
        const resultStr = encodeURIComponent(JSON.stringify(latest.analysis));
        wx.navigateTo({ url: `/pages/measure/result/result?data=${resultStr}` });
        return;
      }
    }
    wx.navigateTo({ url: '/pages/history/month/month' });
  },

  // ★ 改：跟着risk_level.py重构后的新版枚举值走(low/moderate/moderate_high/
  //   critical，不再有旧版的"high")——之前这里还在按旧枚举判断，导致
  //   moderate_high(Path A"中"档，比"关注"更需要留意的状态)完全没被处理，
  //   直接落进else变成不显示横幅，真正该被看到的状态反而被隐藏了。
  //   另外critical(Path B)不一定代表"数值偏高"，也可能是症状单独触发、
  //   数值完全正常——横幅文案不能再断言"偏高"，改成中性的"需要留意"，
  //   具体原因点进详情页看。颜色/文案直接在这里算好，wxml只管绑定，
  //   不再用嵌套三元表达式判断。
  checkAlertStatus() {
    const history = wx.getStorageSync('measure_history') || [];
    if (history.length === 0) {
      this.setData({ showAlert: false });
      return;
    }
    const latest = history[0];
    const riskLevel = latest.riskLevel || 'normal';

    const ALERT_CONFIG = {
      critical:      { bg: '#FFF0F0', dot: '#F44336', color: '#D32F2F', msg: '上次测量结果需要留意，点击查看详情' },
      moderate_high: { bg: '#FFF3E0', dot: '#FF9800', color: '#E65100', msg: '最近血压持续偏离，建议关注' },
      moderate:      { bg: '#FFF8E8', dot: '#FFC107', color: '#B8860B', msg: '最近血压有些波动' },
    };

    const cfg = ALERT_CONFIG[riskLevel];
    if (cfg) {
      this.setData({
        showAlert: true,
        alertBg: cfg.bg,
        alertDot: cfg.dot,
        alertColor: cfg.color,
        alertMsg: cfg.msg
      });
    } else {
      this.setData({ showAlert: false });
    }
  }
});