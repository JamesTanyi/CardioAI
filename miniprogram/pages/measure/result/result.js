// pages/measure/result/result.js
const cloudService = require('../../../utils/cloudService.js');

Page({
  data: {
    result: null,
    userLines:     [], // ★ 改：不再是纯文本字符串，而是解析 **强调标记** 之后的结构化行数组
    riskLevel:     'low',
    riskLabel:     '',
    pulsePressure: 0,

    // ★ 新增：30天统计摘要 / 14天趋势图 / 14天测量记录——
    //   这三块之前这个页面完全没有历史数据来源，现在复用已有的
    //   cloudService.getHistory()（对应后端 history_views.py 的 /get_history 接口，
    //   history/month 页面本来就在用），不需要改动任何后端代码
    stats: { maxSbp: '--', minDbp: '--', abnormalRate: 0 },
    trendChartSource: [],
    trendCanvasWidth: 300,
    records: []
  },

  onLoad(options) {
    if (!options.data) return;
    try {
      const result = JSON.parse(decodeURIComponent(options.data));

      const reports = result.reports || {};
      const riskLabelMap = {
        none: '正常', low: '低风险', normal: '低风险',
        moderate: '中风险', high: '高风险', critical: '高风险'
      };

      this.setData({
        result,
        riskLevel:     result.riskLevel || 'low',
        riskLabel:     riskLabelMap[result.riskLevel] || '低风险',
        userLines:     this.parseEmphasisText(reports.user || '暂无数据'),
        pulsePressure: result.pulsePressure || 0
      });
    } catch (e) {
      console.error('解析结果失败:', e);
    }

    this.loadHistory();
  },

  // ★ 新增：解析后端用 **文字** 标记出的"需要强调"部分（类似 Markdown 加粗语法）——
  //   只做结构还原（识别标记、拆成 emphasis/普通 两种片段），不判断内容本身重不重要，
  //   哪句话该强调完全由后端 language.py 决定
  parseEmphasisText(text) {
    if (!text) return [];
    return text.split('\n').map((line) => {
      const segments = [];
      const regex = /\*\*(.+?)\*\*/g;
      let lastIndex = 0;
      let match;
      while ((match = regex.exec(line)) !== null) {
        if (match.index > lastIndex) {
          segments.push({ text: line.slice(lastIndex, match.index), emphasis: false });
        }
        segments.push({ text: match[1], emphasis: true });
        lastIndex = regex.lastIndex;
      }
      if (lastIndex < line.length) {
        segments.push({ text: line.slice(lastIndex), emphasis: false });
      }
      if (segments.length === 0) {
        segments.push({ text: '', emphasis: false });
      }
      return { segments };
    });
  },

  // ★ 新增：拉取近期历史记录，供统计摘要/趋势图/记录列表使用
  loadHistory() {
    const userId = wx.getStorageSync('app_user_id');
    if (!userId) return;

    cloudService.getHistory(userId, '', 200)
      .then((res) => {
        if (res && res.code === 0 && Array.isArray(res.data)) {
          this.processHistory(res.data);
        }
      })
      .catch((err) => {
        console.error('[result] 加载历史记录失败:', err);
      });
  },

  processHistory(history) {
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    const fourteenDaysAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000);
    const getDt = (item) => new Date(((item.datetime || item.date) || '').replace(/-/g, '/'));

    const last30 = history.filter((item) => getDt(item) >= thirtyDaysAgo);
    const last14 = history.filter((item) => getDt(item) >= fourteenDaysAgo);

    // ── 30天统计摘要：最高收缩压 / 最低舒张压 / 异常率 ──
    let maxSbp = -Infinity, minDbp = Infinity, abnormalCount = 0;
    last30.forEach((item) => {
      const sbp = parseInt(item.sbp);
      const dbp = parseInt(item.dbp);
      if (sbp > maxSbp) maxSbp = sbp;
      if (dbp < minDbp) minDbp = dbp;
      if (sbp >= 140 || dbp >= 90) abnormalCount++;
    });
    const count30 = last30.length;
    const stats = {
      maxSbp: count30 ? maxSbp : '--',
      minDbp: count30 ? minDbp : '--',
      abnormalRate: count30 ? Math.round((abnormalCount / count30) * 100) : 0
    };

    // ── 14天记录（含脉压差），列表最新在前 ──
    const records = last14
      .map((item) => {
        const sbp = parseInt(item.sbp);
        const dbp = parseInt(item.dbp);
        return {
          ...item,
          sbp, dbp,
          pp: sbp - dbp,
          abnormal: sbp >= 140 || dbp >= 90,
          dateSimple: (item.datetime || item.date || '').substring(0, 16)
        };
      })
      .sort((a, b) => getDt(b) - getDt(a));

    // 趋势图用同一份14天数据，时间正序
    const trendChartSource = [...records].reverse();

    const sysInfo = wx.getSystemInfoSync();
    // 画面完全展示、不横向滚动：canvas宽度固定为容器可用宽度
    const trendCanvasWidth = sysInfo.windowWidth - 24 * 2 - 16;

    this.setData({
      stats,
      records,
      trendChartSource,
      trendCanvasWidth
    });

    setTimeout(() => {
      this.drawTrendChart(trendChartSource, trendCanvasWidth);
    }, 200);
  },

  drawTrendChart(data, width) {
    const query = wx.createSelectorQuery();
    query.select('#trendChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0]) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = wx.getSystemInfoSync().pixelRatio;
        canvas.width = res[0].width * dpr;
        canvas.height = res[0].height * dpr;
        ctx.scale(dpr, dpr);
        this._drawTrend(ctx, data, res[0].width, res[0].height);
      });
  },

  // 与医生端趋势图用同一套绘制逻辑，保持三端视觉一致
  _drawTrend(ctx, data, width, height) {
    ctx.clearRect(0, 0, width, height);
    if (!data.length) return;

    const ratio = height / 300;

    // ★ 修复：纵轴范围不再写死 60~180——真实血压可能超过180或低于60，
    //   写死的范围会把超出的读数直接拍扁画在顶边/底边（比如200会画得跟180一样高），
    //   看起来失真、掩盖了真实的严重程度。改成按这14天的实际最高最低值往外扩一点动态计算。
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

    // ★ 修复：左边留白之前是固定值，数字变成3位数（如200/220）时第一位会被切掉——
    //   改成按刻度里最长数字的位数动态算，2位数和3位数都能完整显示。
    //   必须在算 stepX 之前就定好，不然折线的横向坐标会跟这里的留白对不上。
    const maxTickDigits = Math.max(...ticks.map((v) => String(v).length));
    const padding = {
      top: 22 * ratio,
      bottom: 56 * ratio,
      left: (10 + maxTickDigits * 9) * ratio,
      right: 20 * ratio
    };
    const drawHeight = height - padding.top - padding.bottom;
    const stepX = (width - padding.left - padding.right) / Math.max(1, data.length - 1);

    const getY = (val) => {
      const clamped = Math.max(minVal, Math.min(maxVal, val));
      return padding.top + drawHeight * (1 - (clamped - minVal) / valRange);
    };

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

    // ★ 纵轴刻度数字直接画在canvas上（不再用页面上单独固定的一列文字），
    //   这样数字永远跟当前的动态范围对齐，不会像固定文字那样和实际画的图错位
    ctx.fillStyle = '#999';
    ctx.font = `${Math.max(9, 10 * ratio)}px sans-serif`;
    ctx.textAlign = 'right';
    ticks.forEach((val) => {
      const y = getY(val);
      ctx.fillText(String(val), padding.left - 6, y + 3);
    });

    // 线宽/点大小按数据密度自适应，14天里点数可能是3个也可能是20多个
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

    // x轴日期刻度，数据点多时自动稀疏，避免日期文字挤在一起
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

  goBack() {
    wx.navigateBack();
  },

  goHome() {
    wx.reLaunch({ url: '/pages/index/index' });
  }
});