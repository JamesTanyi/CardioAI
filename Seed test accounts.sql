-- ============================================================
-- 本地调试专用：固定测试账号种子数据
-- 用法：本地测试库(SQLite/MySQL均可，语法通用)建好表结构后跑一次
-- 三个账号：T001患者 / T002家属(绑T001) / T003医生(绑T001)
-- 切换身份不用重新登录，在小程序里用Console手动写本地缓存即可，见下方"配套操作"
-- ============================================================

-- 患者：陈测试
INSERT INTO users (user_id, openid, name, role, birth_date, age, gender, created_at)
VALUES ('T001', 'test-openid-p01', '陈测试', 'user', '1960-05-24', 66, 'male', CURRENT_TIMESTAMP);

-- 家属：李测试(家属)
INSERT INTO users (user_id, openid, name, role, created_at)
VALUES ('T002', 'test-openid-f01', '李测试(家属)', 'family', CURRENT_TIMESTAMP);

-- 医生：王测试(医生)
INSERT INTO users (user_id, openid, name, role, created_at)
VALUES ('T003', 'test-openid-d01', '王测试(医生)', 'doctor', CURRENT_TIMESTAMP);

-- 家属绑定关系：T002是T001的家属
INSERT INTO family_bindings (family_id, patient_id, name, status, created_at)
VALUES ('T002', 'T001', '李测试(家属)', 'active', CURRENT_TIMESTAMP);

-- 医生绑定关系：T003是T001的医生
INSERT INTO doctor_bindings (doctor_id, patient_id, doctor_name, hospital, department, status, created_at)
VALUES ('T003', 'T001', '王测试(医生)', '测试医院', '心血管内科', 'active', CURRENT_TIMESTAMP);