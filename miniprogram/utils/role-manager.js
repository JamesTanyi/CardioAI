/**
 * CardioAI 角色权限管理器
 */
const ROLES = {
  // 必须与 app.js 的 globalData.currentRole / getRole() 返回值一致（'user'，非 'patient'）
  PATIENT: 'user',
  FAMILY: 'family',
  DOCTOR: 'doctor'
};

const getRoleTheme = (role) => {
  switch(role) {
    case ROLES.DOCTOR: return { color: '#2c3e50', name: '临床专业版' };
    case ROLES.FAMILY: return { color: '#e67e22', name: '亲情守护版' };
    case ROLES.PATIENT: return { color: '#27ae60', name: '个人健康版' };
    default: return { color: '#27ae60', name: '个人健康版' };
  }
};

module.exports = {
  ROLES,
  getRoleTheme
};