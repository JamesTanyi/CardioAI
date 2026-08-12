import os
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

# 尝试导入图表模块（依赖 matplotlib，requirements.txt 需要补上这个依赖）
try:
    from .plots_risk import plot_risk_scores
    from .plots_symptoms import plot_symptom_timeline
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False
    def plot_risk_scores(*args, **kwargs): return None
    def plot_symptom_timeline(*args, **kwargs): return None

# 图表输出目录：默认放在 Flask 默认的 static 目录下（<项目根>/static/reports），
# Flask 会自动把 static/ 暴露在 /static/ 路径下，无需额外加路由。
# 如果实际部署环境不是这种"和 app.py 同级的 static 目录 + 同源访问"结构，
# 请通过环境变量 CHART_OUTPUT_DIR / PUBLIC_BASE_URL 调整。
CHART_OUTPUT_DIR = os.environ.get(
    "CHART_OUTPUT_DIR",
    os.path.join(os.getcwd(), "static", "reports")
)
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")  # 例如 https://your-domain.com，留空则用相对路径


def _to_public_url(local_path):
    """把本地文件路径转换成医生端报告里可以直接 <img src> 的 URL"""
    if not local_path:
        return None
    filename = os.path.basename(local_path)
    return f"{PUBLIC_BASE_URL}/static/reports/{filename}"


class CardiovascularEngine:
    def __init__(self, history: List[Dict], current: Dict, health_history: List[str] = None):
        """
        初始化引擎
        :param history: 历史测量记录列表 (已按时间归一化)
        :param current: 当前测量记录 (已按时间归一化)
        :param health_history: ★ 新增：患者既往病史(注册时勾选的列表，
            如["高血压","冠心病","心肌梗死"])，供risk_level.py的Path B
            判断时提高敏感度用(有高危病史的人阈值应该更容易触发就医建议)
        """
        self.history = history
        self.current = current
        self.health_history = health_history or []

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
            print(f"      ... 稳态分段: {len(steady_data.get('segments', []))} 段, "
                  f"多窗口: {list(steady_data.get('windows', {}).keys())}", flush=True)

        # 1.2 模式识别 (Pattern)
        print("   -> 正在执行: 模式识别 (Pattern)...", flush=True)
        patterns = analyze_patterns(records)
        print(f"      ... 模式: Dip={patterns.get('nocturnal_dip')}, Surge={patterns.get('morning_surge')}", flush=True)

        # 2. 核心风险与状态评估
        # 2.1 急性动力学 (Emergency) —— ★ 改：挪到风险评估之前算，因为
        #     risk_level.py的Path B判断现在要用它的结果，不能像原来那样
        #     算完只扔给医生时间轴看、自己却从来用不上
        print("   -> 正在执行: 急性动力学 (Emergency)...", flush=True)
        emergency_info = analyze_emergency(records, steady_data)
        print(f"      ... 急性事件: {emergency_info.get('emergency')}", flush=True)

        # 2.2 风险评估 (Risk Level) —— ★ 改：把emergency_info和health_history
        #     一起传进去，供Path A/B判断使用
        print("   -> 正在执行: 风险评估 (Risk Level)...", flush=True)
        risk_bundle = assess_risk_bundle(records, steady_data, events_by_segment, patterns, emergency_info, self.health_history)
        print(f"      ... 风险评估: Level={risk_bundle.get('acute_risk_level')}, Plaque={risk_bundle.get('plaque_risk', {}).get('level')}", flush=True)

        # 2.3 结构变异 (Structure Shift)
        print("   -> 正在执行: 结构变异 (Structure Shift)...", flush=True)
        structure_shift = analyze_structure_shift(steady_data)
        print(f"      ... 结构变异: Level={structure_shift.get('shift_level')}", flush=True)

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

        # 3.2 生成图表（仅供医生端使用）
        print("   -> 正在执行: 图表生成 (Charts, 医生端专用)...", flush=True)
        risk_chart_url = None
        symptom_chart_url = None
        if CHARTS_AVAILABLE:
            try:
                risk_chart_path = plot_risk_scores(risk_bundle, CHART_OUTPUT_DIR)
                risk_chart_url = _to_public_url(risk_chart_path)
            except Exception as e:
                print(f"      ... 风险评分图生成失败: {e}", flush=True)
            try:
                symptom_chart_path = plot_symptom_timeline(records, events_by_segment, CHART_OUTPUT_DIR)
                symptom_chart_url = _to_public_url(symptom_chart_path)
            except Exception as e:
                print(f"      ... 症状时间线图生成失败: {e}", flush=True)
        else:
            print("      ... matplotlib 未安装，跳过图表生成（需要在 requirements.txt 补上 matplotlib）", flush=True)
        print(f"      ... 风险图: {risk_chart_url}, 症状图: {symptom_chart_url}", flush=True)

        # 3.3 生成自然语言报告 (Language)
        print("   -> 正在执行: 自然语言生成 (Language)...", flush=True)
        # 注意：这里过去把 patterns 直接当 figure_paths 传进去是个 bug——
        # language.py 的医生报告需要的是 {"patterns": {...}, "risk_scores_url": ..., "symptom_timeline_url": ...}
        # 这样的结构，而不是 patterns 本身。
        figure_paths = {
            "patterns": patterns,
            "risk_scores_url": risk_chart_url,
            "symptom_timeline_url": symptom_chart_url,
        }
        language_blocks = generate_language_blocks(records, steady_data, risk_bundle, figure_paths)
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
                "reports": language_blocks  # 包含 user, family, doctor 报告
            },
            # 为前端展示增加当前测量值
            "current_measurement": {
                "sbp": self.current.get("sbp"),
                "dbp": self.current.get("dbp"),
                "hr": self.current.get("hr")
            },
        }