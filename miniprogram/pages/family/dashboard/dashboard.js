// pages/family/dashboard/dashboard.js - 家属仪表盘（APP式接口：启动即自动加载）
const cloudService = require('../../../utils/cloudService.js');
const app = getApp();

Page({
  data: {
    patientName: '',
    patientId: '',
    reportDate: '',
    // ★ 改：删除 statistics（平均血压/最高收缩压/异常率）整块——
    //   心血管健康场景下，平均值这类统计方式会掩盖危险信号（比如一次危险的
    //   血压骤升，会被其它正常读数平均掉，看起来"平均值正常"），
    //   项目理念要求前端不做任何计算/判断/建议，全部由后端给出，
    //   这里直接不展示任何统计数字，只展示原始轨迹（图表）和后端已有的判断结果。
    riskLevel: 'normal',
    riskLabel: '',
    hasAlert: false,
    // ★ 新增：系统操作状态提示（无权限/暂无数据/加载失败），和上面的健康风险判断是两码事，
    //   这类文案是应用层状态说明，不是医疗判断，前端可以自己生成
    hasStatusMsg: false,
    statusMsg: '',
    // 图表（如实展示原始数据点，不做平均/掩盖）
    canvasWidth: 300, scrollLeft: 0, chartSource: [],
    // 最近读数
    recentLogs: [],
    // 关注者视角分析（完全是后端原文，前端不加工）
    watcherAnalysis: [],
    analysisTime: '',
    // 绑定关系
    relationLabel: '家人',
    // ★ 改：留言未读提醒——从单纯的"有没有"改成具体几条，
    //   从 bindings.familyPatients[0].unreadFeedbackCount 同步
    unreadFeedbackCount: 0
  },

  /**
   * ★ onLoad：优先从 app.globalData 获取患者，否则从后端查询
   * URL 参数仅作为辅助（分享链接跳转时用）
   */
  onLoad(options) {
    // 1) URL 参数优先（从分享链接跳入时）
    const urlPatientId = options.patientId || '';
    const urlPatientName = options.patientName ? decodeURIComponent(options.patientName) : '';

    // 2) 次选：app 全局绑定数据
    const bindings = app.globalData.bindings;
    let patientId = urlPatientId;
    let patientName = urlPatientName;

    if (!patientId && bindings && bindings.hasFamilyBinding && bindings.familyPatients && bindings.familyPatients.length > 0) {
      // ★ 从全局数据自动选取第一个家属患者
      const p = bindings.familyPatients[0];
      patientId = p.patientId;
      patientName = p.patientName || p.patientId;
      this.setData({ unreadFeedbackCount: p.unreadFeedbackCount || 0 });
    }

    // 3) 最后：从 storage 兜底
    if (!patientId) {
      patientId = wx.getStorageSync('family_patient_id') || '';
      patientName = patientName || wx.getStorageSync('family_patient_name') || '';
    }

    if (patientId) {
      this.setData({ patientId, patientName: patientName || patientId });
      wx.setStorageSync('family_patient_id', patientId);
      if (patientName) wx.setStorageSync('family_patient_name', patientName);
    }
  },

  onShow() {
    // ★ v5 核心重构：先绑后查，永不 403
    this._preBindThenLoad();
    // ★ v6：启动自动轮询，每30秒静默刷新数据（实现持续跟踪）
    this._startAutoRefresh();
    this._maybeShowAddToDesktopTip();
  },

  /**
   * ★ 新增：引导家属把小程序添加到桌面/我的小程序，方便以后直接打开就能看到患者情况，
   *   不用每次都靠患者重新发邀请链接。和医生端 patient-list.js 是同一个做法，
   *   只在第一次进入家属仪表盘时提示一次，不重复打扰。
   *   注：微信平台不允许小程序代码直接触发"添加到桌面"，只能做文字引导。
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

  onHide() {
    this._stopAutoRefresh();
  },

  /** ★ v6：30秒自动轮询（静默刷新，不显示loading） */
  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._refreshTimer = setInterval(() => {
      if (this.data.patientId) {
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
    const { patientId } = this.data;
    const viewerId = wx.getStorageSync('app_user_id') || '';
    if (!patientId) return;
    cloudService.getHistory(patientId, viewerId, 90)
      .then((res) => {
        if (res.code === 0 && res.data && res.data.length > 0) {
          const records = res.data.map(item => ({
            ...item, datetime: item.datetime || item.date || item.created_at
          }));
          records.sort((a, b) => new Date(b.datetime) - new Date(a.datetime));
          this.processData(records);
        }
      })
      .catch(() => {});
  },

  _preBindThenLoad() {
    console.log("🔄 [Dashboard] 触发数据预载与状态刷新");

    // ★ 改：之前这里没有任何地方立即调用 loadPatientData()——
    //   唯一会真正拉取患者数据的路径，是 30 秒自动轮询定时器里的 _silentRefresh()，
    //   而 setInterval 要等满一个完整周期（30秒）才会第一次触发，
    //   这正是"每次打开都要空等二三十秒、甚至遇到一次失败要等一分钟"的真正原因，
    //   和服务器冷启动无关。现在改成页面一显示，只要已经知道 patientId，就立即主动加载一次。
    if (this.data.patientId) {
      this.loadPatientData();
    }

    // 🛡️ 核心修复：安全调用全局刷新，若 app 里没定义这个函数，则执行内部兜底刷新，绝不报错崩溃
    if (app && typeof app.refreshBindings === 'function') {
      app.refreshBindings((bindings) => {
        if (bindings && bindings.hasFamilyBinding && bindings.familyPatients && bindings.familyPatients.length > 0) {
          const p = bindings.familyPatients[0];
          // ★ 修复：hasUnreadFeedback 之前只在"第一次还没有 patientId"这个分支里才会更新，
          //   之后的自动轮询/下拉刷新都刷不到这个字段，小红点永远不会消失或重新出现。
          //   改成每次绑定数据刷新都同步一次，跟 patientId 是否已知无关。
          this.setData({ unreadFeedbackCount: p.unreadFeedbackCount || 0 });

          // 冷启动时如果一开始还没有 patientId（比如全局绑定数据还没就绪），
          // 这次拿到最新绑定关系后，补上首次加载
          if (!this.data.patientId) {
            this.setData({ patientId: p.patientId, patientName: p.patientName || p.patientId });
            wx.setStorageSync('family_patient_id', p.patientId);
            if (p.patientName) wx.setStorageSync('family_patient_name', p.patientName);
            this.loadPatientData();
          }
        }
      });
    } else {
      console.warn("⚠️ [Dashboard] 全局 app.js 未定义 refreshBindings 函数，已自动启用本地局部刷新兜底");

      // 💡 本地兜底刷新逻辑：直接从本地持久化缓存读取绑定身份，实现长期进入
      const currentRole = wx.getStorageSync('currentRole');
      const patientId = this.data.patientId || wx.getStorageSync('family_patient_id') || wx.getStorageSync('last_viewed_patient');

      // ★ 改：原来这里调用的 this.fetchPatientData 这个函数在本文件里根本不存在，
      //   是个死引用，永远不会执行。改成调用真正存在的 loadPatientData()
      if (patientId && !this.data.patientId) {
        this.setData({
          patientId: patientId,
          role: currentRole || this.data.role
        });
        this.loadPatientData();
      }
    }
  },

  onPullDownRefresh() {
    // 下拉刷新：先同步绑定状态，再加载数据
    app.refreshBindings((bindings) => {
      if (bindings && bindings.hasFamilyBinding && bindings.familyPatients && bindings.familyPatients.length > 0) {
        const p = bindings.familyPatients[0];
        this.setData({ unreadFeedbackCount: p.unreadFeedbackCount || 0 });
        if (!this.data.patientId) {
          this.setData({ patientId: p.patientId, patientName: p.patientName || p.patientId });
        }
      }
      this.loadPatientData(() => wx.stopPullDownRefresh());
    });
  },

  /**
   * 加载患者数据
   * ★ 注：原本还有一个 loadFamilyBinding() 兜底函数，调用已删除的 getFamilyPatient 接口，
   *   但这个函数从未被任何地方调用过（纯死代码），本次清理幽灵接口时一并删除。
   */
  loadPatientData(callback) {
    const { patientId } = this.data;
    const viewerId = wx.getStorageSync('app_user_id') || '';
    if (!patientId) return;

    const now = new Date();
    this.setData({
      reportDate: `${now.getFullYear()}/${now.getMonth()+1}/${now.getDate()} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`
    });

    wx.showLoading({ title: '加载数据...', mask: false });

    cloudService.getHistory(patientId, viewerId, 90)
      .then((res) => {
        wx.hideLoading();
        if (res.code === 0 && res.data && res.data.length > 0) {
          const records = res.data.map(item => ({
            ...item,
            datetime: item.datetime || item.date || item.created_at
          }));
          records.sort((a, b) => new Date(b.datetime) - new Date(a.datetime));
          this.processData(records);
        } else {
          if (res.error && res.error.includes('权限')) {
            this.setData({ hasStatusMsg: true, statusMsg: '暂无权限查看该家人的数据，请确认绑定关系' });
          } else {
            this.setData({ hasStatusMsg: true, statusMsg: `${this.data.patientName}暂未录入血压数据` });
          }
        }
        if (callback) callback();
      })
      .catch(() => {
        wx.hideLoading();
        this.setData({ hasStatusMsg: true, statusMsg: '数据加载失败，下拉刷新重试' });
        if (callback) callback();
      });
  },

  /**
   * 处理数据（仅展示层整理：不做任何计算/判断/建议——
   * 风险状态直接来自每条记录后端已经算好并存库的 risk_level 字段，
   * 图表如实展示每一个真实数据点，不做平均，避免掩盖危险信号）
   */
  processData(records) {
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);

    const validData = records.filter(item => {
      const d = new Date(((item.datetime || item.date) || '').replace(/-/g, '/'));
      return d >= thirtyDaysAgo;
    });

    const logs = validData.map(item => ({
      ...item,
      sbp: parseInt(item.sbp),
      dbp: parseInt(item.dbp),
      dateSimple: (item.datetime || item.date || '').substring(0, 16)
    }));

    // ★ 改：当前状态直接取最新一条记录后端算好的 risk_level，
    //   这里只是把分类代码"翻译"成中文短标签，不是重新判断
    const riskLabelMap = {
      none: '状态良好', normal: '状态良好', low: '状态良好',
      moderate: '需关注', high: '高危预警', critical: '高危预警'
    };
    const latest = logs[0];
    const riskLevel = (latest && latest.risk_level) || 'normal';
    const riskLabel = riskLabelMap[riskLevel] || '状态良好';
    const hasAlert = !['normal', 'none', 'low', undefined, null, ''].includes(riskLevel);

    // 关注者视角分析：完全是后端原文，前端不做任何分类/加工
    let watcherAnalysis = [];
    const latestAnalysis = records.find(item => item.analysis && item.analysis.watcher);
    if (latestAnalysis) {
      const text = latestAnalysis.analysis.watcher || '';
      watcherAnalysis = text.split('\n').filter(l => l.trim()).map(line => ({ content: line.trim() }));
      this.setData({ analysisTime: latestAnalysis.datetime || '' });
    } else {
      watcherAnalysis = [{ content: '暂无AI分析数据。建议家人定期测量血压，系统将自动生成报告。' }];
    }

    // 最近读数（最多10条，原始数值，不做统计）
    const recentLogs = logs.slice(0, 10);

    // ★ 修复：画布宽度改成固定等于容器宽度，不再按数据点数量撑宽/横向滚动——
    //   之前纵轴数字画在画布最左边，但默认滚动位置在最右边（显示最新数据），
    //   导致数字被滚出屏幕看不见。改成不滚动、30天数据整体压缩显示在一屏内，
    //   数字就一直在可见范围里（跟患者端/医生端趋势图是同一个思路）
    const chartSource = [...logs].reverse();
    const sysInfo = wx.getSystemInfoSync();
    const canvasWidth = sysInfo.windowWidth - 80;

    this.setData({
      riskLevel, riskLabel, hasAlert,
      recentLogs, watcherAnalysis,
      chartSource, canvasWidth, scrollLeft: 0
    });

    setTimeout(() => this.initChart(chartSource), 200);
  },

  initChart(data) {
    const query = wx.createSelectorQuery();
    query.select('#familyChart')
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

    // ★ 修复：纵轴范围不再写死 60~180——真实血压可能超过180或低于60，
    //   写死的范围会把超出的读数直接拍扁画在顶边/底边（比如200会画得跟180一样高），
    //   看起来失真、掩盖了真实的严重程度。改成按30天实际最高最低值往外扩一点动态计算。
    //   （跟患者端/医生端趋势图用的是同一套修复逻辑，保持三端一致）
    const allVals = [];
    data.forEach((item) => { allVals.push(item.sbp, item.dbp); });
    const rawMin = Math.min(...allVals);
    const rawMax = Math.max(...allVals);
    const minVal = Math.floor((rawMin - 10) / 10) * 10;
    const maxVal = Math.ceil((rawMax + 10) / 10) * 10;
    const valRange = Math.max(20, maxVal - minVal);

    // 纵轴刻度：按动态范围切成约5档整数刻度（10的倍数，好读）
    const rawStep = valRange / 5;
    const tickStep = Math.max(10, Math.round(rawStep / 10) * 10);
    const ticks = [];
    for (let v = minVal; v <= maxVal; v += tickStep) ticks.push(v);

    // ★ 修复：左边留白按刻度最长数字的位数动态算，避免3位数（如200/220）被切掉第一位。
    //   必须在算 stepX 之前定好，不然折线的横向坐标会跟这里的留白对不上。
    const maxTickDigits = Math.max(...ticks.map((v) => String(v).length));
    const padding = {
      top: 22 * ratio,
      bottom: 56 * ratio,
      left: (10 + maxTickDigits * 9) * ratio,
      right: 20 * ratio
    };
    const drawHeight = height - padding.top - padding.bottom;
    const stepX = (width - padding.left - padding.right) / Math.max(1, data.length - 1);
    const getY = (val) => padding.top + drawHeight * (1 - (Math.max(minVal, Math.min(maxVal, val)) - minVal) / valRange);

    // 线宽/点大小按数据密度自适应，30天数据点数可能是几个也可能是二三十个
    const dotRadius = data.length > 14 ? 2 : data.length > 8 ? 2.5 : 3;
    const lineWidth = data.length > 14 ? 1.5 : 2;

    ctx.clearRect(0, 0, width, height);
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';

    // 危险区背景（沿用原有的140~180这条已有的参考线，不新增判断规则）
    ctx.fillStyle = 'rgba(255,107,107,0.06)';
    ctx.fillRect(padding.left, getY(Math.min(180, maxVal)), width - padding.left, getY(140) - getY(Math.min(180, maxVal)));

    ctx.strokeStyle = '#F5F5F5'; ctx.lineWidth = 1;
    ticks.forEach((val) => {
      const y = getY(val);
      ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width, y); ctx.stroke();
    });

    // ★ 纵轴刻度数字直接画在canvas上（原来是页面上单独固定的一列文字，跟动态范围对不上会错位）
    ctx.fillStyle = '#999';
    ctx.font = `${Math.max(9, 10 * ratio)}px sans-serif`;
    ctx.textAlign = 'right';
    ticks.forEach((val) => {
      const y = getY(val);
      ctx.fillText(String(val), padding.left - 6, y + 3);
    });

    const drawLine = (key, color) => {
      ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = lineWidth;
      data.forEach((item, index) => {
        const x = padding.left + index * stepX, y = getY(item[key]);
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.lineWidth = Math.max(1, lineWidth - 0.5);
      data.forEach((item, index) => {
        const x = padding.left + index * stepX, y = getY(item[key]);
        ctx.beginPath(); ctx.arc(x, y, dotRadius, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      });
    };
    drawLine('sbp', '#FF6B6B');
    drawLine('dbp', '#4A90E2');

    // ★ 新增：横轴日期刻度——之前这张图完全没有时间轴，只能靠位置大致猜时间
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

  // ★ 新增：跳转到三方留言板，带上当前绑定患者的ID/姓名
  goToFeedback() {
    const { patientId, patientName } = this.data;
    if (!patientId) {
      wx.showToast({ title: '尚未绑定患者', icon: 'none' });
      return;
    }
    const nameParam = patientName ? `&patientName=${encodeURIComponent(patientName)}` : '';
    wx.navigateTo({ url: `/feedback/feedback?patientId=${encodeURIComponent(patientId)}${nameParam}` });
  },

  /** 返回首页 */
  goHome() {
    wx.navigateBack({
      fail: () => wx.redirectTo({ url: '/pages/index/index' })
    });
  }
});