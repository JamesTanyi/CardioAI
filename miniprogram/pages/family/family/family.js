// pages/family/family/family.js
const app = getApp ? getApp() : wx.getSystemInfoSync() ? getApp() : null; // 兼容安全获取
// ★ 新增：把原来独立的"绑定管理"页面(pages/profile/bindings/)功能合并进这里——
//   绑定关系本来就是在这个页面发起的(邀请家人/邀请医生)，解绑放回同一个地方，
//   不用户再多跳转一层。数据来源和解绑动作复用 binding_views.py 已有的
//   get_my_bindings / cancel_binding 接口。
const cloudService = require('../../../utils/cloudService.js');

Page({
  data: {
    activeTab: 'family', // family | doctor
    userId: '',          // 当前的userId，用于调试
    currentRole: 'user',  // 当前角色
    // ── 已绑定列表(原绑定管理页面功能) ──
    bindingsLoading: true,
    doctorList: [],
    familyList: []
  },

  onLoad(options) {
    options = options || {};
    
    // 1. 🛠️ 核心修正：用微信缓存锁定当前角色，秒杀 app.getRole()
    const role = wx.getStorageSync('currentRole') || 'user';
    this.setData({ 
      currentRole: role 
    });

    // 2. 🛠️ 核心修正：启用右上角「···」菜单分享
    wx.showShareMenu({ withShareTicket: true });

    // 3. 🛠️ 核心修正：支持通过 tab 参数切换与兜底缓存读取
    if (options.tab === 'doctor') {
      this.setData({ activeTab: 'doctor' });
    } else if (options.tab === 'family') {
      this.setData({ activeTab: 'family' });
    } else {
      const lastTab = wx.getStorageSync('family_active_tab') || 'family';
      this.setData({ activeTab: lastTab });
    }

    // 4. 🛠️ 核心修正：获取当前用户ID用于调试
    const userId = wx.getStorageSync('app_user_id') || '';
    this.setData({ userId });
  },

  onShow() {
    // 每次显示都重新拉取一次，保证从"绑定成功"或"解绑成功"返回时列表是最新的
    this.loadBindings();
  },

  onPullDownRefresh() {
    this.loadBindings(() => wx.stopPullDownRefresh());
  },

  // ========== 已绑定列表(原绑定管理页面功能) ==========

  loadBindings(callback) {
    const openid = wx.getStorageSync('app_openid');
    if (!openid) {
      // 患者本人的身份信息缺失时静默失败即可，不打断邀请流程的正常使用
      this.setData({ bindingsLoading: false });
      if (callback) callback();
      return;
    }

    this.setData({ bindingsLoading: true });

    cloudService.getMyBindings(openid)
      .then((res) => {
        this.setData({ bindingsLoading: false });
        if (res.code === 0) {
          const data = res.data || {};
          this.setData({
            doctorList: data.doctorList || [],
            familyList: data.familyList || []
          });
        }
        // 加载失败时不弹toast——这个列表是邀请页面的附加功能，
        // 不该用错误提示打断用户正常发邀请的操作
        if (callback) callback();
      })
      .catch(() => {
        this.setData({ bindingsLoading: false });
        if (callback) callback();
      });
  },

  // 解绑医生
  unbindDoctor(e) {
    const { viewerId, name } = e.currentTarget.dataset;
    this._confirmUnbind('doctor', viewerId, name);
  },

  // 解绑家属
  unbindFamily(e) {
    const { viewerId, name } = e.currentTarget.dataset;
    this._confirmUnbind('family', viewerId, name);
  },

  _confirmUnbind(bindingType, viewerId, name) {
    const typeLabel = bindingType === 'doctor' ? '医生' : '家属';
    wx.showModal({
      title: `解除${typeLabel}绑定`,
      content: `确定解除跟"${name}"的绑定吗？解除后对方将无法再查看你的健康数据和留言。`,
      confirmColor: '#FF4D4F',
      success: (res) => {
        if (!res.confirm) return;
        this._doUnbind(bindingType, viewerId);
      }
    });
  },

  _doUnbind(bindingType, viewerId) {
    const openid = wx.getStorageSync('app_openid');
    const patientId = wx.getStorageSync('app_user_id');

    wx.showLoading({ title: '处理中...', mask: true });

    cloudService.cancelBinding({
      openid,
      bindingType,
      patientId,
      viewerId
    })
      .then((res) => {
        wx.hideLoading();
        if (res.code === 0) {
          wx.showToast({ title: '已解除绑定', icon: 'success' });
          this.loadBindings();
        } else {
          wx.showToast({ title: res.msg || '操作失败', icon: 'none' });
        }
      })
      .catch(() => {
        wx.hideLoading();
        wx.showToast({ title: '网络错误', icon: 'none' });
      });
  },

  /**
   * Tab 切换
   */
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    wx.setStorageSync('family_active_tab', tab);
  },

  /**
   * ★ 调试：模拟家属打开邀请链接
   * 改：邀请确认逻辑已拆分到 bind-confirm 页面，不再经过 intro
   */
  simulateFamilyInvite() {
    const patientId = wx.getStorageSync('app_user_id') || '';
    if (!patientId) {
      wx.showToast({ title: '请先注册', icon: 'none' });
      return;
    }
    wx.reLaunch({
      url: `/pages/onboarding/bind-confirm/bind-confirm?patientId=${patientId}&role=family`
    });
  },

  /**
   * ★ 调试：模拟医生打开邀请链接
   */
  simulateDoctorInvite() {
    const patientId = wx.getStorageSync('app_user_id') || '';
    if (!patientId) {
      wx.showToast({ title: '请先注册', icon: 'none' });
      return;
    }
    wx.reLaunch({
      url: `/pages/onboarding/bind-confirm/bind-confirm?patientId=${patientId}&role=doctor`
    });
  },

  /**
   * ★ V10 分享小程序卡片：携带患者ID+角色（永久链接）
   * 对方点开→验证患者→确认绑定→随时查看
   * 改：分享路径指向 bind-confirm，而不是 intro
   */
  onShareAppMessage() {
    const userId = wx.getStorageSync('app_user_id') || '';

    if (this.data.activeTab === 'doctor') {
      return {
        title: '患者邀请您作为医生查看心血管健康数据',
        path: userId ? `/pages/onboarding/bind-confirm/bind-confirm?patientId=${userId}&role=doctor` : '/pages/onboarding/intro/intro',
        imageUrl: ''
      };
    }
    return {
      title: '邀请您关注我的心血管健康',
      path: userId ? `/pages/onboarding/bind-confirm/bind-confirm?patientId=${userId}&role=family` : '/pages/onboarding/intro/intro',
      imageUrl: ''
    };
  }
});