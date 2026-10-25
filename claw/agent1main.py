import asyncio
import json
import os
from claw.Agent1.LLM_call import agent1, client


skill_path = os.path.join(os.path.dirname(__file__), "Agent1", "qingxuzhiwen.md")
with open(skill_path, "r", encoding="utf-8") as f:
    skill_content = f.read()


async def main():
    """
    异步主函数。所有涉及 LLM 调用的操作都必须放在 async 函数里。
    """
    print("Claw Agent1 调试启动")
    print("输入用户消息，按 q 退出")
    print("-" * 40)

    try:
        while True:
            # 1. 读取用户输入
            query = input("用户：").strip()

            # 2. 退出条件
            if query.lower() == "q":
                print("退出")
                break

            # 3. 构造 messages
            messages = [
                {"role": "system", "content": skill_content},
                {"role": "user", "content": f"用户输入{query}"}
            ]

            # 4. 调用 Agent1（必须 await）
            print("正在分析情绪...")
            emotion_data = await agent1(messages)

            # 4. 检查是否报错
            if "error" in emotion_data:
                print(f"调用失败：{emotion_data['error']}")
                if "raw" in emotion_data:
                    print(f"原始输出：{emotion_data['raw']}")
                continue

            # 5. 打印格式化后的情绪指纹
            print("\n--- 解析后的情绪指纹 ---")
            print(json.dumps(emotion_data, ensure_ascii=False, indent=2))
            print("=" * 40 + "\n")
    finally:
        print("关闭 HTTP client...")
        await client.close()


if __name__ == "__main__":
    """
    程序入口。
    asyncio.run(main()) 会启动事件循环并运行 main()。
    """
    asyncio.run(main())
