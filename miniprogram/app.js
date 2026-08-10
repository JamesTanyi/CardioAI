// app.js  — 全局绑定中枢 + 预警轮询引擎 + APP式角色路由

const cloudService = require('./utils/cloudService.js');

App({
  onLaunch(options) {
    // ★ 云托管初始化：必须在任何 wx.cloud.* 调用之前执行，且只需要执行一次
    wx.cloud.init({
      env: 'prod-d1gpx7r222b5853a8',
      traceUser: true
    });

    // ★ 新增：本地调试模式(USE_LOCAL_DEBUG=true，定义在cloudService.js)——
    //   wx_login依赖云托管自动注入的X-WX-OPENID，本地直连Flask走的是普通
    //   wx.request，没有这个机制，_resolveIdentity()在本地模式下必然拿不到
    //   真实身份。所以本地模式下完全跳过它，直接信任本地缓存里手动写好的
    //   测试账号(app_openid/app_user_id/currentRole)——测试时在开发者工具
    //   Console里手动 wx.setStorageSync 这三项来"变身"成不同测试账号，
    //   不需要真的登录，也不会被这里覆盖掉。
    if (cloudService.USE_LOCAL_DEBUG) {
      console.log('🟡 [本地调试模式] 跳过wx_login身份识别，使用本地缓存的测试账号');
      this.globalData.openid = wx.getStorageSync('app_openid') || '';
      this.globalData.currentRole = wx.getStorageSync('currentRole') || 'user';
      this.syncAllBindings(() => {
        this.globalData.appReady = true;
        if (this.readyCallback) {
          this.readyCallback(options);
        }
      });
      return;
    }

    // ★ 改：身份识别体系重构——每次冷启动都先做一次身份确认，
    //   不管是通过邀请链接、搜索、桌面图标、"我的小程序"哪种方式打开，
    //   只要还是同一个微信号，就能自动找回身份和绑定关系，
    //   不再完全依赖本地存储（本地存储清空/换设备也不怕）。
    this._resolveIdentity(() => {
      this.syncAllBindings(() => {
        this.globalData.appReady = true; // ★ 标记 App 已准备就绪
        if (this.readyCallback) {
          this.readyCallback(options);
        }
      });
    });
  },

  onShow(options) {
    // ★ 修复：冷启动时 onLaunch 里的 _resolveIdentity() 是异步的，onShow 几乎总是
    //   会在它完成之前就先触发——这时候 wx.getStorageSync('app_user_id') 读到的
    //   可能还是上一次的旧值(甚至是空的)，用这份过期数据做绑定同步和自动路由会不准。
    //   之前代码里已经埋了 readyCallback 这个钩子，但一直没有真正接上——现在接上：
    //   appReady 还没就绪时，把这次要做的事情排进 readyCallback，等 onLaunch 真正
    //   跑完身份确认再执行，不提前用旧数据抢跑。
    if (this.globalData.appReady) {
      this.syncAllBindings(() => {
        this._autoRouteByRole();
      });
      this.startAlertPolling();
    } else {
      // 注意：不在这里重复调用 syncAllBindings——onLaunch 自己的链路已经在做，
      // 等它做完触发 readyCallback 时，绑定数据已经是最新的，直接路由+开轮询即可
      this.readyCallback = () => {
        this._autoRouteByRole();
        this.startAlertPolling();
      };
    }
  },

  onHide() {
    // 切到后台停止轮询，省电
    this.stopAlertPolling();
  },

  // ────────────────────────────────────────
  // ★ 身份确认——直接调用后端 /wx_login，openid 由微信云托管在
  //   wx.cloud.callContainer 调用时自动注入到请求头（X-WX-OPENID），
  //   不需要 wx.login() 拿 code 再置换这一步。
  //   （最初设计走 wx.login+jscode2session，实测云托管出网访问
  //   api.weixin.qq.com 会撞上 SSL 自签名证书校验失败，且这套流程
  //   本来就是多余的——查微信官方文档确认了这一点，现在改成直接读请求头，
  //   更简单也更安全，不再需要 AppSecret，也没有出网请求）
  // ────────────────────────────────────────
  _resolveIdentity(callback) {
    console.log('🔵 [identity] 开始身份确认...');
    cloudService.wxLogin()
      .then((res) => {
        console.log('🔵 [identity] wx_login 接口返回:', JSON.stringify(res));
        if (res && res.code === 0 && res.data) {
          const d = res.data;
          wx.setStorageSync('app_openid', d.openid);
          this.globalData.openid = d.openid;
          console.log('✅ [identity] 已获取 openid:', d.openid, ' isNewUser:', d.isNewUser);

          if (!d.isNewUser) {
            // ★ 老用户：服务器返回的身份是唯一可信来源，用它覆盖本地缓存，
            //   而不是反过来用本地缓存去猜——这样清缓存/换设备也能自动恢复
            wx.setStorageSync('app_user_id', d.userId);
            wx.setStorageSync('currentRole', d.role || 'user');
            wx.setStorageSync('userProfile', {
              name: d.name || '',
              role: d.role || 'user',
              birthDate: d.birthDate || '',
              age: d.age,
              gender: d.gender || ''
            });
            this.globalData.currentRole = d.role || 'user';
            console.log('✅ [identity] 老用户身份已恢复:', d.userId, d.role);
          } else {
            console.log('✅ [identity] 新用户，等待注册/绑定流程');
          }
          // 新用户：不动 app_user_id/currentRole，交给注册/绑定流程走完后再确定
        } else {
          console.warn('⚠️ [identity] wx_login 返回异常，降级使用本地缓存', res);
          this._restoreLocalRoleFallback();
        }
        if (callback) callback();
      })
      .catch((err) => {
        // ★ 改：JSON.stringify(Error对象) 会丢失 message 属性变成 {}，
        //   改用 err.message/err.errMsg 才能看到真正的报错原因（比如 HTTP 404/500）
        console.warn('⚠️ [identity] wx_login 请求失败，降级使用本地缓存 | message:', err && err.message, '| errMsg:', err && err.errMsg, '| 完整对象:', err);
        this._restoreLocalRoleFallback();
        if (callback) callback();
      });
  },

  // ★ 兜底：wx_login 失败时（比如网络问题），退回原来的做法——
  //   直接信任本地缓存里的角色，保证功能不整个瘫痪，只是暂时失去"自动找回身份"这个能力
  _restoreLocalRoleFallback() {
    const savedRole = wx.getStorageSync('currentRole');
    if (savedRole) {
      this.globalData.currentRole = savedRole;
    }
  },

  globalData: {
    userInfo: null,
    currentRole: 'user',
    openid: '',

    // ★ 绑定数据（APP 启动时从后端同步，所有页面共用）
    bindings: null,        // 完整绑定状态对象 { hasFamilyBinding, hasDoctorBinding, familyPatients, doctorPatients, ... }
    bindingsReady: false,  // 是否已完成首次同步
    appReady: false,       // ★ App 是否已完成 onLaunch 的所有异步操作
    bindingsError: false,  // 同步是否失败

    // ★ 预警角标（全局共享，驱动首页/更多页角标显示）
    alertBadge: {
      familyRisk: 'none',        // none / normal / moderate / high
      doctorAlertCount: 0,       // 需关注的患者数
      familyPatientName: '',     // 家属绑定的患者名
      selfUnreadFeedbackCount: 0, // 作为患者，自己名下所有医生线的未读留言总数
      timestamp: 0               // 上次更新时间
    },
  },

  // ────────────────────────────────────────
  // ★ 核心：从后端同步全部绑定 + 预警状态
  // ────────────────────────────────────────
  syncAllBindings(callback) {
    const userId = wx.getStorageSync('app_user_id');
    if (!userId) {
      this.globalData.bindingsReady = false;
      this.globalData.bindings = null;
      if (callback) callback();
      return;
    }

    cloudService.getBindingStatus(userId)
      .then((res) => {
        if (res && res.code === 0) {
          const d = res.data || {};
          this.globalData.bindings = d;
          this.globalData.bindingsReady = true;
          this.globalData.bindingsError = false;

          // 同步更新 storage（兼容旧页面）
          if (d.hasFamilyBinding && d.familyPatients && d.familyPatients.length > 0) {
            const p = d.familyPatients[0];
            wx.setStorageSync('family_patient_id', p.patientId);
            wx.setStorageSync('family_patient_name', p.patientName);
            wx.setStorageSync('has_family_binding', true);
          }
          if (d.hasDoctorBinding && d.doctorPatients && d.doctorPatients.length > 0) {
            const dp = d.doctorPatients[0];
            wx.setStorageSync('last_viewed_patient', dp.patientId);
            wx.setStorageSync('last_viewed_patient_name', dp.patientName || dp.patientId);
            wx.setStorageSync('has_doctor_binding', true);
          }

          // 更新预警角标
          this.globalData.alertBadge = {
            familyRisk: d.familyAlertRisk || 'none',
            doctorAlertCount: d.doctorAlertCount || 0,
            familyPatientName: (d.familyAlertSummary && d.familyAlertSummary.patientName) || '',
            // ★ 新增：作为患者，自己名下所有医生线的未读留言总数——之前 more.js
            //   是自己另外发一个 getFeedback(userId) 请求来算这个数字，多医生留言
            //   隔离上线后 doctorId 变成必填参数，那个旧调用已经失效(会400)。
            //   现在统一改成 syncAllBindings 已经在同步的这份数据里带出来，
            //   more.js 直接读，不用再单独发请求。
            selfUnreadFeedbackCount: d.selfUnreadFeedbackCount || 0,
            timestamp: Date.now()
          };
          wx.setStorageSync('global_alert_badge', JSON.stringify(this.globalData.alertBadge));
        } else {
          this.globalData.bindingsError = true;
          console.error('syncAllBindings unexpected response', res);
        }
        if (callback) callback();
      })
      .catch(() => {
        this.globalData.bindingsError = true;
        console.error('syncAllBindings request failed');
        const cached = wx.getStorageSync('global_alert_badge');
        if (cached) {
          try { this.globalData.alertBadge = JSON.parse(cached); } catch (e) {}
        }
        if (callback) callback();
      });
  },

  // ────────────────────────────────────────
  // ★ APP式自动路由：根据角色+绑定状态自动跳转到正确页面（安全兜底）
  // intro.js / bind-confirm.js 已自行处理路由，此方法仅在以下场景生效：
  //   1) 从后台恢复时用户不在正确页面
  //   2) 其他页面意外落到 index 时
  // ────────────────────────────────────────
  _autoRouteByRole() {
    const role = this.getRole();
    const bindings = this.globalData.bindings;
    const pages = getCurrentPages();
    const currentPage = pages.length > 0 ? pages[pages.length - 1].route : '';

    // ★ bind-confirm 页面（邀请确认流程）不能被全局路由打断，
    //   否则用户点开邀请链接后会被这里强制跳走，看不到确认弹窗
    if (currentPage === 'pages/onboarding/bind-confirm/bind-confirm') return;

    // ★ 修复：这里之前只排除了各角色"唯一的主页"，只要用户当前停在留言板、
    //   历史记录页这类主页以外的任何页面，切到后台再切回来(触发 onShow)都会被
    //   强制 reLaunch 弹回主页，正在看的东西直接丢失——这跟上面注释写的
    //   "只在用户不在正确页面/意外落到 index 时生效"完全对不上，实际逻辑比
    //   注释描述的意图激进得多。改成：只有当前页面真的是空白或者首页(index)
    //   这种"确实需要引导去哪"的情况才自动跳转，用户已经在任何一个正常的
    //   业务页面里（不管是主页、留言板、历史记录……）都不打断。
    // ★ 修复：app.json 的 pages 数组第一项是欢迎页(pages/onboarding/intro/intro)，
    //   小程序冷启动/刷新天生就会先落到这个页面(平台规则，不是配置错了)。
    //   但这里原来的判断只认"页面是空的"或者"是index"，没把欢迎页算进去——
    //   导致已经绑定过的家属/医生账号，每次冷启动/刷新都会卡在欢迎页出不去
    //   (这段逻辑一看"当前页面不是index"，就当成"用户已经在正常业务页面"，
    //   直接放过不跳转)。现在把欢迎页也纳入"该触发自动跳转"的范围——
    //   对已绑定的家属/医生，下面的角色判断会正确带去对应的看板；
    //   对真正的全新用户(role还是默认的'user')，下面两个if分支都不会命中，
    //   函数会自然走空、不做任何跳转，欢迎页该怎么显示还怎么显示，不受影响。
    const shouldAutoRoute = !currentPage
      || currentPage === 'pages/index/index'
      || currentPage === 'pages/onboarding/intro/intro';
    if (!shouldAutoRoute) return;

    const hasLocalFamily = wx.getStorageSync('has_family_binding');
    const hasLocalDoctor = wx.getStorageSync('has_doctor_binding');

    if (role === 'family') {
      const serverHas = bindings && bindings.hasFamilyBinding;
      const fpServer = serverHas && bindings.familyPatients && bindings.familyPatients[0];
      if (fpServer) {
        const url = `/pages/family/dashboard/dashboard?patientId=${fpServer.patientId}&patientName=${encodeURIComponent(fpServer.patientName || fpServer.patientId)}`;
        wx.reLaunch({ url });
        return;
      }
      if (hasLocalFamily) {
        const localPid = wx.getStorageSync('family_patient_id') || '';
        const localPname = wx.getStorageSync('family_patient_name') || localPid;
        if (localPid && currentPage !== 'pages/family/dashboard/dashboard') {
          wx.reLaunch({ url: `/pages/family/dashboard/dashboard?patientId=${localPid}&patientName=${encodeURIComponent(localPname)}` });
        }
        return;
      }
      if (!hasLocalFamily) {
        if (currentPage !== 'pages/family/family/family' && currentPage !== 'pages/onboarding/UserProfile/UserProfile') {
          wx.reLaunch({ url: '/pages/family/family/family' });
        }
        return;
      }
      return;
    }

    if (role === 'doctor') {
      const serverHas = bindings && bindings.hasDoctorBinding;
      // ★ 改：医生端不再自动挑选"风险最高的患者"直接跳进详情——
      //   医生的长期入口是患者列表工作台，具体看哪个患者由医生自己在列表里点选
      if (serverHas || hasLocalDoctor) {
        if (currentPage !== 'pages/doctor/patient-list/patient-list') {
          wx.reLaunch({ url: '/pages/doctor/patient-list/patient-list' });
        }
        return;
      }
      if (!hasLocalDoctor) {
        if (currentPage !== 'pages/family/family/family' && currentPage !== 'pages/onboarding/UserProfile/UserProfile') {
          wx.reLaunch({ url: '/pages/family/family/family' });
        }
        return;
      }
      return;
    }
  },

  // ────────────────────────────────────────
  // ★ 预警轮询（前台每60秒静默刷新）
  // ────────────────────────────────────────
  startAlertPolling() {
    this.stopAlertPolling();
    this._alertTimer = setInterval(() => {
      try {
        this.syncAllBindings();
      } catch (e) {
        console.warn('⚠️ [poll] interval error:', e);
      }
    }, 60000);
  },

  stopAlertPolling() {
    if (this._alertTimer) {
      clearInterval(this._alertTimer);
      this._alertTimer = null;
    }
  },

  // ────────────────────────────────────────
  // 刷新绑定（页面可主动调用）
  // ────────────────────────────────────────
  refreshBindings(callback) {
    const userId = wx.getStorageSync('app_user_id');
    if (!userId) {
      if (callback) callback(null);
      return;
    }
    cloudService.getBindingStatus(userId)
      .then((res) => {
        if (res && res.code === 0) {
          this.globalData.bindings = res.data || {};
          this.globalData.bindingsReady = true;
          this.globalData.bindingsError = false;
          if (callback) callback(this.globalData.bindings);
        } else {
          if (callback) callback(null);
        }
      })
      .catch(() => {
        if (callback) callback(null);
      });
  },

  setRole(role) {
    this.globalData.currentRole = role;
    wx.setStorageSync('currentRole', role);
  },

  getRole() {
    if (this.globalData.currentRole && this.globalData.currentRole !== 'user') {
      return this.globalData.currentRole;
    }
    const saved = wx.getStorageSync('currentRole');
    if (saved && saved !== 'user') {
      this.globalData.currentRole = saved;
      return saved;
    }
    return this.globalData.currentRole || saved || 'user';
  },
});