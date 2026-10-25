import asyncio
import os

from claw.Agent3.main import run_with_history
from claw.Agent3.tools import init_tools


SCOUT_PATH = os.path.join(os.path.dirname(__file__), "Agent3", "data", "scout.md")


def load_default_scout():
    """加载默认 scout，文件不存在时返回内置 scout。"""
    if os.path.exists(SCOUT_PATH):
        with open(SCOUT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return """## 揣测结论
- 他此刻真正想要的是：把新知识和旧知识连起来
- 他此刻真正不想要的是：孤立地讲语法
- 推测可能的动向：希望看到知识之间的演进路径

## 认知通道
- 通过结构关联理解
- 排斥跳跃式讲解
- 需要知识地图"""


async def main():
    """
    Agent3 交互式测试入口。

    用法：
        python -m claw.agent3main

    启动后输入问题，按回车发送。输入 exit 或 quit 退出。
    """
    print("正在初始化工具...")
    await init_tools()
    print("工具初始化完成\n")

    scout = load_default_scout()

    while True:
        user_input = input("你：").strip()

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "退出"):
            print("已退出")
            break

        print("\nAgent3 思考中...")
        result = await run_with_history(user_input, scout, max_turns=1)

        if "error" in result:
            print(f"调用失败：{result}\n")
            continue

        print(f"Agent3：{result.get('content', '')}\n")


if __name__ == "__main__":
    asyncio.run(main())
