const app = getApp()

Page({
  data: {
    sbp: '', // 高压
    dbp: '', // 低压
    hr: '',  // 心率
    time: '', // 测量时间
    
    // 症状列表（与后端 symptoms.py 对应）
    symptoms: [
      { label: '头晕', value: 'dizzy', selected: false },
      { label: '胸闷', value: 'chest_tightness', selected: false },
      { label: '心悸', value: 'palpitations', selected: false },
      { label: '胸痛', value: 'chest_pain', selected: false },
      { label: '乏力', value: 'fatigue', selected: false },
      { label: '呼吸困难', value: 'short_breath', selected: false },
      { label: '视物模糊', value: 'vision_loss', selected: false },
      { label: '焦虑紧张', value: 'anxiety', selected: false },
    ]
  },

  onLoad: function() {
    // 初始化时间为当前时间 HH:mm
    const now = new Date();
    const hours = now.getHours().toString().padStart(2, '0');
    const minutes = now.getMinutes().toString().padStart(2, '0');
    this.setData({
      time: `${hours}:${minutes}`
    });
  },

  // 切换症状选中状态
  toggleSymptom(e) {
    const index = e.currentTarget.dataset.index;
    const key = `symptoms[${index}].selected`;
    this.setData({
      [key]: !this.data.symptoms[index].selected
    });
  },

  bindTimeChange(e) {
    this.setData({ time: e.detail.value });
  },

  // 提交分析
  async submitAnalysis() {
    // 1. 基础校验
    const sbp = parseInt(this.data.sbp);
    const dbp = parseInt(this.data.dbp);
    
    if (!sbp || !dbp) {
      wx.showToast({ title: '请输入血压值', icon: 'none' });
      return;
    }
    if (sbp <= dbp) {
      wx.showToast({ title: '高压必须大于低压', icon: 'none' });
      return;
    }

    wx.showLoading({ title: 'AI 分析中...', mask: true });

    try {
      // 2. 构造数据
      // 获取选中的症状 value 列表
      const selectedSymptoms = this.data.symptoms
        .filter(item => item.selected)
        .map(item => item.value);

      // 构造完整时间字符串 (YYYY-MM-DD HH:mm:ss)
      const now = new Date();
      const dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD
      const fullDateTime = `${dateStr} ${this.data.time}:00`;

      // 模拟从缓存获取历史记录 (实际项目中应从 Storage 读取)
      const history = wx.getStorageSync('bp_history') || [];

      const currentData = {
        sbp: sbp,
        dbp: dbp,
        hr: parseInt(this.data.hr) || 75,
        datetime: fullDateTime,
        symptoms: selectedSymptoms
      };

      // 3. 调用云托管
      // 注意：service 名称需要替换为您实际的服务名，如 'cardioai-wechat'
      const res = await wx.cloud.callContainer({
        config: {
          env: 'prod-...', // 您的云环境ID，如果不填则自动匹配
        },
        path: '/analyze',
        header: {
          'X-WX-SERVICE': 'cardioai-wechat', // 您的服务名称
        },
        method: 'POST',
        data: {
          current: currentData,
          history: history
        }
      });

      wx.hideLoading();

      if (res.data && res.data.code === 0) {
        // 成功！将结果存入本地或传递给结果页
        // 这里先简单的打印
        console.log('分析结果:', res.data.data);
        wx.navigateTo({ url: `/pages/result/result?id=${Date.now()}` }); // 假设有个 result 页面
      } else {
        wx.showModal({ title: '分析失败', content: res.data.error || '未知错误' });
      }

    } catch (err) {
      wx.hideLoading();
      console.error(err);
      wx.showToast({ title: '网络请求失败', icon: 'none' });
    }
  }
});
