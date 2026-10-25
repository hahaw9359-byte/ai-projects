"""行为脑：才艺模块（可切换）的契约 + 主控。"""
from performance.skill import Skill            # 基类先加载，brain 依赖它
from performance.brain import PerformBrain
from performance.skills.sell import SellSkill

__all__ = ["Skill", "PerformBrain", "SellSkill"]
