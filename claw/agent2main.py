import asyncio
import json
import os
from claw.Agent2.LLM_call import agent2, agent2b, agent2c, flash_client as agent2_client


skill_a_path = os.path.join(os.path.dirname(__file__), "Agent2", "duanadianzhenduan.md")
with open(skill_a_path, "r", encoding="utf-8") as f:
    skill_a_content = f.read()

skill_b_path = os.path.join(os.path.dirname(__file__), "Agent2", "youshishibie.md")
with open(skill_b_path, "r", encoding="utf-8") as f:
    skill_b_content = f.read()

skill_c_path = os.path.join(os.path.dirname(__file__), "Agent2", "zhishiliu.md")
with open(skill_c_path, "r", encoding="utf-8") as f:
    skill_c_content = f.read()


async def main():
    """
    Agent2 独立测试入口（三路拆分：2a 诊断 + 2b 优势 + 2c 知识流并发）。
    输入用户消息，构造 messages，分别调用 agent2() / agent2b() / agent2c()。
    """
    print("Claw Agent2 调试启动（2a 诊断 + 2b 优势 + 2c 知识流）")
    print("输入用户消息，按 q 退出")
    print("-" * 40)

    try:
        while True:
            print("请输入本轮用户输入：")
            current = input("本轮：").strip()
            if current.lower() == "q":
                print("退出")
                break

            # 构造 messages（三路都用同一份用户输入）
            agent2a_messages = [
                {"role": "system", "content": skill_a_content},
                {"role": "user", "content": f"用户输入：\n{current}\n\n请判断断点类型和子类。"}
            ]
            agent2b_messages = [
                {"role": "system", "content": skill_b_content},
                {"role": "user", "content": f"用户输入：\n{current}\n\n请识别优势。"}
            ]
            agent2c_messages = [
                {"role": "system", "content": skill_c_content},
                {"role": "user", "content": f"用户输入：\n{current}\n\n请提取知识流。"}
            ]

            print("正在诊断断点、识别优势和提取知识流...")
            diag_data, strengths_data, flow_data = await asyncio.gather(
                agent2(agent2a_messages),
                agent2b(agent2b_messages),
                agent2c(agent2c_messages)
            )

            if "error" in diag_data:
                print(f"Agent2a 调用失败：{diag_data['error']}")
                if "raw" in diag_data:
                    print(f"原始输出：{diag_data['raw']}")
            else:
                print("\n--- 解析后的断点诊断（Agent2a） ---")
                print(json.dumps(diag_data, ensure_ascii=False, indent=2))

            if "error" in strengths_data:
                print(f"Agent2b 调用失败：{strengths_data['error']}")
                if "raw" in strengths_data:
                    print(f"原始输出：{strengths_data['raw']}")
            else:
                print("\n--- 解析后的优势识别（Agent2b） ---")
                print(json.dumps(strengths_data, ensure_ascii=False, indent=2))

            if "error" in flow_data:
                print(f"Agent2c 调用失败：{flow_data['error']}")
                if "raw" in flow_data:
                    print(f"原始输出：{flow_data['raw']}")
            else:
                print("\n--- 解析后的知识流（Agent2c） ---")
                print(json.dumps(flow_data, ensure_ascii=False, indent=2))

            print("=" * 40 + "\n")

    finally:
        print("关闭 HTTP client...")
        await agent2_client.close()


if __name__ == "__main__":
    asyncio.run(main())
