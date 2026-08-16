// pages/report/clinical/clinical.js
// 新建页面：完整医生端临床报告，供患者自己调出、直接出示给接诊医生看。
// 不需要绑定过医生、不依赖医生账号权限——这份内容本来就是患者自己的数据，
// 每次测量分析时language.py就已经生成好了(reports.doctor)，只是之前
// 从来没有在患者端渲染出来。
const app = getApp();

Page({
  data: {
    reportHtml: '',
    hasReport: false
  },

  onLoad() {
    // ★ 数据不通过URL参数传递——doctor报告内容可能很长(含图表<img>标签等)，
    // encodeURIComponent之后容易超过小程序navigateTo的URL长度限制，改用
    // app.globalData中转。用完即清，避免下次直接进这个页面(比如误触发/
    // 从聊天记录里的历史消息再次点开)时残留上一次的旧内容。
    const rawReport = (app.globalData && app.globalData.pendingClinicalReport) || '';
    if (app.globalData) {
      app.globalData.pendingClinicalReport = '';
    }

    if (!rawReport) {
      this.setData({ hasReport: false });
      return;
    }

    this.setData({
      hasReport: true,
      reportHtml: this._markdownToHtml(rawReport)
    });
  },

  /**
   * 把language.py生成的doctor报告文本(简单的markdown风格：## 标题、
   * ### 小标题、- 列表项、---分隔线、原样嵌入的<img>标签)转成rich-text
   * 组件能直接渲染的HTML字符串。
   *
   * ★ 修复：之前这里错误地用了<view>/<text>这两个WXML组件标签去拼HTML
   * 字符串——rich-text的nodes解析的是真正的HTML，只认识<div>/<p>/<h3>
   * 这类标准标签，遇到<view>/<text>这种它不认识的标签会直接把内容连带
   * 丢弃，导致整个页面渲染出来是空白。现在全部换成真正的HTML标签。
   *
   * 不重新处理图表本身——<img>标签在language.py那边已经是完整、可直接
   * 使用的HTML，这里原样保留、不转义。
   */
  _markdownToHtml(text) {
    if (!text) return '<p>暂无报告内容</p>';
    const lines = text.split('\n');
    let html = '';
    let inList = false;

    const closeListIfOpen = () => {
      if (inList) {
        html += '</ul>';
        inList = false;
      }
    };

    lines.forEach((rawLine) => {
      const line = rawLine.trim();

      if (!line) {
        closeListIfOpen();
        return;
      }

      if (line.indexOf('<img') !== -1) {
        // 图片标签(含内联style)原样保留，不转义、不当成普通文本处理
        closeListIfOpen();
        html += `<div style="margin:16rpx 0;">${line}</div>`;
        return;
      }

      if (line.startsWith('## ')) {
        closeListIfOpen();
        html += `<h3 style="margin:28rpx 0 12rpx;font-size:32rpx;color:#1a7a4c;border-left:8rpx solid #1a7a4c;padding-left:16rpx;">${this._escapeHtml(line.slice(3))}</h3>`;
        return;
      }

      if (line.startsWith('### ')) {
        closeListIfOpen();
        html += `<h4 style="margin:18rpx 0 8rpx;font-size:27rpx;color:#333;">${this._escapeHtml(line.slice(4))}</h4>`;
        return;
      }

      if (line === '---') {
        closeListIfOpen();
        html += '<hr style="border:none;border-top:2rpx solid #eee;margin:20rpx 0;"/>';
        return;
      }

      if (line.startsWith('- ')) {
        if (!inList) {
          html += '<ul style="margin:8rpx 0;padding-left:32rpx;">';
          inList = true;
        }
        html += `<li style="font-size:25rpx;color:#555;margin-bottom:6rpx;">${this._escapeHtml(line.slice(2))}</li>`;
        return;
      }

      closeListIfOpen();
      html += `<p style="font-size:26rpx;color:#555;margin:6rpx 0;line-height:1.6;">${this._escapeHtml(line)}</p>`;
    });

    closeListIfOpen();
    return html;
  },

  _escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  },

  goBack() {
    wx.navigateBack({
      fail: () => wx.reLaunch({ url: '/pages/index/index' })
    });
  }
});