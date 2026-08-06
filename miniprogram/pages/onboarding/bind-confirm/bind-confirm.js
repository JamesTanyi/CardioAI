// pages/onboarding/bind-confirm/bind-confirm.js
// ★ 拆分自原 intro.js 的邀请确认逻辑（V10 永久链接模式）
// 这个页面只做一件事：家属/医生点开患者的邀请链接后，
// 校验邀请是否有效 → 展示患者摘要 → 用户确认/取消绑定
// intro 页面不再承担这部分职责，保持"欢迎+新老用户分流"单一职责。

const cloudService = require('../../../utils/cloudService.js');

Page({
  data: {
    confirmRole: '',          // 'family' | 'doctor'
    confirmFromUserId: '',    // 患者 user_id
    confirmFromUserName: '',  // 患者展示名（姓名+出生日期）
    confirmViewerOpenid: '',  // 家属/医生自己的 openid（真正的身份锚点）
    confirmPatientInfo: null, // 患者摘要（来自 /validate_invite）
    confirmLoading: true,
    confirmSubmitting: false,
    tokenError: '',           // 验证失败时的错误文案
    // ★ 新增：家属/医生自己的姓名，改成让本人手动填写，不再用微信账号信息
    //   或自动生成的描述文字("患者名+的家属")兜底——那样存进去的根本不是
    //   本人真实姓名，是绑定管理页面显示"全是患者自己名字"这个bug的真正源头。
    inputName: '',
    // ★ 新增：医生角色专属，专业(科室)和医院改成绑定时由医生本人填写，
    //   均为选填项（之前的产品设计是完全不收集，导致这两项一直是空的）
    inputDepartment: '',
    inputHospital: '',
    // ★ 新增：姓名是否已填写——不光在点击"确认绑定"时才校验，按钮本身也
    //   跟这个状态联动直接置灰，避免用户没注意到toast提示就以为点了没反应
    canConfirm: false
  },

  onLoad(options) {
    const app = getApp();
    if (app.globalData.appReady) {
      this._initFromInvite(options);
    } else {
      // 冷启动场景：等 app.js 的 onLaunch 完成初始绑定同步后再继续
      app.readyCallback = (launchOptions) => {
        this._initFromInvite(launchOptions.query || options);
      };
    }
  },

  _initFromInvite(options) {
    const app = getApp();
    const patientId = options.patientId;
    const role = options.role;

    if (!patientId || !role) {
      this.setData({ confirmLoading: false, tokenError: '邀请链接无效（缺少必要参数）' });
      return;
    }

    this.setData({ confirmLoading: true, tokenError: '' });

    cloudService.validateInvite(patientId, role)
      .then((res) => {
        if (!res || res.code !== 0) {
          this.setData({
            confirmLoading: false,
            tokenError: (res && res.msg) || '邀请链接无效或已失效'
          });
          return;
        }

        const { patientName, patientSummary } = res.data;

        // ★ 改：不再自己生成 viewer 的 user_id——openid 由 app.js 在启动时
        //   通过 wx.login() 换取并存在本地，绑定时把 openid 传给后端，
        //   后端会用 openid 找到/建立这个人的真正 user_id
        const openid = wx.getStorageSync('app_openid');
        if (!openid) {
          this.setData({
            confirmLoading: false,
            tokenError: '未能获取微信身份信息，请检查网络后重新打开链接'
          });
          return;
        }

        wx.setStorageSync('currentRole', role);
        app.setRole(role);

        // ★ 再次修复：这里原来会用 curProfile.name 给姓名框做"预填"，
        //   本意是方便老用户不用重复输入，但引发了一个更隐蔽的问题——
        //   app.js 的 _resolveIdentity() 每次冷启动都会用 wx_login 查到的
        //   服务器身份覆盖本地 userProfile.name。如果这个微信账号已经在
        //   服务器注册过(不管是作为患者、还是之前绑过的别的身份)，
        //   curProfile.name 读到的就是"服务器记得的那个身份的名字"，
        //   不是"这次绑定该填的名字"——现实中一个人完全可能同时是
        //   某患者的家属、又是另一位患者的医生，每次绑定该填的名字
        //   不该被"这个微信账号历史上注册过的身份"污染。
        //   姓名这一项彻底不做任何预填，每次都强制留空，必须本人手动输入。
        //   （科室/医院不受这个问题影响：_resolveIdentity 覆盖 userProfile
        //   时压根没写这两个字段，继续保留预填不会有同样的污染风险）
        const curProfile = wx.getStorageSync('userProfile') || {};

        this.setData({
          confirmLoading: false,
          confirmRole: role,
          confirmFromUserId: patientId,
          confirmFromUserName: patientName,
          confirmViewerOpenid: openid,
          confirmPatientInfo: patientSummary,
          inputName: '',
          inputDepartment: curProfile.department || '',
          inputHospital: curProfile.hospital || '',
          canConfirm: false,
          _invitePatientId: patientId,
          _inviteRole: role
        });
      })
      .catch((err) => {
        console.error('[bind-confirm] validate_invite error:', err);
        this.setData({ confirmLoading: false, tokenError: '网络错误，请检查网络后重试' });
      });
  },

  onInputName(e) {
    const value = e.detail.value;
    this.setData({ inputName: value, canConfirm: !!value.trim() });
  },

  onInputDepartment(e) {
    this.setData({ inputDepartment: e.detail.value });
  },

  onInputHospital(e) {
    this.setData({ inputHospital: e.detail.value });
  },

  // ====================================================
  // 用户点击"确认绑定" → /bind_by_invite（永久链接）
  // ====================================================
  onConfirmBind() {
    if (this.data.confirmSubmitting) return;

    const name = (this.data.inputName || '').trim();
    if (!name) {
      wx.showToast({ title: '请输入您的姓名', icon: 'none' });
      return;
    }

    this.setData({ confirmSubmitting: true });
    wx.showLoading({ title: '确认中...', mask: true });

    const { confirmViewerOpenid, confirmRole, _invitePatientId } = this.data;
    const department = (this.data.inputDepartment || '').trim();
    const hospital = (this.data.inputHospital || '').trim();

    // ★ 改：viewerName 现在是用户在上面输入框里自己填的姓名，不再从
    //   微信账号缓存/自动生成的描述文字里取——这是绑定管理页面显示的
    //   姓名不准确问题的根本修复。医生角色额外带上 department/hospital，
    //   后端 bind_by_invite 其实早就支持接收这两项(data.get('hospital')/
    //   data.get('department'))，只是之前前端一直没传。
    const payload = {
      patientId: _invitePatientId,
      role: confirmRole,
      viewerOpenid: confirmViewerOpenid,
      viewerName: name
    };
    if (confirmRole === 'doctor') {
      payload.department = department;
      payload.hospital = hospital;
    }

    // ★ 新增：诊断日志，确认三个必填参数到底哪个是空的
    console.log('🔵 [bind-confirm] onConfirmBind payload:', JSON.stringify(payload));

    cloudService.bindByInvite(payload)
      .then((res) => {
        wx.hideLoading();
        if (res && res.code === 0) {
          // ★ 新增：后端返回真正的 viewerId（老用户复用原有的，新用户后端生成），
          //   前端拿到后要存进本地缓存，之后所有查询才知道"我是谁"
          const realViewerId = res.data && res.data.viewerId;
          if (realViewerId) {
            wx.setStorageSync('app_user_id', realViewerId);
          }
          // ★ 新增：把这次真实填写的姓名(以及医生的科室/医院)存进本地缓存，
          //   下次这个人再确认别的绑定邀请时可以直接预填，不用重复输入
          const profileToSave = { name, role: confirmRole };
          if (confirmRole === 'doctor') {
            profileToSave.department = department;
            profileToSave.hospital = hospital;
          }
          wx.setStorageSync('userProfile', profileToSave);
          this._afterConfirmSuccess(this.data.confirmFromUserName);
        } else {
          wx.showToast({ title: (res && res.msg) || '绑定失败', icon: 'none', duration: 3000 });
          this.setData({ confirmSubmitting: false });
        }
      })
      .catch((err) => {
        wx.hideLoading();
        console.error('[bind-confirm] bind_by_invite fail:', err);
        wx.showToast({ title: '网络错误，请重试', icon: 'none' });
        this.setData({ confirmSubmitting: false });
      });
  },

  // 用户点击"取消"：回到欢迎页，走正常的新老用户分流
  onRejectBind() {
    wx.reLaunch({ url: '/pages/onboarding/intro/intro' });
  },

  // 邀请验证失败时，跳过绑定直接注册
  onSkipToRegister() {
    wx.reLaunch({ url: '/pages/onboarding/UserProfile/UserProfile' });
  },

  // ====================================================
  // 确认成功后：建立长期入口标记，跳转到对应仪表盘
  // ====================================================
  _afterConfirmSuccess(label) {
    const app = getApp();
    const { confirmRole, confirmFromUserId } = this.data;

    if (confirmRole === 'family') {
      app.setRole('family');
      wx.setStorageSync('has_family_binding', true);
      wx.setStorageSync('family_patient_id', confirmFromUserId);
      wx.setStorageSync('family_patient_name', label);
      console.log('✅ [bind] 家属绑定存储完成 → role=family, pid=', confirmFromUserId, 'name=', label);
    } else {
      app.setRole('doctor');
      wx.setStorageSync('has_doctor_binding', true);
      // ★ 改：不再提前写入 last_viewed_patient/last_viewed_patient_name——
      //   医生的落地页现在是患者列表，不需要"记住上次看的患者"这件事在绑定这一刻发生。
      //   这个字段本身仍然有用（比如医生退出重进时想恢复到上次看的详情页），
      //   但应该只在用户真正点开某个患者详情时才写（patient-list.js 的 onSelectPatient 已经在做这件事）。
      //   之前在这里提前写入，会和 reLaunch 触发的 app.onShow → _autoRouteByRole 产生竞态，
      //   导致绑定成功后有时会被错误地带去这个患者的详情页，而不是列表页。
      console.log('✅ [bind] 医生绑定存储完成 → role=doctor, pid=', confirmFromUserId, 'name=', label);
    }

    app.refreshBindings(() => {
      app.globalData._hasAutoRouted = false;
      if (confirmRole === 'family') {
        wx.reLaunch({ url: `/pages/family/dashboard/dashboard?patientId=${confirmFromUserId}&patientName=${encodeURIComponent(label)}` });
      } else {
        // ★ 改：医生首次绑定成功后，进入患者列表工作台（新绑定的患者会出现在列表里），
        //   而不是直接跳进这一个患者的详情——医生的默认落地页是列表，不是某个患者
        wx.reLaunch({ url: '/pages/doctor/patient-list/patient-list' });
      }
    });
  }
});