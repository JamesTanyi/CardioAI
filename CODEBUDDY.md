# CODEBUDDY.md

This file provides guidance to CodeBuddy when working with code in this repository.

## 项目概述

"心安健" (BloodTrack) — 心血管健康监测微信小程序 + Python 后端。患者记录血压数据，AI 引擎分析心脑血管风险；家属和医生通过绑定关系查看患者数据并发送反馈。三角色（患者/家属/医生）共享同一套小程序，通过角色路由分发到不同仪表盘。

## 常用命令

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Flask 开发服务器（默认端口 80，debug=False）
python app.py

# 初始化/完善本地 SQLite 数据库（含测试数据）
python 完善数据库.py
```

⚠️ Flask 开发服务器以 `debug=False` 运行，修改代码后需手动重启。

### Docker 构建与运行

```bash
docker build -t bloodtrack .
docker run -p 80:80 -e FORCE_SQLITE=true bloodtrack
```

Dockerfile 使用 gunicorn（1 worker, 8 threads, `--timeout 0` 无请求超时限制），监听 80 端口。

### 远程部署

项目通过 CloudStudio 部署。环境变量 `FORCE_SQLITE=true` 强制使用 SQLite，`DB_PATH` 指向 `/workspace/data/bloodtrack.db` 确保持久化。生产环境部署到 CloudBase MySQL 时需移除 `FORCE_SQLITE`。

### 微信小程序

小程序入口为 `miniprogram/`，appid `wxc5b1f8601518c8cb`。使用微信开发者工具打开项目根目录即可。`project.config.json` 中 `miniprogramRoot` 指向 `miniprogram/`。

小程序 npm 依赖（`miniprogram/package.json`）：
- `ec-canvas` — ECharts 微信小程序组件（血压趋势图）
- `weapp-qrcode-canvas-2d` — QR 码生成（分享绑定页）

## 架构

### 整体分层

```
微信小程序 (miniprogram/)  ←→  Flask API (app.py)  ←→  DB (SQLite/MySQL)
                                   ↑
                            Engine (engine/)
```

### 后端 API (app.py)

**app.py** 是唯一的后端入口，一个单文件 Flask 应用。按以下顺序组织：

1. **数据库初始化**（第1-270行）：启动时自动选择 SQLite 或 MySQL。优先级：`FORCE_SQLITE=true` > `USE_CLOUD_DB` 环境变量 > 默认尝试 MySQL。MySQL 连接失败自动降级到 SQLite。SQLite 文件路径优先 `/workspace/data/bloodtrack.db`。

2. **辅助函数**：`_normalize_record_time` 将时间字段统一为 datetime 对象并计算脉压(pp)；`_format_record_for_db` 将前端数据标准化；`_save_measurement` / `_fetch_history_from_db` 封装写/读操作，内部根据 `USE_CLOUD_DB` 分支使用 pymysql 或 sqlite3。

3. **API 路由**（全部 RESTful，共 22 个）：

| 路由 | 方法 | 用途 |
|------|------|------|
| `/` | GET | 健康检查 |
| `/analyze` | POST | 核心分析：接收当前+历史记录，调用 Engine 返回风险评估 |
| `/save_history` | POST | 保存测量记录（支持单条或批量） |
| `/get_history` | GET | 读取历史数据（有 viewerId 时验证 active 绑定权限，无权限返回403） |
| `/bind_family` | POST | 家属发起绑定（status=pending，需患者确认） |
| `/bind_doctor` | POST | 医生发起绑定（status=pending，需患者确认） |
| `/confirm_binding` | POST | V8：确认绑定（pending→active） |
| `/reject_binding` | POST | V8：拒绝绑定（pending→rejected） |
| `/get_patient_summary` | GET | V8：获取患者摘要（姓名/年龄/性别/最近测量） |
| `/get_family_list` | GET | 获取家属已 active 绑定的患者列表 |
| `/get_family_patient` | GET | 家属查找绑定的任一 active 患者 |
| `/send_feedback` | POST | 家属/医生向已 active 绑定的患者发送反馈 |
| `/get_feedback` | GET | 患者获取收到的反馈（标为已读） |
| `/generate_invite_code` | POST | 患者生成 6 位邀请码（24h 有效期） |
| `/bind_doctor_by_code` | POST | 医生通过邀请码绑定（status=pending） |
| `/get_doctor_patients` | GET | 医生查看已 active 绑定的患者列表 |
| `/get_patients_risk_summary` | GET | 医生查看所有患者风险汇总 |
| `/upload_excel` | POST | 上传 Excel 批量导入测量数据 |
| `/get_binding_status` | GET | **启动入口**：返回用户全部绑定状态+预警摘要 |
| `/generate_invite_token` | POST | **V9 新增**：生成 48 位 hex 令牌（用于分享链接，避免暴露 patientId） |
| `/validate_invite_token` | POST | **V9 新增**：验证邀请令牌，返回患者摘要供绑定确认页 |
| `/bind_by_token` | POST | **V9 新增**：凭令牌完成绑定（家属/医生），status=pending，需患者后续确认 |

**关键设计模式**：所有写操作都通过 `conn = get_db(); cursor = conn.cursor(); try...finally: conn.close()` 模式，确保连接正确关闭。MySQL 和 SQLite 分支在每个 SQL 语句处 `if USE_CLOUD_DB` 切换。

⚠️ `/get_history` 路由使用了两次连接（验证绑定 + 获取数据各开一个），与其他路由的单连接模式不同。

### 数据库

7 张表（MySQL 和 SQLite 在 app.py 初始化时均已建表）：

- **measurements**：血压测量记录（user_id, sbp, dbp, hr, pp, symptoms, risk_level, risk_text, analysis, datetime, created_at）
- **users**：用户（user_id UNIQUE, name, age, gender, birthDate）
- **family_bindings**：家属绑定（family_id, patient_id, name, **status** DEFAULT 'active', UNIQUE）— status 值为 pending/active/rejected
- **doctor_bindings**：医生绑定（doctor_id, patient_id, doctor_name, hospital, department, **status** DEFAULT 'active', UNIQUE）— status 同上
- **feedbacks**：反馈消息（from_id, from_role, to_id, content, is_read）
- **invite_codes**：邀请码（code UNIQUE, patient_id, used, used_by, expires_at）— 6位数字码，24h有效期
- **invite_tokens**：邀请令牌（token UNIQUE, patient_id, role, used, used_by, expires_at）— 48位hex令牌，V9 分享绑定使用

⚠️ `完善数据库.py` 未创建 `invite_tokens` 表，单独运行会导致 V9 令牌路由失败。`family_bindings` 和 `doctor_bindings` 的 `status` 列 DEFAULT 为 `'active'`（向后兼容 pre-V8 数据），新建绑定需显式设置 `status='pending'`。

`symptoms` 和 `analysis` 字段存储 JSON 字符串。`pp`（脉压 = sbp - dbp）由 `_normalize_record_time` 自动计算。

**两阶段绑定模型**：`bind_family` / `bind_doctor` 创建记录时 status=`pending`（被邀请人可查看患者摘要但无数据权限）；患者确认调用 `/confirm_binding` 将 status 改为 `active`（此后可长期访问数据）；拒绝则 `/reject_binding` 设为 `rejected`。所有权限校验查询均要求 `status='active'`。

**V9 令牌分享机制**：`/generate_invite_token` 生成 48 位 hex 令牌，小程序分享页将令牌编码进 QR 码；intro 页收到令牌后调用 `/validate_invite_token` 获取患者摘要，再走绑定流程。旧版 `fromUserId` 参数仍保留向后兼容。

### Engine 分析引擎 (engine/)

`CardiovascularEngine` 是核心分析类（`engine/cardiovascular_engine.py`），入口 `run_all_diagnostics()` 串联 8 个诊断模块：

1. **steady_state.py** — `analyze_steady_states`：稳态分段（后续分析的基础）
2. **pattern.py** — `analyze_patterns`：模式识别（晨峰、夜间勺型等）
3. **risk_level.py** — `assess_risk_bundle`：多维度风险评估（急性风险、斑块风险）
4. **structure_shift.py** — `analyze_structure_shift`：结构变异检测
5. **emergency.py** — `analyze_emergency`：急诊动力学信号检测
6. **lifecycle.py** — `calculate_lifecycle_state`：生命周期状态计算
7. **timeline.py** — `build_timeline`：疾病时间线建模
8. **language.py** — `generate_language_blocks`：自然语言报告生成

`auto_threshold.py`、`plots_risk.py`、`plots_symptoms.py` 存在于 engine 目录但**不在** `run_all_diagnostics()` 主流程中调用。还有 `interaction.py`、`symptoms.py` 等辅助模块。`index.py` 是早期独立分析入口（端口8000），仅调用 risk_level + emergency + language，已不再使用。

### 微信小程序 (miniprogram/)

**全局中枢 — app.js**：
- `syncAllBindings()`：每次启动/恢复时调用 `/get_binding_status`，同步全部绑定关系+预警角标到 `globalData.bindings`
- `refreshBindings()`：页面级刷新绑定（轻量版，仅更新 bindings）
- `_autoRouteByRole()`：根据角色和绑定状态自动跳转到正确仪表盘
- `resetAutoRoute()`：清除 `_hasAutoRouted` / `_lastRouteTime` 标志，用于手动导航时重置
- `startAlertPolling()` / `stopAlertPolling()`：前台每 60 秒轮询绑定状态
- `globalData` 维护 `BASE_URL`（后端地址，部署时需修改）

**角色路由流程**：

```
APP 启动 → intro 页检查 localStorage
  ├─ 无 userProfile → 引导注册
  ├─ 有 userProfile + 绑定参数/令牌 → 调绑定 API → 等待成功 → reLaunch 仪表盘
  └─ 有 userProfile 无绑定参数 → reLaunch 历史仪表盘

仪表盘 onShow → refreshBindings → 加载数据（不冗余调 bind API）
```

**关键页面**（app.json 注册 13 个页面）：
- `pages/onboarding/intro/intro` — 启动入口，注册/绑定路由分发
- `pages/onboarding/UserProfile/UserProfile` — 用户资料表单（姓名/年龄/性别/出生日期）
- `pages/onboarding/DoctorRegister/DoctorRegister` — 医生注册页
- `pages/index/index` — 悁者主页
- `pages/measure/result/result` — 测量结果页
- `pages/family/dashboard/dashboard` — 家属仪表盘
- `pages/family/family/family` — 家属绑定流程页
- `pages/doctor/dashboard/dashboard` — 医生仪表盘（患者列表 + 医学报告）
- `pages/history/month/month` — 历史数据月视图
- `pages/history/upload/upload` — Excel/CSV 上传批量导入
- `pages/more/more` — 设置页（未读反馈数、绑定提醒）
- `pages/profile/share/share` — **V9** 令牌化 QR 码分享页
- `feedback/feedback` — 反馈列表页（⚠️ 此页在 `feedback/` 目录而非 `pages/` 下）

⚠️ `pages/profile/share/share`（V9，基于令牌）是当前唯一的分享页。旧版 `pages/index/share`（V7/V8，基于 fromUserId）已删除，`pages/index/` 下仅剩主页 `index.*`。（`pages/measure/month/` 目录在磁盘上存在但未在 app.json 注册，不可达。）

**绑定机制核心原则**：
1. intro 页收到绑定参数时，**必须先调用 bind API 并等待返回**，成功后才 reLaunch 仪表盘
2. 仪表盘 `onShow` **不再冗余调用 bind API**，直接 `refreshBindings()` + 加载数据
3. `get_history` 接口用 viewerId 校验双向绑定（家属或医生），无绑定返回 403
4. localStorage 的绑定标记是本地快速兜底，服务端 `get_binding_status` 是真相源

**角色身份**：存储在 `wx.getStorageSync('currentRole')`，值 'user' / 'family' / 'doctor'。`app.setRole()` / `app.getRole()` 统一管理。⚠️ `utils/role-manager.js` 定义 `ROLES.PATIENT = 'patient'`，与 app.js 使用的 `'user'` 不一致。

**前端组件与工具**：
- `miniprogram/components/echarts/` — ECharts 微信小程序封装组件（ec-canvas）
- `miniprogram/utils/role-manager.js` — 角色常量与主题色映射
- `miniprogram/utils/time-series-processor.js` — ECharts 图表配置生成与数据处理

### 环境变量

`.env.example` 包含配置模板：`USE_CLOUD_DB`、`DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`、`PORT`、`DB_PATH`。

### 注意

- `BASE_URL` 在 `miniprogram/app.js` 的 `globalData` 中配置，部署到新服务器后必须更新
- `index.py`（端口8000）和根目录 `index.js`/`index.wxml`/`index.wxss` 都是早期遗留文件，使用旧架构（云函数容器调用），已不再使用
- `build/` 目录包含编译产物，不手动编辑
- `完善数据库.py` 用于命令行初始化 SQLite 并灌入 30 天模拟数据，仅开发环境使用，但**不创建 invite_tokens 表**
- `push.ps1` 是已弃用的部署脚本（曾硬编码已暴露的 GitHub PAT，token 不可用），推送请用 `git push origin main`
- 项目无测试框架、无 linting 配置、无 CI/CD 流程
