// pages/onboarding/intro/intro.js
// ★ 职责单一化：这个页面现在只做两件事——欢迎展示 + 新老用户分流
//   原先的"邀请确认绑定"逻辑（V10 永久链接模式）已拆分到
//   pages/onboarding/bind-confirm/bind-confirm.js，
//   分享链接现在直接指向 bind-confirm 页面，不再经过这里。

Page({
  // ★ 新增：页面一加载就自动检查——之前角色跳转逻辑只写在 onStart() 里，
  //   而 onStart 只有用户点了"开始"按钮才会触发。如果家属/医生账号因为
  //   别的原因(比如冷启动默认落到这个页面)被带到这里，只要不点按钮，
  //   就会一直卡在欢迎页出不去。现在页面一打开就自动检查一次：
  //   如果已经是绑定过的家属/医生，立刻转走，不用等用户操作；
  //   真正的全新用户(还没有 userProfile)不受影响，仍然停留在欢迎页，
  //   走原来"点开始按钮→注册"这条路。
  onLoad() {
    this._guardAlreadyBoundRoles();
  },

  _guardAlreadyBoundRoles() {
    let userProfile = wx.getStorageSync('userProfile');
    if (!userProfile) {
      const recovered = this._recoverRoleFromStorage();
      if (recovered) {
        userProfile = wx.getStorageSync('userProfile');
      }
    }
    if (!userProfile) return; // 真正的新用户，留在欢迎页，等待点击"开始"

    const role = userProfile.role || 'user';
    if (role === 'family') {
      const pid = wx.getStorageSync('family_patient_id') || '';
      const pname = wx.getStorageSync('family_patient_name') || pid;
      if (pid) {
        wx.reLaunch({ url: `/pages/family/dashboard/dashboard?patientId=${pid}&patientName=${encodeURIComponent(pname)}` });
      } else {
        wx.reLaunch({ url: '/pages/family/family/family' });
      }
      return;
    }
    if (role === 'doctor') {
      const hasDoctor = wx.getStorageSync('has_doctor_binding');
      if (hasDoctor) {
        wx.reLaunch({ url: '/pages/doctor/patient-list/patient-list' });
      } else {
        wx.reLaunch({ url: '/pages/family/family/family' });
      }
      return;
    }
    // role 是 'user'(患者)：留在欢迎页，走原来点击"开始"按钮的流程
  },

  onStart() {
    let userProfile = wx.getStorageSync('userProfile');
    if (!userProfile) {
      const recovered = this._recoverRoleFromStorage();
      if (recovered) {
        userProfile = wx.getStorageSync('userProfile');
      }
    }

    if (!userProfile) {
      wx.navigateTo({ url: '/pages/onboarding/UserProfile/UserProfile' });
      return;
    }

    const role = userProfile.role || 'user';
    if (role === 'family') {
      const pid = wx.getStorageSync('family_patient_id') || '';
      const pname = wx.getStorageSync('family_patient_name') || pid;
      if (pid) {
        wx.reLaunch({ url: `/pages/family/dashboard/dashboard?patientId=${pid}&patientName=${encodeURIComponent(pname)}` });
      } else {
        wx.reLaunch({ url: '/pages/family/family/family' });
      }
      return;
    }
    if (role === 'doctor') {
      const hasDoctor = wx.getStorageSync('has_doctor_binding');
      if (hasDoctor) {
        // ★ 改：医生的长期入口是患者列表工作台，不再直接跳进"上次看的患者"详情
        wx.reLaunch({ url: '/pages/doctor/patient-list/patient-list' });
      } else {
        wx.reLaunch({ url: '/pages/family/family/family' });
      }
      return;
    }
    wx.reLaunch({ url: '/pages/index/index' });
  },

  // ====================================================
  // 角色恢复：兜底从本地缓存推断角色（比如 userProfile 意外丢失，
  // 但绑定关系相关的缓存字段还在时，避免用户重新走一遍注册）
  // ====================================================
  _recoverRoleFromStorage() {
    const app = getApp();
    const userId = wx.getStorageSync('app_user_id') || '';
    const savedRole = wx.getStorageSync('currentRole') || '';
    const hasFamily = wx.getStorageSync('has_family_binding');
    const hasDoctor = wx.getStorageSync('has_doctor_binding');
    const familyPid = wx.getStorageSync('family_patient_id') || '';
    const doctorPid = wx.getStorageSync('last_viewed_patient') || '';

    if (userId.startsWith('F') && (hasFamily || familyPid)) {
      wx.setStorageSync('userProfile', { name: '家属用户', role: 'family' });
      wx.setStorageSync('currentRole', 'family');
      app.setRole('family');
      return true;
    }
    if (userId.startsWith('D') && (hasDoctor || doctorPid)) {
      wx.setStorageSync('userProfile', { name: '医生用户', role: 'doctor' });
      wx.setStorageSync('currentRole', 'doctor');
      app.setRole('doctor');
      return true;
    }
    if (savedRole === 'family' && (hasFamily || familyPid)) {
      wx.setStorageSync('userProfile', { name: '家属用户', role: 'family' });
      app.setRole('family');
      return true;
    }
    if (savedRole === 'doctor' && (hasDoctor || doctorPid)) {
      wx.setStorageSync('userProfile', { name: '医生用户', role: 'doctor' });
      app.setRole('doctor');
      return true;
    }
    if (hasFamily && familyPid) {
      wx.setStorageSync('userProfile', { name: '家属用户', role: 'family' });
      wx.setStorageSync('currentRole', 'family');
      app.setRole('family');
      return true;
    }
    if (hasDoctor && doctorPid) {
      wx.setStorageSync('userProfile', { name: '医生用户', role: 'doctor' });
      wx.setStorageSync('currentRole', 'doctor');
      app.setRole('doctor');
      return true;
    }
    return false;
  }
});