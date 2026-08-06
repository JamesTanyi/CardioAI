// pages/more/more.js
const app = getApp();

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
  }
});