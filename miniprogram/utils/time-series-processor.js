/**
 * 时间序列数据处理器
 * 将原始数据转换为ECharts格式
 */

// 生成ECharts折线图配置
function generateLineChartConfig(timeSeriesData, baselineData) {
  const dates = timeSeriesData.dates || [];
  const sbp = timeSeriesData.sbp || [];  // 收缩压
  const dbp = timeSeriesData.dbp || [];  // 舒张压
  
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    legend: {
      data: ['收缩压', '舒张压', '稳态带上限', '稳态带下限']
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { rotate: 30 }
    },
    yAxis: {
      type: 'value',
      name: '血压 (mmHg)'
    },
    series: [
      {
        name: '收缩压',
        type: 'line',
        data: sbp,
        smooth: true,
        lineStyle: { color: '#ff4d4f', width: 2 },
        symbol: 'circle'
      },
      {
        name: '舒张压',
        type: 'line',
        data: dbp,
        smooth: true,
        lineStyle: { color: '#faad14', width: 2 },
        symbol: 'circle'
      },
      {
        name: '稳态带上限',
        type: 'line',
        data: Array(dates.length).fill((baselineData && baselineData.sbp && baselineData.sbp.upper) || 140),
        lineStyle: { type: 'dashed', color: '#999' },
        symbol: 'none'
      },
      {
        name: '稳态带下限',
        type: 'line',
        data: Array(dates.length).fill((baselineData && baselineData.dbp && baselineData.dbp.lower) || 80),
        lineStyle: { type: 'dashed', color: '#999' },
        symbol: 'none',
        areaStyle: { color: 'rgba(200,200,200,0.1)' }  // 填充稳态区域
      }
    ]
  };
}

// 处理医生端返回的完整数据
function processDoctorData(apiResponse) {
  if (!apiResponse || apiResponse.code !== 0) {
    return null;
  }
  
  const data = apiResponse.data || {};
  
  return {
    patientId: data.patient_id,
    demographics: data.demographics,
    parameters: data.hemodynamic_parameters,
    steadyState: data.individual_steady_state_band,
    trendAnalysis: data.trend_analysis,
    symptomCorrelation: data.symptom_correlation,
    riskPrediction: data.acute_event_prediction,
    recommendations: data.recommended_actions,
    charts: {
      primary: (data.charts_config && data.charts_config.primary) || generateLineChartConfig(
        data.hemodynamic_parameters,
        data.individual_steady_state_band
      ),
      secondary: (data.charts_config && data.charts_config.secondary)
    }
  };
}

module.exports = {
  generateLineChartConfig,
  processDoctorData
};