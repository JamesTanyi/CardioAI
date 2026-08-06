// 文件路径: miniprogram/utils/config.js

// ★★★ 云托管配置 ★★★
// 所有 API 调用统一通过 wx.cloud.callContainer，无需配置 IP 或域名
// - 本地调试：微信开发者工具 → 工具 → 云托管 → 开启本地调试 → 自动代理到本地容器
// - 生产环境：wx.cloud.callContainer 自动路由到云端容器内网地址

// 云托管服务名（与 cloudbase.yml / CloudBase 控制台保持一致）
const CLOUD_SERVICE_NAME = 'cardioai-backend';

// 保留 BASE_URL 仅用于 uploadFile 等 wx.uploadFile 直传场景
// DevTools 本地调试时 DevTools 会自动代理 127.0.0.1 到本地容器
const isDevTools = (() => {
  try {
    const si = wx.getSystemInfoSync();
    return si && si.platform === 'devtools';
  } catch (e) { return false; }
})();

// 仅 uploadFile 等特殊接口使用（统一 API 已迁移到 wx.cloud.callContainer）
const BASE_URL = isDevTools
  ? 'http://127.0.0.1'   // DevTools 本地调试：自动转发到云托管本地容器
  : 'http://cardioai-backend'; // 生产：云托管内网地址（由腾讯云自动解析）

module.exports = { CLOUD_SERVICE_NAME, BASE_URL };
