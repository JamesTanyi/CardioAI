// feedback/feedback.js
// ★ 重写说明：反馈从"手动输入接收者ID的私信"改成"以患者为中心的透明共享留言板"——
//   医生、家属、患者本人共享同一条留言线，谁都能看到全部内容。
//   原来弹窗里的"接收者ID"输入框和"您的角色"单选去掉了（不再需要，也不该让用户
//   自己选角色，容易选错/冒充身份）；留言线由 patientId 自动解析决定，
//   发言身份改成针对具体患者实时查真实绑定关系决定(get_relation_role)，
//   不再依赖本地缓存的 currentRole——同一个微信账号可能同时是A的家属、
//   又是B的医生，全局角色字段没法正确反映"我对这一个具体患者是什么关系"。
//   顶部导航、状态展示、弹窗这套 UI 结构保留原样，只改数据来源和字段。
//
// ★ 再次重写：多医生留言隔离上线——一个患者如果同时绑定了多个医生，
//   留言线按 (patientId, doctorId) 拆分，医生之间互相看不到对方那条线；
//   患者/家属对该患者名下任意一条医生线都能看/发。
//
// ★ 第三次重写：加入"基础线"——患者+家属专属的对话，永远存在，不挂任何医生，
//   医生完全无法访问（不是权限受限，是压根看不见这条线存在）。之前"必须先
//   绑医生才能开始留言"的设计已经改掉——患者/家属能不能绑到医生不受自己控制，
//   留言不该被这件事卡住。数据库层面用空字符串 '' 作为 doctor_id 表示基础线
//   （不用 NULL，因为已读记录表的唯一性判断在多数数据库里对 NULL 会失效）。
//   - 医生角色：固定用自己的 id 作为 doctorId，看不到、也切不到基础线
//   - 患者/家属角色：默认打开基础线（doctorId=''），如果绑了医生，
//     可以点"当前对话：xxx ▾"切换到某位医生的诊疗线，基础线始终是切换列表里
//     的第一项，不需要绑够医生才能用
//
//   同时新增"管理模式"（仅患者可见）：右上角🗑图标进入多选删除，
//   底部出现"删除所选"+"清空全部"按钮。家属/医生看不到这个入口
//   （后端 delete_feedback/clear_feedback 也只认患者本人，其他身份调用会被403）。
const cloudService = require('../utils/cloudService.js');

Page({
  data: {
    patientId: '',
    patientName: '',
    myRole: 'patient', // patient / family / doctor —— 决定发言时的身份标签，不再由用户手动选
    feedbacks: [],
    loading: true,
    requesting: false,
    isEmpty: false,
    // ── 留言线：基础线(doctorId='') + 各医生诊疗线 ──
    doctors: [],           // 患者/家属角色下，该患者绑定的医生列表(可以是空数组，不再阻塞)
    doctorsLoading: false,
    doctorId: '',          // 当前查看的线：''=基础线(患者+家属专属)，非空=某位医生的诊疗线
    lineResolved: false,   // 是否已经确定好该看哪条线——doctorId==''本身是合法状态(基础线)，
                            // 用这个字段区分"还没算出来"和"算出来就是基础线"，避免误判成未初始化
    currentLineLabel: '👨‍👩‍👧 家庭对话', // 当前线的展示文案
    showDoctorPicker: false,
    // ── 管理模式(仅患者)：多选删除/清空 ──
    manageMode: false,
    selectedIds: [],
    deleting: false,
    clearing: false,
    // 发送反馈相关
    showSendModal: false,
    sendContent: '',
    sending: false,
    // navigationStyle 改成 custom 之后，系统不再自动预留导航栏空间，
    // 需要自己算出状态栏高度 + 右上角胶囊按钮(···和圆点)的位置，
    // 让自定义头部避开它，不然会跟胶囊按钮挤在一起
    headerTotalHeight: 0, // 状态栏 + 导航栏内容 的总高度(px)，用于 .header 的高度
    headerContentCenterY: 0, // 导航内容区(不含状态栏)的垂直中心位置(px)，绝对定位子元素靠它对齐
    headerRightGap: 0,    // 右侧要让出的宽度(px)，避免跟胶囊按钮重叠
    headerTitleRight: 0
  },

  onLoad(options) {
    // patientId 解析：URL参数（从别的页面带着患者ID跳转进来）→ 默认自己
    // ★ 改：原来这里没有 URL 参数时会看本地缓存的 currentRole 猜"该打开谁的
    //   看板"——如果 currentRole 是 family 就去读 family_patient_id 兜底。
    //   这个分支不可靠：currentRole 这个全局字段本身就有"账号身兼多重身份/
    //   冻结在最早注册角色"这类已知问题(参考 get_relation_role 那次修复)，
    //   一旦猜错，family_patient_id 缓存里读到空字符串，patientId 就成了空的，
    //   后续 _resolveMyRoleAndLoad() 直接短路返回，连请求都不会发出去，
    //   页面表现为"打开是空的、没有任何网络请求、没有任何日志"。
    //   而这个入口(more.wxml的"健康反馈")本来就只有患者账号能进——家属/医生
    //   走的是完全不同的入口，且必然会带着明确的 patientId 跳转过来，所以
    //   没有 URL 参数时，不需要再猜，直接默认打开"我自己"的看板即可。
    const urlPatientId = options.patientId || '';
    const urlPatientName = options.patientName ? decodeURIComponent(options.patientName) : '';
    const myUserId = wx.getStorageSync('app_user_id') || '';

    const patientId = urlPatientId || myUserId;
    const patientName = urlPatientName;

    // 头部先按默认角色(patient)算一版尺寸，避免首屏空白；等真实角色查出来后
    // _resolveMyRoleAndLoad() 会用查到的真实角色重新算一次并纠正
    this._setupCustomHeader('patient');

    this.setData({ patientId, patientName });
  },

  // 算出自定义导航栏要避开胶囊按钮所需的尺寸
  _setupCustomHeader(myRole) {
    try {
      const sys = wx.getSystemInfoSync();
      const menuButton = wx.getMenuButtonBoundingClientRect();
      // 导航栏内容高度：胶囊按钮跟状态栏之间的间距，上下各留一份，加上胶囊按钮本身的高度
      const navBarHeight = (menuButton.top - sys.statusBarHeight) * 2 + menuButton.height;
      // 右侧要让出的宽度：从屏幕右边到胶囊按钮左边缘，再留一点间距
      const rightGap = sys.windowWidth - menuButton.left + 12;

      // 标题右边界要卡在"图标组左边缘再往左一点"，而不是屏幕正中央，
      // 这样标题实际居中的是"返回按钮和图标组之间"这段空间，不会被挡。
      // ★ 改：图标数量按角色而变——患者多一个"管理"图标(🗑)，
      //   宽度也要跟着变，不然标题右边界会算错，跟第三个图标挤在一起
      const rpxToPx = sys.windowWidth / 750;
      const iconCount = myRole === 'patient' ? 3 : 2;
      const iconGroupWidthPx = (iconCount * 60 + (iconCount - 1) * 20 + 12) * rpxToPx;
      const titleRightBoundary = rightGap + iconGroupWidthPx;

      this.setData({
        headerTotalHeight: sys.statusBarHeight + navBarHeight,
        // 导航内容区(排除状态栏那一截)的垂直中心，绝对定位的返回按钮/标题/图标组
        // 都靠这个值 + transform:translateY(-50%) 对齐，保证跟胶囊按钮上下居中对齐
        headerContentCenterY: sys.statusBarHeight + navBarHeight / 2,
        headerRightGap: rightGap,
        headerTitleRight: titleRightBoundary
      });
    } catch (e) {
      // 极端情况下取不到胶囊按钮信息，退回一个常见机型下大致够用的默认值，不阻塞页面
      this.setData({
        headerTotalHeight: 88,
        headerContentCenterY: 66,
        headerRightGap: 100,
        headerTitleRight: 170
      });
    }
  },

  onShow() {
    // ★ 改：原来直接 loadFeedbacks()，后来改成先确定 doctorId 再加载；
    //   现在再往前加一步——先用 get_relation_role 查清楚"我对这个 patientId
    //   到底是什么角色"，不再信任本地缓存的 currentRole。三步都放进
    //   同一次 onShow，保证每次显示都是最新、最准确的角色+留言线+留言内容。
    this._resolveMyRoleAndLoad();
  },

  // 第一步：用真实绑定关系查"我"对这个patientId到底是什么角色
  _resolveMyRoleAndLoad() {
    const { patientId } = this.data;
    const myUserId = wx.getStorageSync('app_user_id') || '';

    if (!patientId || !myUserId) {
      this.setData({ myRole: 'patient', loading: false, isEmpty: true });
      return;
    }

    cloudService.getRelationRole(patientId, myUserId)
      .then((res) => {
        // role 可能是 'none'(比如绑定关系已经被解除、链接过期)，退回 patient 兜底，
        // 后续 _resolveDoctorContextAndLoad 会因为查不到有效数据自然显示空态，不会崩溃
        const role = (res && res.code === 0 && res.data && res.data.role) || 'patient';
        const resolvedRole = role === 'none' ? 'patient' : role;
        this._setupCustomHeader(resolvedRole);
        this.setData({ myRole: resolvedRole });
        this._resolveDoctorContextAndLoad();
      })
      .catch((err) => {
        // 网络异常时退回 patient 兜底，不阻塞页面(跟原来的容错思路一致)
        this._setupCustomHeader('patient');
        this.setData({ myRole: 'patient' });
        this._resolveDoctorContextAndLoad();
      });
  },

  // 第二步：确定当前要看哪条线(doctorId，''代表基础线)，确定后再去加载留言
  _resolveDoctorContextAndLoad() {
    const { patientId, myRole } = this.data;
    const myUserId = wx.getStorageSync('app_user_id') || '';

    if (!patientId) {
      this.setData({ loading: false, isEmpty: true });
      return;
    }

    if (myRole === 'doctor') {
      // 医生只能看/发自己那条诊疗线，doctorId 固定是自己，看不到、也切不到基础线
      this.setData({
        doctorId: myUserId, currentLineLabel: '', doctors: [], lineResolved: true
      });
      this.loadFeedbacks();
      return;
    }

    // 患者/家属：查这个患者绑定了哪些医生，用来填充切换列表；
    // 绑0个医生完全没关系，基础线始终可用，不再是"必须绑医生才能留言"
    this.setData({ doctorsLoading: true });
    cloudService.getPatientDoctors(patientId, myUserId)
      .then((res) => {
        this.setData({ doctorsLoading: false });
        const doctors = (res && res.code === 0) ? (res.data || []) : [];
        if (res && res.code !== 0) {
          // 查医生列表失败不影响基础线正常使用，只是切换列表暂时是空的，静默降级
          console.warn('[feedback] getPatientDoctors failed:', res.msg || res.error);
        }
        // 如果当前已选的线还有效(基础线永远有效；医生线要确认这位医生还在列表里)，保留选择；
        // 否则回到基础线——不再有"必须默认选中某个医生"这回事
        const currentDoctorId = this.data.lineResolved ? this.data.doctorId : '';
        const stillValidDoctorLine = currentDoctorId && doctors.some(d => d.doctorId === currentDoctorId);
        const nextDoctorId = stillValidDoctorLine ? currentDoctorId : '';
        const picked = stillValidDoctorLine ? doctors.find(d => d.doctorId === nextDoctorId) : null;

        this.setData({
          doctors,
          doctorId: nextDoctorId,
          currentLineLabel: picked ? `👨‍⚕️ ${picked.doctorName}` : '👨‍👩‍👧 家庭对话',
          lineResolved: true
        });
        this.loadFeedbacks();
      })
      .catch(() => {
        this.setData({ doctorsLoading: false, loading: false, isEmpty: true });
        wx.showToast({ title: '网络异常，请检查网络', icon: 'none' });
      });
  },

  loadFeedbacks() {
    const { patientId, doctorId, lineResolved } = this.data;
    const viewerId = wx.getStorageSync('app_user_id') || '';

    if (!patientId || !lineResolved) {
      this.setData({ loading: false, isEmpty: true });
      return;
    }

    // 请求锁，防止重复请求
    if (this.data.requesting) return;

    this.setData({ loading: true, requesting: true });

    cloudService.getFeedback(patientId, viewerId, doctorId)
      .then((res) => {
        this.setData({ loading: false, requesting: false });
        if (res.code === 0) {
          // 成功看到这条留言线之后，标记"我"已经看过了(各端、各条线独立记录，
          // 不影响其他人/其他线的未读状态)，患者列表页的未读提醒靠这个消失
          if (viewerId) {
            cloudService.markFeedbackRead({ viewerId, patientId, doctorId }).catch(() => {});
          }
          // ★ 改：roleLabel 从纯角色文案("👨‍👩‍👧 家属")改成"角色emoji + 真实姓名"，
          //   否则患者绑了不止一位家属/医生时，留言列表里全是"👨‍👩‍👧 家属"，
          //   根本分不清具体是哪一位说的。sender_name 由后端 get_feedback 新增的
          //   JOIN users 查出来；查不到(比如账号异常)时退回角色文案兜底，不留空白。
          const roleIconMap = { doctor: '👨‍⚕️', family: '👨‍👩‍👧', patient: '🙋' };
          const roleFallbackMap = { doctor: '医生', family: '家属', patient: '患者本人' };
          const feedbacks = (res.data || []).map((item) => {
            const icon = roleIconMap[item.from_role] || '';
            const displayName = item.sender_name || roleFallbackMap[item.from_role] || item.from_role;
            return {
              ...item,
              roleLabel: `${icon} ${displayName}`.trim(),
              roleClass: `role-${item.from_role}`,
              isMine:    item.from_id === viewerId,
              timeStr:   this.formatTime(item.created_at)
            };
          });
          this.setData({ feedbacks, isEmpty: feedbacks.length === 0 });
        } else {
          wx.showToast({ title: res.error || '加载失败', icon: 'none' });
          this.setData({ isEmpty: true });
        }
      })
      .catch(() => {
        this.setData({ loading: false, requesting: false, isEmpty: true });
        wx.showToast({ title: '网络异常，请检查网络', icon: 'none' });
      });
  },

  formatTime(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr.replace(/-/g, '/'));
      const now  = new Date();
      const diff = now - date;
      const mins  = Math.floor(diff / 60000);
      const hours = Math.floor(diff / 3600000);
      const days  = Math.floor(diff / 86400000);
      if (mins  < 1)  return '刚刚';
      if (mins  < 60) return `${mins}分钟前`;
      if (hours < 24) return `${hours}小时前`;
      if (days  < 7)  return `${days}天前`;
      return `${date.getMonth()+1}/${date.getDate()}`;
    } catch (e) {
      return '';
    }
  },

  onGoBack() {
    wx.navigateBack();
  },

  // ========== 留言线选择器(患者/家属可用；基础线永远是第一项，绑了医生才多出可切换的诊疗线) ==========

  showDoctorPickerModal() {
    if (this.data.myRole === 'doctor') return; // 医生看不到、切不到基础线/别的医生线
    if (this.data.doctors.length === 0) return; // 只有基础线，没有别的可切
    this.setData({ showDoctorPicker: true });
  },

  closeDoctorPicker() {
    this.setData({ showDoctorPicker: false });
  },

  // 切到基础线(患者+家属专属)
  selectBaseLine() {
    if (this.data.doctorId === '') {
      this.setData({ showDoctorPicker: false });
      return;
    }
    this.setData({
      doctorId: '',
      currentLineLabel: '👨‍👩‍👧 家庭对话',
      showDoctorPicker: false,
      manageMode: false,
      selectedIds: []
    });
    this.loadFeedbacks();
  },

  // 切到某位医生的诊疗线
  selectDoctor(e) {
    const doctorId = e.currentTarget.dataset.id;
    const doctor = this.data.doctors.find(d => d.doctorId === doctorId);
    if (!doctor || doctorId === this.data.doctorId) {
      this.setData({ showDoctorPicker: false });
      return;
    }
    this.setData({
      doctorId: doctor.doctorId,
      currentLineLabel: `👨‍⚕️ ${doctor.doctorName}`,
      showDoctorPicker: false,
      manageMode: false,
      selectedIds: []
    });
    this.loadFeedbacks();
  },

  // ========== 管理模式：多选删除 / 清空全部(仅患者本人可见) ==========

  toggleManageMode() {
    if (this.data.myRole !== 'patient') return;
    this.setData({
      manageMode: !this.data.manageMode,
      selectedIds: []
    });
  },

  toggleSelectFeedback(e) {
    const id = e.currentTarget.dataset.id;
    const selectedIds = this.data.selectedIds.slice();
    const idx = selectedIds.indexOf(id);
    if (idx >= 0) {
      selectedIds.splice(idx, 1);
    } else {
      selectedIds.push(id);
    }
    this.setData({ selectedIds });
  },

  deleteSelected() {
    const { selectedIds, patientId } = this.data;
    if (selectedIds.length === 0) {
      wx.showToast({ title: '请先选择要删除的留言', icon: 'none' });
      return;
    }
    const viewerId = wx.getStorageSync('app_user_id') || '';

    wx.showModal({
      title: '删除留言',
      content: `确定删除选中的 ${selectedIds.length} 条留言吗？此操作不可恢复。`,
      confirmColor: '#e74c3c',
      success: (r) => {
        if (!r.confirm) return;
        this.setData({ deleting: true });
        cloudService.deleteFeedback({ viewerId, patientId, feedbackIds: selectedIds })
          .then((res) => {
            this.setData({ deleting: false });
            if (res.code === 0) {
              wx.showToast({ title: res.message || '已删除', icon: 'success' });
              this.setData({ manageMode: false, selectedIds: [] });
              this.loadFeedbacks();
            } else {
              wx.showToast({ title: res.error || '删除失败', icon: 'none' });
            }
          })
          .catch(() => {
            this.setData({ deleting: false });
            wx.showToast({ title: '网络错误', icon: 'none' });
          });
      }
    });
  },

  // ★ 注意：后端 clear_feedback 没有 doctorId 参数，清空的是该患者名下
  //   【全部医生留言线】的全部留言，不是只清空当前正在看的这一条线，
  //   所以确认弹窗文案要把这一点说清楚，避免患者以为只清了当前线
  clearAll() {
    const { patientId } = this.data;
    const viewerId = wx.getStorageSync('app_user_id') || '';

    wx.showModal({
      title: '清空全部留言',
      content: '将清空你名下【所有医生】的全部留言记录，此操作不可恢复，确定继续吗？',
      confirmColor: '#e74c3c',
      success: (r) => {
        if (!r.confirm) return;
        this.setData({ clearing: true });
        cloudService.clearFeedback({ viewerId, patientId })
          .then((res) => {
            this.setData({ clearing: false });
            if (res.code === 0) {
              wx.showToast({ title: res.message || '已清空', icon: 'success' });
              this.setData({ manageMode: false, selectedIds: [] });
              this.loadFeedbacks();
            } else {
              wx.showToast({ title: res.error || '清空失败', icon: 'none' });
            }
          })
          .catch(() => {
            this.setData({ clearing: false });
            wx.showToast({ title: '网络错误', icon: 'none' });
          });
      }
    });
  },

  // ========== 发送反馈相关 ==========

  showSendModal() {
    if (!this.data.patientId) {
      wx.showToast({ title: '未确定患者，无法发送', icon: 'none' });
      return;
    }
    if (!this.data.lineResolved) {
      wx.showToast({ title: '正在确定留言线，请稍候', icon: 'none' });
      return;
    }
    this.setData({
      showSendModal: true,
      sendContent: '',
      sending: false
    });
  },

  closeSendModal() {
    this.setData({ showSendModal: false });
  },

  // 给弹窗内容区的 catchtap 用——WXML 里 catchtap="" (空字符串) 不一定能
  // 可靠拦截事件冒泡，改成绑定一个真正存在的空函数，确保点浮窗内部(包括输入框)
  // 不会冒泡触发外层遮罩的 closeSendModal，导致浮窗被意外关掉
  noop() {},

  onInputContent(e) {
    this.setData({ sendContent: e.detail.value });
  },

  sendFeedback() {
    const { patientId, doctorId, sendContent, myRole, lineResolved } = this.data;
    const content = sendContent.trim();

    if (!content) {
      wx.showToast({ title: '请输入留言内容', icon: 'none' });
      return;
    }
    if (content.length > 500) {
      wx.showToast({ title: '内容不能超过500字', icon: 'none' });
      return;
    }
    if (!lineResolved) {
      wx.showToast({ title: '正在确定留言线，请稍候', icon: 'none' });
      return;
    }

    const fromId = wx.getStorageSync('app_user_id');
    this.setData({ sending: true });

    cloudService.sendFeedback({
      fromId,
      fromRole: myRole,
      patientId,
      doctorId,
      content
    })
      .then((res) => {
        this.setData({ sending: false });
        if (res.code === 0) {
          wx.showToast({ title: '发送成功', icon: 'success' });
          // 发送成功但列表读不到最新数据的真正原因——loadFeedbacks() 里有个
          // "请求锁"(this.data.requesting)防止手抖连点刷新导致重复请求，
          // 但如果页面刚打开时 onShow() 触发的那次自动加载还没真正结束，
          // requesting 还是 true，这里紧跟着调用 loadFeedbacks() 会被这把锁
          // 直接拦下、静默跳过，请求根本没发出去。这里强制解锁，不依赖它"自然"重置。
          this.setData({ showSendModal: false, requesting: false });
          this.loadFeedbacks();
        } else {
          wx.showToast({ title: res.error || '发送失败', icon: 'none' });
        }
      })
      .catch(() => {
        this.setData({ sending: false });
        wx.showToast({ title: '网络错误', icon: 'none' });
      });
  }
});
