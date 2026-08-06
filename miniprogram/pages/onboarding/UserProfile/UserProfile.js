// pages/onboarding/UserProfile/UserProfile.js
const app = getApp();
const cloudService = require('../../../utils/cloudService.js');

Page({
  data: {
    name: '',
    age: '',
    gender: '',
    birthDate: '', // 后台保持标准的 YYYY-MM-DD
    
    // 💡 专供老年人习惯的填空变量
    birthYear: '',
    birthMonth: '',
    birthDay: '',

    role: 'user',
    healthHistory: [],
    otherText: '',
    agreed: false,
    isLocked: false,
    isSubmitting: false // ★ 新增：注册请求进行中标志，防止重复提交
  },

  onLoad() {
    const profile = wx.getStorageSync('userProfile');
    console.log('[UserProfile] onLoad — userProfile from storage:', JSON.stringify(profile));
    
    if (profile && profile.name) {
      // 老用户：回显时自动将标准日期拆散，并去掉前导0恢复单位数显示（如 "08" 变 "8"）
      let y = '', m = '', d = '';
      if (profile.birthDate && profile.birthDate.includes('-')) {
        const parts = profile.birthDate.split('-');
        y = parts[0] || '';
        m = parts[1] ? parseInt(parts[1], 10).toString() : '';
        d = parts[2] ? parseInt(parts[2], 10).toString() : '';
      }
      this.setData({ 
        ...profile, 
        birthYear: y,
        birthMonth: m,
        birthDay: d,
        isLocked: true 
      });
      console.log('[UserProfile] 已锁定 (isLocked=true)');
    } else {
      console.log('[UserProfile] 未注册状态 (isLocked=false)');
      wx.removeStorageSync('userProfile');
    }
  },

  onShow() {
    const profile = wx.getStorageSync('userProfile');
    if (!profile || !profile.name) {
      if (this.data.isLocked) {
        console.log('[UserProfile] onShow 检测到 storage 已清空，强制解锁');
        this.setData({ isLocked: false, name: '', age: '', gender: '', birthDate: '', birthYear: '', birthMonth: '', birthDay: '', healthHistory: [] });
      }
    }
  },

  onInputName(e) {
    this.setData({ name: e.detail.value });
  },

  // 💡 填空监听：年
  onInputYear(e) {
    if (this.data.isLocked) return;
    let val = e.detail.value.replace(/\D/g, '');
    this.setData({ birthYear: val });
    this._checkAndCalculateAge();
  },

  // 💡 填空监听：月
  onInputMonth(e) {
    if (this.data.isLocked) return;
    let val = e.detail.value.replace(/\D/g, '');
    this.setData({ birthMonth: val });
    this._checkAndCalculateAge();
  },

  // 💡 填空监听：日
  onInputDay(e) {
    if (this.data.isLocked) return;
    let val = e.detail.value.replace(/\D/g, '');
    this.setData({ birthDay: val });
    this._checkAndCalculateAge();
  },

  /**
   * 🔍 核心计算中枢：静默合并、算年龄
   */
  _checkAndCalculateAge() {
    const { birthYear, birthMonth, birthDay } = this.data;
    if (birthYear.length === 4 && birthMonth.length >= 1 && birthDay.length >= 1) {
      // 在后台静默对单数月份补零（如 8 补成 08），绝不倒灌回填到输入框，防类型冲突
      const paddedMonth = birthMonth.padStart(2, '0');
      const paddedDay = birthDay.padStart(2, '0');
      
      const mNum = parseInt(paddedMonth, 10);
      const dNum = parseInt(paddedDay, 10);
      if (mNum < 1 || mNum > 12 || dNum < 1 || dNum > 31) {
        this.setData({ age: '', birthDate: '' });
        return; 
      }

      const standardDateStr = `${birthYear}-${paddedMonth}-${paddedDay}`;
      this.setData({ birthDate: standardDateStr });

      // 计算年龄
      const today = new Date();
      const birth = new Date(standardDateStr);
      let age = today.getFullYear() - birth.getFullYear();
      const m = today.getMonth() - birth.getMonth();
      if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) {
        age--;
      }
      this.setData({ age: age >= 0 ? age.toString() : '' });
    } else {
      this.setData({ age: '', birthDate: '' });
    }
  },

  onInputAge(e) {
    this.setData({ age: e.detail.value });
  },

  onSelectGender(e) {
    this.setData({ gender: e.currentTarget.dataset.gender });
  },

  onSelectRole(e) {
    this.setData({ role: e.currentTarget.dataset.role });
  },

  onToggleHealth(e) {
    const item = e.currentTarget.dataset.item;
    const healthHistory = [...this.data.healthHistory];
    const index = healthHistory.indexOf(item);
    if (index > -1) {
      healthHistory.splice(index, 1);
    } else {
      healthHistory.push(item);
    }
    this.setData({ healthHistory });
  },

  onToggleOther() {
    const healthHistory = [...this.data.healthHistory];
    const index = healthHistory.findIndex(
      item => item.startsWith('其他') || item === '其他'
    );
    if (index > -1) {
      healthHistory.splice(index, 1);
      this.setData({ healthHistory });
    } else {
      wx.showModal({
        title: '其他病史',
        content: '请输入其他病史',
        placeholderText: '例如：糖尿病、肾病等',
        editable: true,
        success: (res) => {
          if (res.confirm && res.content) {
            healthHistory.push('其他: ' + res.content);
            this.setData({ healthHistory });
          }
        }
      });
    }
  },

  onToggleAgreement() {
    this.setData({ agreed: !this.data.agreed });
  },

  // ★ 改：onSubmit 现在是 async 函数，同步等待后端注册成功后才跳转
  async onSubmit() {
    if (this.data.isSubmitting) return; // 防止重复点击导致重复请求

    const { name, age, gender, role, agreed, birthDate, birthYear, birthMonth, birthDay } = this.data;

    if (!name) return wx.showToast({ title: '请输入姓名', icon: 'none' });
    if (!birthYear || !birthMonth || !birthDay || !birthDate) {
      return wx.showToast({ title: '请完整填写出生年月日', icon: 'none' });
    }
    if (!age)       return wx.showToast({ title: '请输入年龄', icon: 'none' });
    if (!gender)    return wx.showToast({ title: '请选择性别', icon: 'none' });
    if (!agreed)    return wx.showToast({ title: '请先阅读并同意免责条款', icon: 'none' });

    // 💾 统一覆盖保存用户的档案基本集（本地缓存，先于网络请求写入，保证离线也有数据兜底）
    wx.setStorageSync('userProfile', this.data);

    // 🛡️ 修复核心：兼容处理 app.setRole 报错问题
    // 优先尝试调用原厂 app.setRole，如果没有定义，则降级通过本地缓存记录角色
    if (app && typeof app.setRole === 'function') {
      app.setRole(role);
    } else {
      wx.setStorageSync('currentRole', role);
      console.log('📌 [UserProfile] app.setRole不存在，已自动通过缓存降级记录角色:', role);
    }

    // ★ 改：不再自己生成 user_id——身份识别体系重构后，openid 才是身份锚点，
    //   openid 由 app.js 在小程序启动时通过 wx.login() 换取并存在本地，
    //   user_id 现在由后端根据 openid 决定（老用户复用原有的，新用户后端生成）
    const openid = wx.getStorageSync('app_openid');
    if (!openid) {
      wx.showModal({
        title: '登录异常',
        content: '未能获取微信身份信息，请检查网络后重新打开小程序',
        showCancel: false
      });
      return;
    }

    // ★ 新增：同步等待后端注册成功后才继续跳转流程
    this.setData({ isSubmitting: true });
    wx.showLoading({ title: '注册中...', mask: true });

    try {
      const res = await cloudService.registerUser({
        openid,
        name,
        age,
        gender,
        role,
        birth_date: birthDate // ★ 新增：把出生日期一并传给后端，供家属/医生端展示识别
      });

      wx.hideLoading();

      if (!res || res.code !== 0) {
        this.setData({ isSubmitting: false });
        wx.showModal({
          title: '注册失败',
          content: (res && res.msg) || '服务异常，请重试',
        });
        return; // ★ 注册失败：不跳转，留在当前页，避免本地以为注册成功、后端却没有记录
      }

      // ★ 新增：把后端返回的真正 user_id 存进本地缓存
      //   （老用户会拿到原有的 user_id，新用户拿到后端新生成的）
      const returnedUserId = res.data && res.data.userId;
      if (returnedUserId) {
        wx.setStorageSync('app_user_id', returnedUserId);
      }
    } catch (err) {
      wx.hideLoading();
      this.setData({ isSubmitting: false });
      console.error('[UserProfile] registerUser 请求失败:', err);
      wx.showModal({
        title: '网络异常',
        content: '注册请求失败，请检查网络后重试',
      });
      return; // ★ 网络异常：同样不跳转
    }

    this.setData({ isSubmitting: false });

    const pendingToken = wx.getStorageSync('pending_invite_token');
    if (pendingToken) {
      wx.removeStorageSync('pending_invite_token');
      wx.reLaunch({ url: `/pages/onboarding/intro/intro?token=${pendingToken}` });
      return;
    }

    if (role === 'family' || role === 'doctor') {
      wx.reLaunch({ url: '/pages/family/family/family' });
    } else {
      wx.reLaunch({ url: '/pages/index/index' });
    }
  },
  goHome() {
    wx.reLaunch({ url: '/pages/index/index' });
  },

  onShareAppMessage() {
    const userProfile = wx.getStorageSync('userProfile') || {};
    const name = userProfile.name || '我';
    return {
      title: `${name} 推荐给您：专业的智能心血管健康管家`,
      path: '/pages/index/index',
      imageUrl: '/images/share-cover.png'
    };
  }
});