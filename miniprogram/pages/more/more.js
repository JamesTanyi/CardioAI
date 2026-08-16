// pages/more/more.js
const app = getApp();
const cloudService = require('../../utils/cloudService.js');

// 万能安全跳转器：自动识别并处理 TabBar 页面，路径错误时提供友好提示
function safeNavigate(url) {
  wx.navigateTo({
    url: url,
    fail: (err) => {
      if (err.errMsg && (err.errMsg.indexOf('tabbar') !== -1 || err.errMsg.indexOf('can not navigate to a tabbar page') !== -1)) {
        wx.switchTab({ url: url.split('?')[0] });
      } else {
        console.error(`[More] 跳转页面失败，请核对路径是否存在于 app.json 中: ${url}`, err);
        wx.showToast({ title: '功能建设中或路径错误', icon: 'none' });
      }
    }
  });
}

Page({
  data: {
    unreadCount: 0
  },

  onShow() {
    this.checkUnreadFeedback();
  },

  /**
   * 检查未读反馈消息
   * ★ 改：这里原来自己发一个 cloudService.getFeedback(userId) 请求来算未读数——
   *   多医生留言隔离上线后，get_feedback 的 doctorId 变成必填参数，这个旧调用
   *   已经失效(会400)，导致这个角标一直显示不出来。
   *   现在改成直接读 app.js 的 syncAllBindings 已经从 get_binding_status 同步好
   *   的 selfUnreadFeedbackCount(后端已经统计了"我这个患者，名下所有医生线的
   *   未读留言总数")，不再重复发请求。
   */
  checkUnreadFeedback() {
    const readFromGlobal = () => {
      const badge = app.globalData.alertBadge || {};
      this.setData({ unreadCount: badge.selfUnreadFeedbackCount || 0 });
    };

    if (app.globalData.bindingsReady) {
      readFromGlobal();
    } else {
      // 绑定数据还没同步完(比如冷启动第一次进这个页面)，等 app.js 同步完再读一次
      app.syncAllBindings(() => readFromGlobal());
    }
  },

  /** 基础跳转：处理 data-url 静态传参 */
  goToFeature(e) {
    const url = e.currentTarget.dataset.url;
    if (url) {
      safeNavigate(url);
    } else {
      wx.showToast({ title: '路径配置为空', icon: 'none' });
    }
  },

  /** 查看最近一次分析结果 */
  goToLatestResult() {
    const history = wx.getStorageSync('measure_history') || [];
    if (history.length > 0) {
      const latest = history[0];
      if (latest.analysis) {
        const resultStr = encodeURIComponent(JSON.stringify(latest.analysis));
        safeNavigate(`/pages/measure/result/result?data=${resultStr}`);
        return;
      }
    }
    safeNavigate('/pages/history/month/month');
  },

  /**
   * ★ 新增：常驻的"完整临床报告"入口——服务"随时想看/复诊前主动查看"这类
   * 场景，跟result.js那个"刚测完立刻可用"的快捷入口不冲突，各自解决对方
   * 解决不了的场景（这个入口手头没有"刚测完"的上下文，需要单独拉一次
   * 最新记录）。
   * 报告内容不通过URL参数传递——doctor报告内容可能很长(包含图表<img>
   * 标签等)，encodeURIComponent后容易超过小程序navigateTo的URL长度限制，
   * 改用app.globalData中转，避免这个风险。
   */
  goToClinicalReport() {
    const userId = wx.getStorageSync('app_user_id');
    if (!userId) {
      wx.showToast({ title: '请先完成注册', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '加载中...', mask: true });
    cloudService.getHistory(userId, '', 1)
      .then((res) => {
        wx.hideLoading();
        if (res && res.code === 0 && Array.isArray(res.data) && res.data.length > 0) {
          const latest = res.data[0];
          const doctorReport = (latest.analysis && latest.analysis.doctor) || '';
          if (!doctorReport) {
            wx.showToast({ title: '暂无可用报告，请先完成一次测量', icon: 'none' });
            return;
          }
          app.globalData.pendingClinicalReport = doctorReport;
          safeNavigate('/pages/report/clinical/clinical');
        } else {
          wx.showToast({ title: '暂无测量记录', icon: 'none' });
        }
      })
      .catch((err) => {
        wx.hideLoading();
        console.error('[More] 获取临床报告失败', err);
        wx.showToast({ title: '加载失败，请重试', icon: 'none' });
      });
  }
});