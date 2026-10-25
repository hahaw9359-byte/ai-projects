import os
import json

from ..onboarding.LLMagent0 import Request_s
from ..onboarding.map import SCORING_MAP, RISK_RULES
from .profile_normalizer import normalize_profile
from ..onboarding.LLMagent_run import Request
acc = Request_s()
add = Request()

def main():
    topic = None
    content = None
    max_attempts = 3

    for attempt in range(max_attempts):
        query = input("请输入你需要学习的学科/领域（或输入 q 退出）：").strip()

        if query.lower() == "q":
            print("已退出程序")
            return

        if len(query) == 0:
            print("主题不能为空，请重新输入")
            continue

        topic = query
        print(f"请稍等，正在为你生成 {topic} 题目")
        题目 = acc.发送(topic)
        content = 题目["content"]
        print(content)

        # 简单熔断：判断 LLM 是否真的输出了题目
        if "Q1" not in content and "1." not in content and "1、" not in content:
            print("该领域无法生成有效题目，请换一个学科/领域试试")
            topic = None
            content = None
            continue

        break

    if topic is None or content is None:
        print("多次尝试失败，程序退出")
        return

    # 答案输入最多允许 3 次重试
    用户答案 = None
    for attempt in range(3):
        用户答案 = input("请输入你得答案").replace(" ", "").replace("\n", "").upper()
        if len(用户答案) == 11:
            break
        print("答案必须是 11 个字母（A/B/C/D），请重新输入")
    else:
        print("答案输入失败次数过多，程序退出")
        return

    print("根据你的答案计算你的学习画像")
    answers = {}
    for i, choice in enumerate(用户答案):
        answers[f"q{i+1}"] = choice

    raw_score = {}
    for qid in SCORING_MAP:
        choice = answers.get(qid)
        if not choice:
            continue
        selected = SCORING_MAP[qid][choice]
        for attr, score in selected.items():
            raw_score[attr] = raw_score.get(attr, 0) + score

    profile = normalize_profile(raw_score)
    profile["risks"] = []
    for risk_name, rule in RISK_RULES.items():
        conditions = rule["conditions"]
        all_match = True
        for qid, choice in conditions:
            if answers.get(qid) != choice:
                all_match = False
                break
        if all_match:
            profile["risks"].append(risk_name)
    LLM润色 = add.发送(profile)
    润色content = LLM润色["content"]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profile_path = os.path.join(base_dir, "profile.json")

    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"画像已保存到 {profile_path}")
    print(润色content)


if __name__ == "__main__":
    main()
