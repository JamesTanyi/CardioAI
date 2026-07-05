from datetime import datetime, timedelta

# --- 90天用户体验曲线常量 ---
PHASE_1_ONBOARDING = "P1_ONBOARDING"       # Day 1-3: 建立信任，降低认知门槛
PHASE_2_BASELINE   = "P2_BASELINE"         # Day 4-14: 建立基线，校准数据
PHASE_3_HABIT      = "P3_HABIT_FORMATION"  # Day 15-30: 习惯养成，连续性激励
PHASE_4_IMPROVE    = "P4_IMPROVEMENT"      # Day 31-60: 趋势分析，生活方式干预
PHASE_5_MASTERY    = "P5_MASTERY"          # Day 61-90: 自我管理，深度洞察
PHASE_6_MAINTENANCE= "P6_MAINTENANCE"      # Day 90+: 长期维护，异常预警

def _get_date(record):
    """安全获取记录的日期"""
    if not isinstance(record, dict):
        return None
    dt = record.get('datetime') or record.get('timestamp')
    if isinstance(dt, str):
        try:
            # 处理 ISO 格式字符串
            return datetime.fromisoformat(dt.replace(" ", "T")).date()
        except ValueError:
            return None
    elif isinstance(dt, datetime):
        return dt.date()
    return None

def _get_datetime(record):
    """安全获取记录的完整时间"""
    if not isinstance(record, dict):
        return None
    dt = record.get('datetime') or record.get('timestamp')
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt.replace(" ", "T"))
        except ValueError:
            return None
    elif isinstance(dt, datetime):
        return dt
    return None

class StageManager:
    """
    用户阶段判断 (Stage Manager)
    负责根据用户活跃天数确定当前的体验阶段。
    """
    @staticmethod
    def determine_phase(days_active):
        """根据活跃天数确定 90 天用户体验阶段"""
        if days_active <= 3: return PHASE_1_ONBOARDING
        if days_active <= 14: return PHASE_2_BASELINE
        if days_active <= 30: return PHASE_3_HABIT
        if days_active <= 60: return PHASE_4_IMPROVE
        if days_active <= 90: return PHASE_5_MASTERY
        return PHASE_6_MAINTENANCE

    @staticmethod
    def get_legacy_stage(ux_phase):
        """兼容旧代码的 stage 字段映射"""
        stage_mapping = {
            PHASE_1_ONBOARDING: "baseline",
            PHASE_2_BASELINE: "baseline",
            PHASE_3_HABIT: "confirm",
            PHASE_4_IMPROVE: "trend_phase",
            PHASE_5_MASTERY: "trend_phase",
            PHASE_6_MAINTENANCE: "long_term"
        }
        return stage_mapping.get(ux_phase, "long_term")

class BehaviorScore:
    """
    活跃度评分 (Behavior Score)
    负责计算用户的连续性、成熟度等行为指标。
    """
    @staticmethod
    def calculate_continuity(records, total_days):
        """计算连续性 (记录数 / 总天数)"""
        return len(records) / total_days if total_days > 0 else 0.0

    @staticmethod
    def calculate_maturity(total_days):
        """计算成熟度 (Maturity) - 每30天升一级"""
        maturity_int = min(5, int(total_days / 30) + 1)
        return f"L{maturity_int}"

    @staticmethod
    def calculate_regularity(records):
        """
        计算规律性评分 (Regularity Score)
        基于测量时间点（分钟）的标准差。
        """
        if len(records) < 2:
            return 0.0
        
        minutes = []
        for r in records:
            dt = _get_datetime(r)
            if dt:
                minutes.append(dt.hour * 60 + dt.minute)
        
        if len(minutes) < 2:
            return 0.0
            
        n = len(minutes)
        mean = sum(minutes) / n
        variance = sum((x - mean) ** 2 for x in minutes) / (n - 1)
        sd = variance ** 0.5
        
        # 归一化: SD=0 -> 1.0, SD=60 -> 0.5
        return round(1.0 / (1.0 + (sd / 60.0)), 2)

    @staticmethod
    def calculate_streak(dates):
        """
        计算连续打卡天数 (Streak)
        """
        if not dates:
            return 0
        
        # 去重并排序
        unique_dates = sorted(list(set(dates)))
        if not unique_dates:
            return 0
            
        streak = 1
        # 从最后一天倒推
        for i in range(len(unique_dates) - 1, 0, -1):
            if (unique_dates[i] - unique_dates[i-1]).days == 1:
                streak += 1
            else:
                break
        return streak

def calculate_lifecycle_state(records):
    """
    计算用户的生命周期状态 (数据库持久化状态模型)
    """
    if not records:
        return {
            "stage": "baseline",
            "total_days": 0,
            "days_active": 0,
            "continuity": 0.0,
            "continuity_score": 0.0,
            "regularity_score": 0.0,
            "current_streak": 0,
            "maturity_level": "L1",
            "cycle_day": 1,
            "ux_phase": PHASE_1_ONBOARDING,
            "cycle_info": {
                "current_cycle": 1,
                "day_in_cycle": 1,
                "cycle_length": 7,
                "is_complete": False
            },
            "milestones": []
        }

    # 1. 提取并排序日期
    dates = []
    for r in records:
        d = _get_date(r)
        if d:
            dates.append(d)
    
    if not dates:
         return calculate_lifecycle_state([])

    dates.sort()
    start_date = dates[0]
    end_date = dates[-1]
    
    # 2. 计算总跨度天数
    total_days = (end_date - start_date).days + 1
    
    # 3. 计算周期信息 (7天一周期)
    cycle_length = 7
    current_cycle = (total_days - 1) // cycle_length + 1
    cycle_day = total_days % cycle_length or cycle_length
    is_complete = (cycle_day == cycle_length)
    
    # 4. 计算行为指标
    continuity = BehaviorScore.calculate_continuity(records, total_days)
    maturity_level = BehaviorScore.calculate_maturity(total_days)
    regularity_score = BehaviorScore.calculate_regularity(records)
    current_streak = BehaviorScore.calculate_streak(dates)
    
    # 5. 确定阶段
    ux_phase = StageManager.determine_phase(total_days)
    stage = StageManager.get_legacy_stage(ux_phase)

    # 7. 构造持久化状态对象
    return {
        "total_days": total_days,
        "days_active": total_days, # 兼容旧字段名
        "continuity": continuity,
        "continuity_score": continuity, # 兼容旧字段名
        "current_streak": current_streak, # 新增：连续打卡天数
        "regularity_score": regularity_score,
        "maturity_level": maturity_level,
        "cycle_day": cycle_day,
        "cycle_info": {
            "current_cycle": current_cycle,
            "day_in_cycle": cycle_day,
            "cycle_length": cycle_length,
            "is_complete": is_complete
        },
        # 新增：90天体验曲线核心字段
        "ux_phase": ux_phase,
        "stage": stage, # 保留用于兼容
        "last_updated": datetime.now().isoformat()
    }