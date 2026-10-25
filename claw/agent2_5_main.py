import asyncio
import json
import os

from claw.Agent2_5.LLM_call import agent2_5, client as agent2_5_client
from claw.Agent2_5.main import build_messages
from claw.shared.round_store import write_emotion, write_breakpoint


async def main():
    """
    Agent2.5 独立测试入口。
    读取 sample_emotion_current.json 和 sample_breakpoint_diagnosis.json，
    调用 agent2_5() 输出认知侦察结果。
    """
    print("Claw Agent2.5 调试启动")
    print("按 q 退出")
    print("-" * 40)

    base_dir = os.path.dirname(__file__)
    emotion_path = os.path.join(base_dir, "Agent2_5", "data", "sample_emotion_current.json")
    breakpoint_path = os.path.join(base_dir, "Agent2_5", "data", "sample_breakpoint_diagnosis.json")

    try:
        while True:
            query = input("按回车运行，或输入 q 退出：").strip()
            if query.lower() == "q":
                print("退出")
                break

            if not os.path.exists(emotion_path):
                print(f"情绪指纹文件不存在：{emotion_path}")
                continue
            if not os.path.exists(breakpoint_path):
                print(f"断点诊断文件不存在：{breakpoint_path}")
                continue

            with open(emotion_path, "r", encoding="utf-8") as f:
                emotion_json = json.load(f)
            with open(breakpoint_path, "r", encoding="utf-8") as f:
                breakpoint_json = json.load(f)

            # 先把 sample 数据写进 round_store，再让 2.5 从文件读当前层
            write_emotion(emotion_json)
            write_breakpoint(breakpoint_json)

            messages = build_messages()

            print("正在进行认知侦察...")
            result = await agent2_5(messages)

            if "error" in result:
                print(f"调用失败：{result['error']}")
                if "raw" in result:
                    print(f"原始输出：{result['raw']}")
                continue

            print(f"\nprompt_token: {result.get('prompt_token', 0)}")
            print(f"completion_token: {result.get('completion_token', 0)}")
            print("\n--- 认知侦察结果 ---")
            print(result.get("content", ""))
            print("=" * 40 + "\n")

    finally:
        print("关闭 HTTP client...")
        await agent2_5_client.close()


if __name__ == "__main__":
    asyncio.run(main())
