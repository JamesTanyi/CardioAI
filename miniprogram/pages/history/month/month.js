// pages/history/month/month.js
// ★ 重写说明：原来这里用 calcMedian()/getDeviationInfo() 在前端本地重新计算
//   "个人稳态中位值"和"偏离程度"——这是本项目"前端不做临床判断，一切分析交给
//   后端引擎"这条核心原则明确要禁止的做法。而且这套本地计算只是拿全部历史数据
//   算一个全局中位数（单点、不分阶段），跟后端 steady_state.py（阶段稳态：多窗口+
//   变点检测分段）和 risk_level.py（长期个体化稳态带：一个区间、随基线动态调整）
//   已经做好的判断完全是两回事，两边逻辑不一致，会出现相近的读数却标注不同等级
//   这种让人看不懂的情况。
//   现在改成：偏离等级直接读每条记录后端已经算好、存库的 risk_level 字段，
//   前端只负责把这个字段翻译成中文文案+展示样式，不再重新判断。
//   同时把图表和列表的数据窗口统一成近90天（原来图表被写死30天、列表却是全量，
//   两边范围对不上，这正是"上传了110条历史记录但趋势图反映不出来"的根本原因）。
const cloudService = require('../../../utils/cloudService.js');

const CHART_H = 300;
const PAD_TOP = 16;
const PAD_BTM = 36;
const PAD_L   = 10;
const PAD_R   = 16;
const Y_MAX   = 180;
const Y_MIN   = 60;
const Y_TICKS = [180, 160, 140, 120, 100, 80, 60];
const DRAW_H  = CHART_H - PAD_TOP - PAD_BTM;
const WINDOW_DAYS = 60; // ★ 改：90天改成60天；60天之外的历史不再直接隐藏，改成文字概括(见 _summarizeOlder)

function getY(val) {
  const v = Math.max(Y_MIN, Math.min(Y_MAX, val));
  return PAD_TOP + DRAW_H * (1 - (v - Y_MIN) / (Y_MAX - Y_MIN));
}

// ★ 改：不再自己算"稳态"和"偏离程度"，只是把后端 risk_level 字段翻译成中文标签+样式类——
//   翻译对照关系摆在这里没问题，但"这次读数到底算不算偏离"这个判断本身完全是
//   后端 risk_level.py 算出来存进数据库的，前端不参与判断。
const RISK_LABEL_MAP = {
  low:           { text: '稳态内',   cls: 'stable' },
  none:          { text: '稳态内',   cls: 'stable' },
  moderate:      { text: '轻度偏离', cls: 'mild' },
  moderate_high: { text: '明显偏离', cls: 'moderate' },
  high:          { text: '显著偏离', cls: 'significant' },
  critical:      { text: '高危预警', cls: 'critical' }
};

function getRiskDisplay(riskLevel) {
  return RISK_LABEL_MAP[riskLevel] || { text: '建立稳态中', cls: 'unknown' };
}

// ★ 说明：这个中位数函数只用在一处——_summarizeOlder() 里对"60天前 vs 近期"
//   做一个纯算术的数值对比，描述"更早的中位数比现在高/低多少"，是描述性的对比，
//   不用来给任何一条记录分类"算不算偏离"（那个判断完全由后端 risk_level 给出）。
function calcMedian(arr) {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

Page({
  data: {
    viewingUserId:  '',
    history:        [],
    chartSource:    [],
    canvasWidth:    300,
    distStable:     0,
    distMild:       0,
    distModerate:   0,
    distSignificant: 0,
    olderSummary:   null
  },

  onLoad(options) {
    // 优先从页面参数获取 userId（从家属页面跳转过来时）
    if (options && options.userId) {
      this.setData({ viewingUserId: options.userId });
      // 同时存入缓存，供 onShow 使用
      wx.setStorageSync('viewing_patient_id', options.userId);
    }
  },

  onShow() {
    this.loadHistory();
  },

  loadHistory() {
    // 优先使用页面参数或缓存中的 viewing_patient_id（家属查看）
    const viewingUserId = wx.getStorageSync('viewing_patient_id');
    const userId = viewingUserId || wx.getStorageSync('app_user_id');

    if (!userId) { this.renderHistory([]); return; }

    wx.showLoading({ title: '加载中...', mask: false });

    // 先读取本地缓存，保证页面立即有内容
    const localHistory = wx.getStorageSync('measure_history') || [];

    cloudService.getHistory(userId, '', 1000)
      .then((res) => {
        wx.hideLoading();
        if (res.code === 0 && res.data && Array.isArray(res.data) && res.data.length > 0) {
          const serverRecords = res.data.map(item => ({
            ...item,
            datetime: item.datetime || item.date || item.created_at
          }));
          const merged = this.mergeAndDeduplicate(serverRecords, localHistory);
          merged.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || b.date));
          if (!viewingUserId) {
            wx.setStorageSync('measure_history', merged);
          }
          this.renderHistory(merged);
        } else {
          this.renderHistory(localHistory);
        }
      })
      .catch(() => {
        wx.hideLoading();
        this.renderHistory(localHistory);
      });
  },

  // 合并并去重数据
  mergeAndDeduplicate(serverData, localData) {
    const map = new Map();

    // 先放入后端数据
    serverData.forEach(item => {
      const key = item.datetime || item.date || item.created_at;
      if (key) map.set(key, item);
    });

    // 再放入本地数据（不覆盖已有的）
    localData.forEach(item => {
      const key = item.datetime || item.date || item.created_at;
      if (key && !map.has(key)) {
        map.set(key, item);
      }
    });

    return Array.from(map.values());
  },

  fallbackToLocal() {
    const history = wx.getStorageSync('measure_history') || [];
    this.renderHistory(history);
  },

  // ★ 改：列表和图表现在用同一个"近60天"窗口，不再是"列表全量、图表30天"这种范围不一致；
  //   60天之外的历史不再直接消失——挪去 _summarizeOlder() 生成一段文字概括，
  //   保留"看得到"这件事，只是不再逐条画进图/列表里
  renderHistory(history) {
    const now = new Date();
    const windowStart = new Date(now - WINDOW_DAYS * 86400000);

    const windowed = [];
    const older = [];
    history.forEach(item => {
      const d = new Date(((item.datetime || item.date) || '').replace(/-/g, '/'));
      (d >= windowStart ? windowed : older).push(item);
    });

    // ★ 改：不再本地计算中位数/偏离度，直接读每条记录后端存好的 risk_level
    const listData = windowed.map(item => {
      const sbp = parseInt(item.sbp) || 0;
      const dbp = parseInt(item.dbp) || 0;
      const pp  = sbp - dbp;
      const risk = getRiskDisplay(item.risk_level);
      return {
        ...item, sbp, dbp, pp,
        hr:            parseInt(item.hr) || 75,
        dateShort:     this.formatDate(item.datetime || item.date),
        deviationLevel: risk.cls,
        deviationText:  risk.text
      };
    });

    // 图表数据（近60天，时间正序，跟列表是同一份数据源、同一个窗口）
    const chartSource = [...listData].reverse();

    // 分布统计：数一遍后端已经给的 risk_level 落在哪个档，纯计数汇总，不涉及新判断
    // （critical 和 significant 都算"显著偏离"这一档，避免顶部统计要新增第5个格子）
    let stable = 0, mild = 0, moderate = 0, significant = 0;
    listData.forEach(item => {
      if      (item.deviationLevel === 'stable')      stable++;
      else if (item.deviationLevel === 'mild')        mild++;
      else if (item.deviationLevel === 'moderate')    moderate++;
      else if (item.deviationLevel === 'significant' || item.deviationLevel === 'critical') significant++;
      else                                            stable++; // unknown(数据不足阶段) 归入稳态内展示
    });
    const cnt = listData.length;
    const pct = v => cnt ? Math.round(v / cnt * 100) : 0;

    const sysInfo = wx.getSystemInfoSync();
    // ★ 修复：canvas 宽度固定为容器宽度，不再按数据点数量撑宽——之前画布比屏幕宽很多，
    //   需要放在 scroll-view 里横向滑动才能看完；但小程序里 <canvas> 是原生组件，
    //   会抢占触摸事件，导致外层 scroll-view 经常滑不动（既滑不了手势，代码设的
    //   自动滚动位置也不生效），数据一多这个坑必现。改成不需要滑动，
    //   60天窗口内不管有多少条记录，全部压缩显示在一屏内，跟医生端/患者端/
    //   家属端趋势图是同一套思路。
    const canvasWidth = sysInfo.windowWidth - 48 - 16;

    // ★ 新增：60天之外的历史记录，概括成一段文字（不再直接隐藏）
    const olderSummary = this._summarizeOlder(older, listData);

    this.setData({
      history:         listData,
      chartSource:     chartSource,
      canvasWidth:     canvasWidth,
      distStable:      pct(stable),
      distMild:        pct(mild),
      distModerate:    pct(moderate),
      distSignificant: pct(significant),
      olderSummary:    olderSummary
    });

    setTimeout(() => {
      this.drawYAxis();
      this.drawTrendChart(chartSource, canvasWidth);
    }, 200);
  },

  /**
   * ★ 新增：60天窗口之外的历史记录，概括成一段文字——不再让批量上传的历史数据
   * 因为超出可视窗口就彻底"看不见"，同时不需要把几百条老数据硬塞进图表画布。
   * 这里做两件事，都是描述性的统计/算术，不涉及重新判断"算不算偏离"：
   *  1) 百分比分布——数一遍这段时间里每条记录后端 risk_level 落在哪个档，
   *     跟可视区间那四个百分比方块是同一类操作。
   *  2) 中位数对比——纯算术比较"更早的收缩压中位数比近期高/低多少"，
   *     只是描述数值差异和方向，不对这个差异做临床解读。
   */
  _summarizeOlder(olderRaw, recentListData) {
    if (!olderRaw || !olderRaw.length) return null;

    const olderData = olderRaw.map(item => {
      const sbp = parseInt(item.sbp) || 0;
      const risk = getRiskDisplay(item.risk_level);
      return { sbp, deviationLevel: risk.cls };
    });

    let stable = 0, mild = 0, moderate = 0, significant = 0;
    olderData.forEach(item => {
      if      (item.deviationLevel === 'stable')      stable++;
      else if (item.deviationLevel === 'mild')        mild++;
      else if (item.deviationLevel === 'moderate')    moderate++;
      else if (item.deviationLevel === 'significant' || item.deviationLevel === 'critical') significant++;
      else                                            stable++;
    });
    const cnt = olderData.length;
    const pct = v => cnt ? Math.round(v / cnt * 100) : 0;

    const olderMedianSbp  = calcMedian(olderData.map(i => i.sbp));
    const recentMedianSbp = calcMedian((recentListData || []).map(i => i.sbp));

    let trendText = '';
    if (recentListData && recentListData.length > 0) {
      const diff = Math.round(olderMedianSbp - recentMedianSbp);
      if (Math.abs(diff) < 3) {
        trendText = '与近期中位数相近';
      } else if (diff > 0) {
        trendText = `比近期收缩压中位数高约 ${diff} mmHg`;
      } else {
        trendText = `比近期收缩压中位数低约 ${Math.abs(diff)} mmHg`;
      }
    }

    return {
      count: cnt,
      medianSbp: Math.round(olderMedianSbp),
      trendText,
      distStable: pct(stable),
      distMild: pct(mild),
      distModerate: pct(moderate),
      distSignificant: pct(significant)
    };
  },

  drawYAxis() {
    const query = wx.createSelectorQuery();
    query.select('#yAxisCanvas').fields({ node: true, size: true }).exec(res => {
      if (!res[0]) return;
      const canvas = res[0].node;
      const dpr = wx.getSystemInfoSync().pixelRatio;
      canvas.width  = res[0].width  * dpr;
      canvas.height = res[0].height * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      const W = res[0].width;
      ctx.clearRect(0, 0, W, CHART_H);
      ctx.font      = 'bold 11px sans-serif';
      ctx.fillStyle = '#888';
      ctx.textAlign = 'right';
      Y_TICKS.forEach(val => {
        ctx.fillText(String(val), W - 4, getY(val) + 4);
      });
    });
  },

  // ★ 改：去掉了原来"个人稳态中位线"那条虚线——那是前端自己用 calcMedian() 现算的，
  //   现在前端不做这层计算了。以后如果要在图上标出稳态带（一个区间，不是一个点），
  //   需要后端把 steady_state.py 已经算好的基线/带宽通过接口单独暴露出来，
  //   这个可以作为后续的事，这次先解决"范围不同步"和"前端自己判断"这两个更迫切的问题。
  drawTrendChart(data, canvasWidth) {
    const query = wx.createSelectorQuery();
    query.select('#trendChart').fields({ node: true, size: true }).exec(res => {
      if (!res[0]) return;
      const canvas = res[0].node;
      const dpr = wx.getSystemInfoSync().pixelRatio;
      canvas.width  = canvasWidth * dpr;
      canvas.height = CHART_H * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);

      const W = canvasWidth;
      ctx.clearRect(0, 0, W, CHART_H);
      ctx.lineJoin = 'round';
      ctx.lineCap  = 'round';

      if (data.length === 0) return;

      const stepX = data.length > 1
        ? (W - PAD_L - PAD_R) / (data.length - 1)
        : W - PAD_L - PAD_R;
      const getX = i => PAD_L + i * stepX;

      // ★ 新增：点和线的粗细按数据密度自适应——90天窗口里数据点可能是几个，
      //   也可能是大几十个，固定粗细要么点少时显得单薄，要么点多时挤成一团
      const dotRadius = data.length > 60 ? 2 : data.length > 30 ? 3 : data.length > 12 ? 4 : 5;
      const lineW = data.length > 60 ? 1.5 : data.length > 30 ? 2 : 2.5;

      // 网格线（中性，不带任何固定标准值警戒线）
      Y_TICKS.forEach(val => {
        ctx.beginPath();
        ctx.strokeStyle = '#F0F0F0';
        ctx.lineWidth   = 1;
        ctx.setLineDash([]);
        ctx.moveTo(0, getY(val));
        ctx.lineTo(W, getY(val));
        ctx.stroke();
      });

      // 压差竖线（点多时适当变淡，避免糊成一片）
      data.forEach((item, i) => {
        ctx.beginPath();
        ctx.strokeStyle = data.length > 30 ? 'rgba(123,104,238,0.12)' : 'rgba(123,104,238,0.2)';
        ctx.lineWidth   = 1;
        ctx.moveTo(getX(i), getY(item.sbp));
        ctx.lineTo(getX(i), getY(item.dbp));
        ctx.stroke();
      });

      // 折线 + 渐变 + 数据点
      const drawLine = (key, color) => {
        const grad = ctx.createLinearGradient(0, PAD_TOP, 0, CHART_H - PAD_BTM);
        grad.addColorStop(0, color + '33');
        grad.addColorStop(1, color + '00');

        ctx.beginPath();
        data.forEach((item, i) => {
          const x = getX(i), y = getY(item[key]);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.lineTo(getX(data.length - 1), CHART_H - PAD_BTM);
        ctx.lineTo(getX(0), CHART_H - PAD_BTM);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth   = lineW;
        data.forEach((item, i) => {
          const x = getX(i), y = getY(item[key]);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();

        const labelStep = Math.max(1, Math.ceil(data.length / 10));
        data.forEach((item, i) => {
          const x = getX(i), y = getY(item[key]);
          ctx.beginPath();
          ctx.arc(x, y, dotRadius, 0, 2 * Math.PI);
          ctx.fillStyle   = '#fff';
          ctx.strokeStyle = color;
          ctx.lineWidth   = Math.max(1, lineW - 0.5);
          ctx.fill();
          ctx.stroke();

          if (i % labelStep === 0 || i === data.length - 1) {
            ctx.font      = '9px sans-serif';
            ctx.fillStyle = '#aaa';
            ctx.textAlign = 'center';
            const labelY  = key === 'sbp' ? y - 10 : y + 18;
            ctx.fillText(String(item[key]), x, labelY);
          }
        });
      };

      drawLine('sbp', '#FF6B6B');
      drawLine('dbp', '#4A90E2');

      // PP脉压差折线（紫色，细线）——只画数值走势，不做等级分类
      ctx.beginPath();
      ctx.strokeStyle = '#7B68EE88';
      ctx.lineWidth   = 1.5;
      ctx.setLineDash([3, 3]);
      data.forEach((item, i) => {
        const x = getX(i), y = getY(item.pp + Y_MIN);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);

      // X轴日期
      ctx.font      = '10px sans-serif';
      ctx.fillStyle = '#aaa';
      ctx.textAlign = 'center';
      data.forEach((item, i) => {
        if (data.length <= 10 || i % Math.ceil(data.length / 10) === 0 || i === data.length - 1) {
          ctx.fillText(item.dateShort || '', getX(i), CHART_H - 8);
        }
      });
    });
  },

  formatDate(dateStr) {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr.replace(/-/g, '/'));
      return `${d.getMonth()+1}/${d.getDate()}`;
    } catch (e) { return ''; }
  },

  onGoBack() {
    wx.navigateBack();
  }
});
