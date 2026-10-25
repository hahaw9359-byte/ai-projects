DIMENSIONS = {
    "learning_style":      ["demand", "practice", "structure", "analogy"],
    "blockage_response":   ["drill", "reroute", "diagnose"],
    "consolidation_style": ["cement", "rebuild", "surface"],
    "agency":              ["self_driven", "collaborative", "external"],
    "stress_tolerance":    ["stress_high", "stress_low"]
}


def normalize_profile(raw_scores,dimensions = DIMENSIONS,alpha = 1.0):
    profile = {}
    # 遍历 维度内容
    for dim_name, attrs in dimensions.items():
        # 拉普拉斯平滑
        smoothed = {}
        for attr in attrs:
            smoothed[attr] = raw_scores.get(attr,0) + alpha
        
        # 计算维度内得总分
        total = 0
        for score in smoothed.values():
            total = total +score
        
        # 归一化 每个属性除总分
        profile[dim_name] = {}
        for attr in attrs:
            profile[dim_name][attr] = smoothed[attr]/total
    return profile