"""用户画像摘要：把完整画像转成精简文本，省 token。"""


def format_profile(profile_json):
    """画像 → 摘要文本（每维度 top2）。"""
    if not profile_json:
        return "画像数据暂不可用"
    # 画像可能直接是各维度，也可能包在 "profile" 字段里
    data = profile_json.get("profile", profile_json) if isinstance(profile_json, dict) else {}
    names = {
        "learning_style": "学习风格",
        "processing_mode": "处理模式",
        "depth_tendency": "深度倾向",
        "blockage_response": "卡壳反应",
        "consolidation_style": "巩固方式",
        "agency": "主动性",
        "stress_tolerance": "压力耐受",
    }
    lines = []
    for category, weights in data.items():
        # risk_flags 这类 list 不是权重维度，跳过
        if not isinstance(weights, dict) or not weights:
            continue
        top2 = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:2]
        parts = [f"{k}:{v:.2f}" for k, v in top2]
        lines.append(f"{names.get(category, category)}：{' / '.join(parts)}")
    return "\n".join(lines)
