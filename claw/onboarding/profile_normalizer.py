# profile_normalizer.py
# 把用户答案转成学习画像

from .map import SCORING_MAP, RISK_RULES

# 维度分组：每个 dimension 内部有哪些属性
DIMENSION_GROUPS = {
    "learning_style": ["demand", "practice", "structure", "analogy"],
    "processing_mode": ["resistance", "high_agency", "low_agency"],
    "depth_tendency": ["deep", "verify", "shallow"],
    "agency": ["high_agency", "low_agency"],
    "stress_tolerance": ["stress_high", "stress_low"],
}


def normalize_profile(answers: dict, alpha: float = 1.0) -> dict:
    """
    把用户答案转成画像。

    参数:
        answers: {"q1": "A", "q2": "B", ...}
        alpha: 拉普拉斯平滑系数，默认 1.0

    返回:
        包含各维度概率分布的 dict
    """
    # 1. 初始化所有属性的 raw 分数为 0
    raw_scores = {
        dim: 0.0
        for dims in DIMENSION_GROUPS.values()
        for dim in dims
    }

    # 2. 查表累加
    for qid, options in SCORING_MAP.items():
        choice = answers.get(qid)
        if not choice:
            continue

        selected = options.get(choice)
        if not selected:
            continue

        for attr, score in selected.items():
            raw_scores[attr] += score

    # 3. 分组拉普拉斯平滑 + 归一化
    profile = {}
    for group_name, dims in DIMENSION_GROUPS.items():
        smoothed = {dim: raw_scores[dim] + alpha for dim in dims}
        total = sum(smoothed.values())

        profile[group_name] = {
            dim: round(score / total, 4)
            for dim, score in smoothed.items()
        }

    # 4. 风险信号检测
    profile["risk_flags"] = detect_risks(answers)

    return profile


def detect_risks(answers: dict) -> list:
    """
    根据固定规则检测风险信号。
    命中某些选项组合时打标签，但不改权重。
    """
    flags = []
    for name, rule in RISK_RULES.items():
        conditions = rule["conditions"]
        matched = all(
            answers.get(qid) == opt
            for qid, opt in conditions
        )
        if matched:
            flags.append({
                "type": name,
                "signals": [f"{qid}_{opt}" for qid, opt in conditions]
            })
    return flags
