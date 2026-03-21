from typing import List, Dict, Any
from .risk_level import assess_risk_bundle
from .emergency import analyze_emergency
from .steady_state import analyze_steady_states
from .pattern import analyze_patterns
from .structure_shift import analyze_structure_shift
from .timeline import build_timeline
from .lifecycle import calculate_lifecycle_state

# 尝试导入语言模块，如果不存在则使用存根
try:
    from .language import generate_language_blocks
except ImportError:
    def generate_language_blocks(*args): return {}

class CardiovascularEngine:
    def __init__(self, history: List[Dict], current: Dict):
        """
        初始化引擎
        :param history: 历史测量记录列表 (已按时间归一化)
        :param current: 当前测量记录 (已按时间归一化)
        """
        self.history = history
        self.current = current
        
        # 合并记录并按时间排序，用于趋势分析
        self.all_records = history + [current]
        self.all_records.sort(key=lambda x: x["datetime"])

    def run_all_diagnostics(self) -> Dict[str, Any]:
        """
        执行所有诊断模块
        """
        # 1. 准备数据和基础分析
        records = self.all_records

        # 1.1 稳态分析 (Steady State) - 这是后续所有分析的基础
        print("   -> 正在执行: 稳态分析 (Steady State)...", flush=True)
        steady_data = analyze_steady_states(records)
        if not steady_data:
            steady_data = {}
            events_by_segment = []
            print("      ... 数据不足，跳过稳态分析。", flush=True)
        else:
            events_by_segment = steady_data.get("events_by_segment", [])
            print(f"      ... 稳态分段: {len(steady_data.get('segments', []))} 段", flush=True)
        
        # 1.2 模式识别 (Pattern)
        print("   -> 正在执行: 模式识别 (Pattern)...", flush=True)
        patterns = analyze_patterns(records)
        print(f"      ... 模式: Dip={patterns.get('nocturnal_dip')}, Surge={patterns.get('morning_surge')}", flush=True)
        
        # 2. 核心风险与状态评估
        # 2.1 风险评估 (Risk Level)
        print("   -> 正在执行: 风险评估 (Risk Level)...", flush=True)
        risk_bundle = assess_risk_bundle(records, steady_data, events_by_segment, patterns)
        print(f"      ... 风险评估: Level={risk_bundle.get('acute_risk_level')}, Plaque={risk_bundle.get('plaque_risk', {}).get('level')}", flush=True)
        
        # 2.2 结构变异 (Structure Shift)
        print("   -> 正在执行: 结构变异 (Structure Shift)...", flush=True)
        structure_shift = analyze_structure_shift(steady_data)
        print(f"      ... 结构变异: Level={structure_shift.get('shift_level')}", flush=True)
        
        # 2.3 急性动力学 (Emergency)
        print("   -> 正在执行: 急性动力学 (Emergency)...", flush=True)
        emergency_info = analyze_emergency(records, steady_data)
        print(f"      ... 急性事件: {emergency_info.get('emergency')}", flush=True)
        
        # 2.4 生命周期状态 (Lifecycle)
        print("   -> 正在执行: 生命周期状态 (Lifecycle)...", flush=True)
        lifecycle_state = calculate_lifecycle_state(records)
        print(f"      ... 生命周期: Phase={lifecycle_state.get('ux_phase')}, Days={lifecycle_state.get('total_days')}", flush=True)
        
        # 3. 结果整合与输出
        # 3.1 生成时间轴 (Timeline)
        print("   -> 正在执行: 时间轴生成 (Timeline)...", flush=True)
        timeline = build_timeline(
            records, 
            steady_data, 
            emergency_info, 
            events_by_segment, 
            risk_bundle
        )
        print(f"      ... 时间轴事件: {len(timeline)} 个", flush=True)
        
        # 3.2 生成自然语言报告 (Language)
        print("   -> 正在执行: 自然语言生成 (Language)...", flush=True)
        language_blocks = generate_language_blocks(records, steady_data, risk_bundle, patterns)
        print(f"      ... 已生成 User/Family/Doctor 报告", flush=True)

        # 9. 构造最终返回结果
        return {
            "risk_level": risk_bundle.get("acute_risk_level", "normal"),
            "risk_factors": risk_bundle.get("assessment_reasons", []),
            "message": language_blocks.get("user", "分析完成，但未生成用户报告。"),
            "details": {
                "risk": risk_bundle,
                "emergency": emergency_info,
                "patterns": patterns,
                "structure": structure_shift,
                "lifecycle": lifecycle_state,
                "timeline": timeline,
                "reports": language_blocks # 包含 user, family, doctor 报告
            },
            # 为前端展示增加当前测量值
            "current_measurement": {
                "sbp": self.current.get("sbp"),
                "dbp": self.current.get("dbp"),
                "hr": self.current.get("hr")
            },
        }