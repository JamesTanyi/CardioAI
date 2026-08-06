// pages/history/upload/upload.js
// ★ 本次重写：原文件同时维护 CSV 客户端解析、JSON 解析、逐条调用旧版嵌套格式 /analyze
//   等多条并行路径，其中"正常"的 CSV/JSON 路径实际用的是已经废弃的嵌套请求格式，
//   一直是跑不通的；而真正能用的 Excel 路径又被界面上的弹窗主动拦截了。
//   现在统一简化为一条路径：选择文件（.xlsx/.xls/.csv）→ 整份上传给后端解析入库，
//   不在前端做任何字段解析/校验/计算，全部交给后端 /upload_excel 处理。
const cloudService = require('../../../utils/cloudService.js');

Page({
  data: {
    userId: '',
    selectedFileName: '',
    selectedFilePath: '',
    uploadStatus: '',
    uploading: false
  },

  onShow() {
    this.setData({ userId: wx.getStorageSync('app_user_id') || '' });
  },

  // 查看模板说明（只做展示，不生成/解析任何数据）
  showTemplateInfo() {
    wx.showModal({
      title: '📥 文件格式说明',
      content: '支持 Excel(.xlsx) 或 CSV(.csv) 文件，表头需包含以下列：\n\n日期、时间、收缩压、舒张压（必填）\n心率（可选，缺省按75计算）\n\n日期格式建议：YYYY-MM-DD\n时间格式建议：HH:MM',
      showCancel: false,
      confirmText: '我知道了'
    });
  },

  chooseHistoryFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['csv', 'xlsx', 'xls'],
      success: (res) => {
        const file = res.tempFiles && res.tempFiles[0];
        if (!file) {
          wx.showToast({ title: '未选择文件', icon: 'none' });
          return;
        }

        const ext = (file.name || '').match(/\.([^.]+)$/)?.[1]?.toLowerCase() || '';
        if (!['csv', 'xlsx', 'xls'].includes(ext)) {
          wx.showToast({ title: '仅支持 CSV/Excel 文件', icon: 'none' });
          return;
        }

        this.setData({
          selectedFileName: file.name,
          selectedFilePath: file.path,
          uploadStatus: `已选择文件：${file.name}`
        });
      },
      fail: (err) => {
        if (err.errMsg !== 'chooseMessageFile:fail cancel') {
          wx.showToast({ title: '选择文件失败', icon: 'none' });
        }
      }
    });
  },

  uploadHistory() {
    const { userId, selectedFilePath, selectedFileName } = this.data;

    if (!userId) {
      wx.showToast({ title: '请先完成用户注册', icon: 'none' });
      return;
    }
    if (!selectedFilePath) {
      wx.showToast({ title: '请先选择历史文件', icon: 'none' });
      return;
    }

    this.setData({ uploading: true, uploadStatus: `正在上传文件：${selectedFileName}` });

    cloudService.uploadExcel(selectedFilePath, selectedFileName, userId)
      .then((res) => {
        this.setData({ uploading: false });
        if (res && res.code === 0) {
          const { imported = 0, skipped = 0 } = res.data || {};
          this.setData({
            uploadStatus: `导入完成：成功 ${imported} 条${skipped > 0 ? `，跳过 ${skipped} 条（缺必填字段）` : ''}`
          });
          wx.showToast({ title: `成功导入 ${imported} 条`, icon: 'success' });
        } else {
          const msg = (res && res.msg) || '服务异常';
          this.setData({ uploadStatus: `上传失败：${msg}` });
          wx.showToast({ title: msg, icon: 'none' });
        }
      })
      .catch((err) => {
        this.setData({
          uploading: false,
          uploadStatus: `网络错误：${err.message || err.errMsg || '未知错误'}`
        });
        wx.showToast({ title: '上传失败', icon: 'none' });
      });
  }
});