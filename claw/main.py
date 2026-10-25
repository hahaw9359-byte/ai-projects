import asyncio
import json
import os
import time

from claw.Agent1.LLM_call import agent1, client as agent1_client
from claw.Agent2.LLM_call import agent2, agent2b, agent2c, flash_client as agent2_client, flash_client_2c
from claw.Agent2_5.LLM_call import agent2_5, client as agent2_5_client
from claw.Agent2_5.main import build_messages as build_agent2_5_messages
from claw.Agent3.main import run_with_history
from claw.Agent3.LLM_call import client as agent3_client
from claw.shared.context_store import append_user_input
from claw.shared.round_store import write_breakpoint


agent1_skill_path = os.path.join(os.path.dirname(__file__), "Agent1", "qingxuzhiwen.md")
with open(agent1_skill_path, "r", encoding="utf-8") as f:
    agent1_skill_content = f.read()

agent2a_skill_path = os.path.join(os.path.dirname(__file__), "Agent2", "duanadianzhenduan.md")
with open(agent2a_skill_path, "r", encoding="utf-8") as f:
    agent2a_skill_content = f.read()

agent2b_skill_path = os.path.join(os.path.dirname(__file__), "Agent2", "youshishibie.md")
with open(agent2b_skill_path, "r", encoding="utf-8") as f:
    agent2b_skill_content = f.read()

agent2c_skill_path = os.path.join(os.path.dirname(__file__), "Agent2", "zhishiliu.md")
with open(agent2c_skill_path, "r", encoding="utf-8") as f:
    agent2c_skill_content = f.read()

# 加载画像（如果存在）
profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profile.json")
if os.path.exists(profile_path):
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                profile_data = json.loads(content)
    except (json.JSONDecodeError, OSError):
        profile_data = None
    if profile_data:
        print(f"已加载画像：{profile_path}")
    else:
        print(f"画像文件为空或损坏，Agent2.5 将在无画像模式下运行：{profile_path}")
else:
    print("未找到画像文件，Agent2.5 将在无画像模式下运行")


async def _timed(name, coro):
    """给一个协程计时，返回结果并打印耗时。"""
    start = time.time()
    result = await coro
    elapsed = time.time() - start
    print(f"[耗时] {name}: {elapsed:.1f}s")
    return result


async def main():
    """
    Claw 主入口。
    并发调用 Agent1（情绪）、Agent2a（断点诊断）、Agent2b（优势识别），
    合并 Agent2a + Agent2b 输出后送入 Agent2.5（认知侦察）。
    """
    print("Claw 主入口启动")
    print("输入用户消息，按 q 退出")
    print("-" * 40)

    try:
        while True:
            # 1. 读取用户输入（一行 = 一个回合）
            query = input("用户：").strip()

            # 2. 退出条件
            if query.lower() == "q":
                print("退出")
                break

            # 3. 记录用户输入（业务层来做，不是 Agent1 的职责）
            append_user_input(query)

            # 4. 构造 Agent1 的 messages（只包含当前 query）
            agent1_messages = [
                {"role": "system", "content": agent1_skill_content},
                {"role": "user", "content": f"用户输入：{query}"}
            ]

            # 5. 构造 Agent2a / Agent2b / Agent2c 的 messages（只分析本轮用户输入）
            agent2a_messages = [
                {"role": "system", "content": agent2a_skill_content},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请判断断点类型和子类。"}
            ]

            agent2b_messages = [
                {"role": "system", "content": agent2b_skill_content},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请识别优势。"}
            ]

            agent2c_messages = [
                {"role": "system", "content": agent2c_skill_content},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请提取知识流。"}
            ]

            # 6. 并发调用 Agent1 / Agent2a / Agent2b / Agent2c
            print("正在分析情绪、断点、优势和知识流...")
            try:
                emotion_data, diag_data, strengths_data, flow_data = await asyncio.gather(
                    _timed("Agent1 情绪", agent1(agent1_messages)),
                    _timed("Agent2a 诊断", agent2(agent2a_messages)),
                    _timed("Agent2b 优势", agent2b(agent2b_messages)),
                    _timed("Agent2c 知识流", agent2c(agent2c_messages))
                )
            except Exception as e:
                print(f"并发调用异常：{e}")
                continue

            # 7. 打印 Agent1 结果
            if "error" in emotion_data:
                print(f"Agent1 调用失败：{emotion_data['error']}")
                if "raw" in emotion_data:
                    print(f"原始输出：{emotion_data['raw']}")
            else:
                print("\n--- 解析后的情绪指纹 ---")
                print(json.dumps(emotion_data, ensure_ascii=False, indent=2))
                print("=" * 40)

            # 8. 打印 Agent2a（断点诊断）结果
            if "error" in diag_data:
                print(f"Agent2a 调用失败：{diag_data['error']}")
                if "raw" in diag_data:
                    print(f"原始输出：{diag_data['raw']}")
            else:
                print("\n--- 解析后的断点诊断（Agent2a） ---")
                print(json.dumps(diag_data, ensure_ascii=False, indent=2))
                print("=" * 40)

            # 9. 打印 Agent2b（优势识别）结果
            if "error" in strengths_data:
                print(f"Agent2b 调用失败：{strengths_data['error']}")
                if "raw" in strengths_data:
                    print(f"原始输出：{strengths_data['raw']}")
            else:
                print("\n--- 解析后的优势识别（Agent2b） ---")
                print(json.dumps(strengths_data, ensure_ascii=False, indent=2))
                print("=" * 40)

            # 10. 打印 Agent2c（知识流）结果
            if "error" in flow_data:
                print(f"Agent2c 调用失败：{flow_data['error']}")
                if "raw" in flow_data:
                    print(f"原始输出：{flow_data['raw']}")
            else:
                print("\n--- 解析后的知识流（Agent2c） ---")
                print(json.dumps(flow_data, ensure_ascii=False, indent=2))
                print("=" * 40)

            # 11. 合并 Agent2a + Agent2b + Agent2c 输出，还原完整断点诊断结构
            breakpoint_data = {}
            if "error" not in diag_data:
                breakpoint_data.update(diag_data)
            if "error" not in strengths_data:
                breakpoint_data.update(strengths_data)
            if "error" not in flow_data:
                breakpoint_data.update(flow_data)

            # 写断点到统一轮次记录（情绪由 Agent1 内部写，指导由 Agent2.5 内部写）
            if breakpoint_data:
                write_breakpoint(breakpoint_data)

            # 12. Agent1 和 Agent2（至少一个分支）成功后，送入 Agent2.5
            if "error" not in emotion_data and breakpoint_data:
                print("\n正在进行认知侦察...")
                agent2_5_messages = build_agent2_5_messages(profile_data)
                scout_result = await _timed("Agent2.5 侦察", agent2_5(agent2_5_messages))

                if "error" in scout_result:
                    print(f"Agent2.5 调用失败：{scout_result['error']}")
                    if "raw" in scout_result:
                        print(f"原始输出：{scout_result['raw']}")
                else:
                    print(f"\nprompt_token: {scout_result.get('prompt_token', 0)}")
                    print(f"completion_token: {scout_result.get('completion_token', 0)}")
                    print("\n--- 认知侦察结果 ---")
                    scout_guidance = scout_result.get("content", "")
                    print(scout_guidance)
                    print("=" * 40 + "\n")

                    # 13. Agent3 教学执行
                    print("正在生成教学回应...")
                    agent3_result = await _timed("Agent3 教学", run_with_history(query, scout_guidance, max_turns=2))

                    if "error" in agent3_result:
                        print(f"Agent3 调用失败：{agent3_result['error']}")
                        if "raw" in agent3_result:
                            print(f"原始输出：{agent3_result['raw']}")
                    else:
                        print("\n--- Agent3 教学回应 ---")
                        print(agent3_result.get("content", ""))
                        print("=" * 40 + "\n")
            else:
                print("\n跳过 Agent2.5：Agent1 或 Agent2a/2b 调用失败。\n")

    except Exception as e:
        print(f"主循环异常：{e}")
        import traceback
        traceback.print_exc()
    finally:
        print("关闭 HTTP client...")
        await agent1_client.close()
        await agent2_client.close()
        await flash_client_2c.close()
        await agent2_5_client.close()
        await agent3_client.close()


if __name__ == "__main__":
    asyncio.run(main())
