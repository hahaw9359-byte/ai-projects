# scoring_map.py
# 五大维度 + 独立压力乘区 v2
# 分数不统一：同维度内，不同选项体现的行为强度不同，分数反映程度差异

SCORING_MAP = {
    # 题 1：首次接触新材料 —— learning_style
    # 四个输入倾向互斥，全 1.0
    "q1": {
        "A": {"demand": 1.0},
        "B": {"practice": 1.0},
        "C": {"structure": 1.0},
        "D": {"analogy": 1.0}
    },

    # 题 2：第一次报错/失败 —— blockage_response
    # A 直接问人 = 最典型的路径重选，给 1.0
    # B 自己盯报错 = 定点突破，给 1.0
    # C 换教程 = 也是路径重选，但比直接问人弱一点（换资源 vs 靠人），给 0.8
    # D 跳过 = 路径重选的末端——"以后再说"是最弱的绕路，给 0.3
    "q2": {
        "A": {"reroute": 1.0},
        "B": {"drill": 1.0},
        "C": {"reroute": 0.8},
        "D": {"reroute": 0.3}
    },

    # 题 3：同一种解释听了三遍还没懂 —— agency
    # A 换一个 AI 继续 = 协同驱动，自己驾驶但需要外部导航，给 1.0
    # B 要代码自己跑 = 纯自驱，给 1.0
    # C 退回去问缺什么前置 = 自驱诊断，和 B 同为自驱但稍逊（诊断 vs 行动），给 0.8
    # D 跳过 = 纯外部牵引，等将来再说，给 1.0
    "q3": {
        "A": {"collaborative": 1.0},
        "B": {"self_driven": 1.0},
        "C": {"self_driven": 0.8},
        "D": {"external": 1.0}
    },

    # 题 4：刚搞懂一个知识点 —— consolidation_style
    # A 找题验证 = 外炼固化，给 1.0
    # B 写笔记 = 内建重构，但比 C 浅一点（记录 vs 创造），给 0.7
    # C 挑战更难 = 内建重构最主动形态，给 1.0
    # D 够了合上 = 浅层收口，给 1.0
    "q4": {
        "A": {"cement": 1.0},
        "B": {"rebuild": 0.7},
        "C": {"rebuild": 1.0},
        "D": {"surface": 1.0}
    },

    # 题 5：遇到陌生术语 —— learning_style
    # 四个输入倾向互斥，全 1.0
    "q5": {
        "A": {"structure": 1.0},
        "B": {"analogy": 1.0},
        "C": {"demand": 1.0},
        "D": {"practice": 1.0}
    },

    # 题 6：发现前置知识有洞 —— blockage_response
    # A 退回去补完 = 纯粹回溯诊断，给 1.0
    # B 标记绕开 = 路径重选但几乎没有实际行动，给 0.4
    # C 交叉对照学 = 定点突破的创造性形式，给 1.0
    # D 问 AI 借力 = 路径重选，主动性强于 B 弱于 A/C，给 0.7
    "q6": {
        "A": {"diagnose": 1.0},
        "B": {"reroute": 0.4},
        "C": {"drill": 1.0},
        "D": {"reroute": 0.7}
    },

    # 题 7：面对大量陌生内容 —— learning_style
    # A 看大纲结构图 = 结构优先最典型形态，给 1.0
    # B 查文档抄定义 = 结构优先但偏死记，给 0.6
    # C 找核心问题串联 = 问题导向，给 1.0
    # D 直接跟作业做 = 实践优先，给 1.0
    "q7": {
        "A": {"structure": 1.0},
        "B": {"structure": 0.6},
        "C": {"demand": 1.0},
        "D": {"practice": 1.0}
    },

    # 题 8：学到一半情绪上来了 —— agency
    # A 果断止损运动去 = 最高理性自驱，给 1.0
    # B 硬刚到底 = 被当前计划拖着走，纯外部牵引，给 1.0
    # C 换小任务调剂 = 协同驱动——自己在驾驶但换了过渡动作，给 0.7
    # D 看科普/简化 = 外部牵引，但比 B 温和——主动降低认知负荷，给 0.5
    "q8": {
        "A": {"self_driven": 1.0},
        "B": {"external": 1.0},
        "C": {"collaborative": 0.7},
        "D": {"external": 0.5}
    },

    # 题 9：卡在难点很久 —— stress_tolerance（独立乘区）
    # A 死磕 = 最高压力耐受，给 1.0
    # B 平稳保持节奏 = 高耐受但没那么极端，给 0.7
    # C 标记卡点先撤退 = 低耐受但属于策略性撤退，给 0.6
    # D 想放弃换方向 = 纯崩溃，给 1.0
    "q9": {
        "A": {"stress_high": 1.0},
        "B": {"stress_high": 0.7},
        "C": {"stress_low": 0.6},
        "D": {"stress_low": 1.0}
    },

    # 题 10：怎么判断自己学会了 —— consolidation_style
    # A 解决一个之前不能的问题 = 外炼固化最标准形态，给 1.0
    # B 讲给完全不懂的人 = 内建重构，比 C 浅，给 0.7
    # C 回答为什么这样设计 = 内建重构最深层次，给 1.0
    # D 两周后不查资料还能写 = 外炼固化 + 时间检验，给 0.8
    "q10": {
        "A": {"cement": 1.0},
        "B": {"rebuild": 0.7},
        "C": {"rebuild": 1.0},
        "D": {"cement": 0.8}
    },

    # 题 11：两周前学的忘了 —— consolidation_style
    # A 重做当时的典型题 = 外炼固化，但依赖旧材料，给 0.7
    # B 合上书自己推导写出小结 = 内建重构最纯粹形态，给 1.0
    # C 忘了正常，能查到会用就行 = 纯浅层收口，给 1.0
    # D 找真实场景重新解释 = 外炼固化最高形态——迁移验证，给 1.0
    "q11": {
        "A": {"cement": 0.7},
        "B": {"rebuild": 1.0},
        "C": {"surface": 1.0},
        "D": {"cement": 1.0}
    }
}


# 风险信号：命中特定选项组合时打标签，但不改权重
RISK_RULES = {
    # q4 刚学就合上 + q11 忘了就重新问 = 一直停留在表面
    # 新标签: q4-D=surface, q11-C=surface
    "shallow_avoidance": {"conditions": [("q4", "D"), ("q11", "C")]},

    # q8 硬刚到底 + q2 报错跳过 = 虚假勤奋——用蛮力掩饰具体难点逃避
    # 新标签: q8-B=external:硬刚, q2-D=reroute:跳过
    "false_diligence": {"conditions": [("q8", "B"), ("q2", "D")]},

    # q11 选 C = 不重视长期记忆，每次忘掉都像第一次学
    # 新标签: q11-C=surface
    "zero_retention": {"conditions": [("q11", "C")]},

    # q6 选 B = 明知基础不牢还标记绕开，最高风险信号
    # 新标签: q6-B=reroute:绕开
    "active_avoidance": {"conditions": [("q6", "B")]},

    # q9 选 D + q8 选 D = 全面崩溃——卡住就放弃 + 情绪也投降
    # 新标签: q9-D=stress_low:放弃, q8-D=external:简化
    "full_collapse": {"conditions": [("q9", "D"), ("q8", "D")]},

    # q3 选 D + q8 选 B = 外部依赖循环——听不懂就跳过 + 情绪用蛮力硬刚
    # 新标签: q3-D=external:跳过, q8-B=external:硬刚
    "external_loop": {"conditions": [("q3", "D"), ("q8", "B")]}
}
