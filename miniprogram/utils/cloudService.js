// ⚠️ 本地调试模式——USE_LOCAL_DEBUG=true 时走普通 wx.request 直连本机 Flask，
// 不走云托管的 wx.cloud.callContainer，省掉每次改后端都要重新构建镜像+部署的等待。
// ⚠️ 但也因此没有云托管自动注入的 X-WX-OPENID 这个机制，wx_login 那条身份识别
// 链路在本地模式下走不通——本地测试改成直接手动写本地缓存伪装身份，见 app.js
// 的 onLaunch，本地模式下会跳过 _resolveIdentity()，不依赖 wx_login。
// 要连云托管测试时，改回 false。
const USE_LOCAL_DEBUG = false;

const SERVICE_NAME = 'cardioai-wechat';  // ← 必须和云托管控制台里创建的服务名完全一致
// ⚠️ 换成你本机的局域网IP + Flask实际监听的端口(不是127.0.0.1，手机连不到)
// 端口以 python app.py 启动时控制台打印的 "Running on http://<你的IP>:<端口>" 为准
const LOCAL_BASE_URL = 'http://192.168.178.28:80';

function _cloudCall(path, method = 'GET', data = null) {
  return new Promise((resolve, reject) => {
    if (USE_LOCAL_DEBUG) {
      const params = {
        // ★ 修复：这里原来漏了 /api 前缀——云托管模式(下面那个分支)请求路径是
        //   /api${path}，本地这条路径一直没跟着加，导致后端路由匹配不上，
        //   本地调试模式实测会直接404。这里补上，跟云托管模式保持一致。
        url: `${LOCAL_BASE_URL}/api${path}`,
        method: method,
        header: { 'content-type': 'application/json' },
        success: (res) => {
          if (res.statusCode === 200 && res.data) {
            resolve(res.data);
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(res.data)}`));
          }
        },
        fail: (err) => {
          console.error('[cloudService] wx.request 失败:', JSON.stringify(err));
          reject(err);
        }
      };
      if (data && method !== 'GET') {
        params.data = data;
      }
      wx.request(params);
      return;
    }

    // 云托管模式（服务重新搭建好后启用）
    const params = {
      path: `/api${path}`,
      method: method,
      header: {
        'X-WX-SERVICE': SERVICE_NAME,
        'content-type': 'application/json'
      },
      success: (res) => {
        if (res.statusCode === 200 && res.data) {
          resolve(res.data);
        } else {
          // ★ 改：在这里先打印清楚，不依赖调用方能不能正确读出 Error.message
          //   （JSON.stringify(Error对象) 会丢失 message，变成看不出原因的 {}）
          console.error(`[cloudService] callContainer 返回异常 | path=${path} | statusCode=${res.statusCode} | data=`, res.data);
          reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(res.data)}`));
        }
      },
      fail: (err) => {
        console.error('[cloudService] callContainer 失败:', JSON.stringify(err));
        reject(err);
      }
    };
    if (data && method !== 'GET') {
      params.data = data;
    }
    wx.cloud.callContainer(params);
  });
}

// ──────────────────────────────────────────────
// 通用 GET/POST 包装
// ──────────────────────────────────────────────
function get(path) { return _cloudCall(path, 'GET'); }
function post(path, data) { return _cloudCall(path, 'POST', data); }

/**
 * 文件上传（Excel/CSV，历史数据批量导入）
 * ★ 改：原来用 wx.uploadFile 直接打裸域名（http://<服务名>/upload_excel），
 *   这套机制在本项目里从未验证通过（实测 404），且和其他所有接口
 *   用 wx.cloud.callContainer 的方式不一致。现在改成读取文件内容并转成
 *   base64 字符串，当作普通 JSON 数据，通过已经反复验证可靠的
 *   callContainer 机制发送——体积增加约33%，但历史数据文件通常只有
 *   几十行、几KB，完全可以忽略。
 */
function uploadFile(filePath, fileName, userId) {
  return new Promise((resolve, reject) => {
    const fileManager = wx.getFileSystemManager();
    fileManager.readFile({
      filePath: filePath,
      encoding: 'base64',
      success: (readRes) => {
        post('/upload_excel', {
          fileName: fileName,
          userId: userId,
          fileBase64: readRes.data
        }).then(resolve).catch(reject);
      },
      fail: (err) => {
        console.error('[cloudService] 读取待上传文件失败:', JSON.stringify(err));
        reject(err);
      }
    });
  });
}

// ──────────────────────────────────────────────
// API 方法导出
// ★ 本次清理：删除了以下确认无任何页面调用的死代码方法
//   （2026-07-22 全项目搜索确认无引用）：
//   - generateInviteCode / bindByCode / confirmBinding / rejectBinding（V11 邀请码模式，已废弃）
//   - getPatientSummary（无调用方）
//   - getFamilyPatient（唯一调用方 family/dashboard 的 loadFamilyBinding() 本身就是死函数，未被触发）
//   - getFamilyList（无调用方）
//   - getPatientsRiskSummary（doctor/dashboard 已改用本地统计，不再需要这个接口）
//   若未来需要恢复，可从 Git 历史中找回。
// ──────────────────────────────────────────────
const api = {
  // ── 身份识别（openid 体系） ──
  // ★ 改：不再需要 wx.login() 拿 code——微信云托管在 wx.cloud.callContainer
  //   调用时会自动在请求头里携带 X-WX-OPENID，后端直接读取即可
  wxLogin: () => post('/wx_login', {}),

  // ── 绑定相关（V10 主流程） ──
  getBindingStatus: (userId) => get(`/get_binding_status?userId=${encodeURIComponent(userId)}`),
  validateInvite: (patientId, role) => post('/validate_invite', { patientId, role }),
  // ★ 改：payload 现在需要带 viewerOpenid 而不是 viewerId（由调用方 bind-confirm.js 负责传入）
  bindByInvite: (payload) => post('/bind_by_invite', payload),

  // ── 取消绑定（新增，三方均可发起） ──
  getMyBindings: (openid) => get(`/get_my_bindings?openid=${encodeURIComponent(openid)}`),
  cancelBinding: (payload) => post('/cancel_binding', payload),

  // ── 医生端：患者列表分页/搜索 ──
  // 后端路由 /get_doctor_patients 已实现（按姓名搜索+按风险等级降序排序+分页）
  getDoctorPatients: (doctorId, page = 1, pageSize = 20, keyword = '') => {
    let path = `/get_doctor_patients?doctorId=${encodeURIComponent(doctorId)}&page=${page}&pageSize=${pageSize}`;
    if (keyword) path += `&keyword=${encodeURIComponent(keyword)}`;
    return get(path);
  },

  // ── 历史记录 ──
  getHistory: (userId, viewerId = '', limit = 1000) => {
    let path = `/get_history?userId=${encodeURIComponent(userId)}&limit=${limit}`;
    if (viewerId) path += `&viewerId=${encodeURIComponent(viewerId)}`;
    return get(path);
  },
  analyze: (data) => post('/analyze', data),
  saveHistory: (data) => post('/save_history', data),
  uploadExcel: (filePath, fileName, userId) => uploadFile(filePath, fileName, userId),

  // ── 反馈消息 ──
  // ★ 改：getFeedback 补上 viewerId 参数——之前只传 userId，后端的
  //   require_binding_permission 装饰器在缺少 viewerId 时会直接放行（形同虚设），
  //   现在反馈改成"以患者为中心的共享留言板"，必须带上真实的查看者身份才能正确校验权限
  // ★ 再改：多医生留言隔离上线后，留言线按 patientId+doctorId 拆分。
  //   ⚠ doctorId 是必填参数——后端 get_feedback 缺少 doctorId 会直接返回 400，
  //   不存在"不传 doctorId 就返回公共线"这种模式，调用方必须先选定一位医生
  //   （只绑定一位医生时可以直接用那唯一的 doctorId，不需要用户手动选）
  getFeedback: (patientId, viewerId, doctorId) => {
    let path = `/get_feedback?userId=${encodeURIComponent(patientId)}&doctorId=${encodeURIComponent(doctorId)}`;
    if (viewerId) path += `&viewerId=${encodeURIComponent(viewerId)}`;
    return get(path);
  },
  // ★ 改：payload 现在需要带 doctorId(必填)，标明这条留言属于哪条医生线
  sendFeedback: (payload) => post('/send_feedback', payload),
  // ★ 新增：记录"这个查看者刚看过这个患者的留言线"，各端(患者/家属/医生)独立记录已读进度
  // ★ 改：payload 同样需要带 doctorId(必填)，未读计数改成按线区分
  markFeedbackRead: (payload) => post('/mark_feedback_read', payload),
  // ★ 新增：家属/患者查询该患者已绑定的医生列表，用于留言页的医生选择器
  //   （只绑定一位医生时前端不展示选择器，直接用该医生的线）
  //   ⚠ patientId 和 viewerId 都是必填——后端用 viewerId 判断查看者是患者本人
  //   还是该患者的绑定家属(医生调用会被拒绝，返回403，这个接口不是给医生用的)
  getPatientDoctors: (patientId, viewerId) =>
    get(`/get_patient_doctors?patientId=${encodeURIComponent(patientId)}&viewerId=${encodeURIComponent(viewerId)}`),
  // ★ 新增：查"我"相对于某个具体患者，真实持有的关系角色(patient/doctor/family/none)——
  //   不依赖本地缓存的 currentRole(只反映最近一次冷启动时服务器记的角色，
  //   同一个微信账号身兼多重身份——比如既是A的家属又是B的医生——时会认错)，
  //   直接查绑定关系表，以"针对这一个患者"为准。feedback.js 判断"我在这条
  //   留言线上是什么角色"要用这个，不能用 currentRole。
  getRelationRole: (patientId, viewerId) =>
    get(`/get_relation_role?patientId=${encodeURIComponent(patientId)}&viewerId=${encodeURIComponent(viewerId)}`),
  // ★ 新增：患者删除单条/多条留言，仅患者本人可操作，家属/医生调用一律403
  //   payload: { viewerId, patientId, feedbackIds: [...] }
  deleteFeedback: (payload) => post('/delete_feedback', payload),
  // ★ 新增：清空该患者名下【全部医生留言线】的全部留言(不是按单条线清空)，仅患者本人可操作
  //   payload: { viewerId, patientId }  ← 注意没有 doctorId，后端本来就是全量清空
  clearFeedback: (payload) => post('/clear_feedback', payload),

  // ── 用户注册 ──
  // ★ 改：payload 现在需要带 openid 而不是 user_id（由调用方 UserProfile.js 负责传入）
  registerUser: (userData) => post('/register_user', userData),
};

// ★ 暴露给 app.js 用：本地调试模式下要跳过 _resolveIdentity()(wx_login那套身份
// 识别本地走不通)，改成信任手动写好的本地缓存测试身份。只在这一个地方定义
// USE_LOCAL_DEBUG，app.js 不再自己重复维护一份同样的开关，避免忘了同步。
api.USE_LOCAL_DEBUG = USE_LOCAL_DEBUG;

module.exports = api;