// pages/profile/share/share.js —— ✨ 纯净直连版（去 Token，直接携带 patientId）
const qrCode = require('weapp-qrcode-canvas-2d');
const app = getApp();

Page({
  data: {
    userId: '',
    userName: '',
    qrReady: false,
    selectedRole: 'family' // 默认选择邀请：'family' | 'doctor'
  },

  onLoad() {
    let userId = wx.getStorageSync('app_user_id') || wx.getStorageSync('userId');
    if (!userId) {
      // 如果没有 ID，生成一个本地唯一 ID
      userId = 'U' + Math.floor(Math.random() * 900000 + 100000);
      wx.setStorageSync('app_user_id', userId);
    }
    const profile = wx.getStorageSync('userProfile') || {};
    this.setData({
      userId,
      userName: profile.name || ''
    });
  },

  onReady() {
    // 页面准备好后，直接根据当前数据绘制二维码
    this.drawQrCode();
  },

  /**
   * 🔄 切换邀请角色（家属/医生）
   */
  onRoleChange(e) {
    const role = e.currentTarget.dataset.role;
    if (role === this.data.selectedRole) return;
    this.setData({ selectedRole: role, qrReady: false });
    
    // 角色切换后，直接重新绘制对应的二维码，不需要呼叫后端
    this.drawQrCode();
  },

  /**
   * 📋 复制长期邀请链接
   */
  onCopyInviteLink() {
    const { userId, selectedRole } = this.data;
    // 直接拼接长期有效的物理绑定路径
    const invitePath = `/pages/onboarding/intro/intro?patientId=${userId}&role=${selectedRole}`;
    
    wx.setClipboardData({
      data: invitePath,
      success: () => { wx.showToast({ title: '长期链接已复制', icon: 'success' }); }
    });
  },

  /**
   * 🎨 绘制直连二维码（扫码直接触发绑定）
   */
  drawQrCode() {
    const { userId, selectedRole } = this.data;
    // 二维码中直接写入直连路径
    const qrText = `pages/onboarding/intro/intro?patientId=${userId}&role=${selectedRole}`;

    const query = wx.createSelectorQuery();
    query.select('#qrcode')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0]) return;
        const canvas = res[0].node;
        try {
          qrCode({
            canvas,
            canvasId: 'qrcode',
            width:  res[0].width,
            height: res[0].height,
            text:   qrText,
            level:  'H',
            padding: 16,
            background: '#ffffff',
            foreground: '#222222',
          });
          this.setData({ qrReady: true });
        } catch (e) {
          console.error('二维码生成失败:', e);
        }
      });
  },

  // pages/profile/share/share.js 里的分享配置
  onShareAppMessage() {
    const { userId, userName, selectedRole } = this.data;
    const name = userName || '我';
    
    // 💡 纯净打包：这个路径是留给【对方】点开看的，患者自己绝对不要在本地执行跳转！
    const permanentPath = `/pages/onboarding/intro/intro?patientId=${userId}&role=${selectedRole}`;

    console.log(`📤 [患者端] 成功打包微信卡片，等待选择好友发送。生成路径: ${permanentPath}`);

    return {
      title: selectedRole === 'doctor'
        ? `${name} 邀请您作为【医生】绑定并管理其健康数据`
        : `${name} 邀请您作为【家属】绑定并关注TA的心血管健康`,
      path: permanentPath
    };
  }
});