# Agent3 教学执行模块总结

> 更新日期：2026-08-12
> 状态：Agent3 已接入主链路，可正常运行，支持工具调用与对话历史维护
> 说明：v1 基础版——外部传入 messages，内部走 ReAct 闭环；工具固定为 tavily_search 与 read_plan

---

## 一、Agent3 定位

Agent3 是 Claw 系统的**教学执行者**，位于 Agent2.5（认知侦察兵）之后，直接面对学习者。

**核心职责**：接收 Agent2.5 的认知侦察 Markdown、用户当前输入和最近对话历史，生成最终教学回应。教学过程中如果需要外部信息或学习计划，可主动调用工具。

**设计原则**：
- 只接收 messages，不自己组装 skill 或 scout
- 教学闭环在 Agent3 内部完成，main.py 不干预思考过程
- 工具是能力的延伸，不是流程的必需步骤
- 不确定的知识主动查，不瞎编

---

## 二、输入与输出

### 2.1 输入

Agent3 接收三份材料：

1. **SKILL.md**（system prompt）：Agent3 的角色设定、教学原则、严禁事项
2. **Agent2.5 认知侦察 Markdown**（user prompt 的一部分）：本轮学习者状态分析
3. **用户输入 + 历史对话**（user/assistant messages）：当前问题和最近 1-N 轮上下文

#### messages 结构示例

```python
[
    {"role": "system", "content": "你是 AI 教师..."},
    {"role": "user", "content": "## 本轮认知侦察结果\n[Agent2.5 的 Markdown 分析]\n\n请基于以上侦察结果进行教学。"},
    {"role": "user", "content": "什么是闭包？"},
    {"role": "assistant", "content": "闭包就是函数记住外部变量..."},
    {"role": "user", "content": "那闭包和装饰器有什么关系？"}
]
```

### 2.2 输出

Agent3 输出两种形式：

| 形式 | 含义 |
|------|------|
| `{"content": "..."}` | 正常教学回应 |
| `{"error": "...", "detail": "..."}` | 调用失败或 LLM 返回空内容 |

### 2.3 持久化

对话历史保存到 `Agent3/data/dialogue_history.json`，格式为标准 messages 列表：

```json
[
  {"role": "user", "content": "什么是闭包？"},
  {"role": "assistant", "content": "闭包就是..."}
]
```

默认只保留最近 1 轮（`max_turns=1`），可通过参数调整。

---

## 三、代码实现

### 3.1 文件结构

```
claw/
├── Agent3/
│   ├── __init__.py
│   ├── SKILL.md               # Agent3 角色定义
│   ├── LLM_call.py            # ReAct 循环 + 工具调用
│   ├── main.py                # messages 组装 + 历史维护
│   ├── tools.py               # 工具注册表 + 工具实例初始化
│   ├── AGENT3_SUMMARY.md      # 本文件
│   └── data/
│       ├── plan.md            # 学习计划（read_plan 工具数据源）
│       └── dialogue_history.json  # 对话历史
├── shared/
│   ├── HTTT_llm.py            # 异步 LLM client
│   ├── tavily_client.py       # Tavily 搜索封装
│   ├── chunk_retriever.py     # RAG 热备封装
│   └── tik_token.py           # token 估算
├── agent3main.py              # Agent3 独立交互式测试入口
└── main.py                    # Claw 主入口：... → Agent2.5 → Agent3
```

### 3.2 Agent3/SKILL.md

定义 AI 教师的角色和工作方式。核心指令：

- 严谨：内容准确，不确定的不输出
- 合适：结合学习者状态，因材施教
- 高效：把知识点敲碎，让学习者自己吸收
- 严禁跳过简报、空洞鼓励、替学习者做他能自己做的事

### 3.3 Agent3/tools.py

```python
import os
from ..shared.tavily_client import TavilyClient
from ..shared.chunk_retriever import ChunkRetriever

# 工具实例占位符

tavily = None
retriever = None

# 调用注册表：name -> func
TOOL_REGISTRY = {}


def register_tool(name=None):
    def wrapper(func):
        TOOL_REGISTRY[name or func.__name__] = func
        return func
    return wrapper


@register_tool("tavily_search")
async def tavily_search(query: str):
    result = await tavily.search(query)
    ...


@register_tool("read_plan")
async def read_plan(query: str):
    result = await retriever.query(query)
    ...


# 给 LLM 看的 schema
TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "tavily_search", ...}},
    {"type": "function", "function": {"name": "read_plan", ...}}
]


def list_tools():
    return TOOLS_SCHEMA


async def init_tools():
    global tavily, retriever
    tavily = TavilyClient()
    retriever = ChunkRetriever(os.path.join(os.path.dirname(__file__), "data", "plan.md"))
    await retriever.warmup()
```

**设计要点**：
- 装饰器只注册函数，schema 单独写成 `TOOLS_SCHEMA`
- `init_tools()` 负责实例化 + 热备，由编排层在首次调用前触发
- `tavily` / `retriever` 用全局变量占位，解决 `__init__` 不能 `await` 的问题

### 3.4 Agent3/LLM_call.py

```python
import json
from ..shared.HTTT_llm import LLM_client
from .tools import TOOL_REGISTRY, list_tools

client = LLM_client(maxtoken=4000)


async def agent3(messages, max_rounds: int = 3):
    messages = list(messages)              # 防御性复制
    tools_schema = list_tools()

    response = await client.send(messages, tools=tools_schema)
    if "error" in response:
        return response

    for _ in range(max_rounds):
        content = response.get("content", "")
        tool_calls = response.get("tool_calls")

        if not tool_calls:
            if not content:
                return {"error": "empty_content", "detail": "LLM 返回空内容"}
            return {"content": content}

        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls
        })

        for tool_call in tool_calls:
            tool_result = await _run_tool(
                tool_call["function"]["name"],
                tool_call["function"]["arguments"]
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_call["function"]["name"],
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        response = await client.send(messages, tools=tools_schema)
        if "error" in response:
            return response

    # 轮次用完，强制最终回应
    final_response = await client.send(messages, tools=None)
    ...
    return {"content": final_content}
```

**设计要点**：
- `agent3(messages)` 只接收 messages，不在内部 load skill
- 内部复制 messages，避免污染外部列表
- 自己走 ReAct 闭环：LLM → tool_calls → 执行工具 → 再调 LLM
- 轮次用完强制最终回应（不带 tools）
- `_run_tool` 捕获所有异常，返回错误字典给 LLM

### 3.5 Agent3/main.py

```python
def build_messages(user_input: str, scout_markdown: str, history: list = None):
    if history is None:
        history = []

    skill = load_skill()
    messages = [
        {"role": "system", "content": skill},
        {"role": "user", "content": f"## 本轮认知侦察结果\n{scout_markdown}\n\n请基于以上侦察结果进行教学。"},
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages


async def run(user_input: str, scout_markdown: str, history: list = None):
    if tools.retriever is None:
        await init_tools()
    messages = build_messages(user_input, scout_markdown, history)
    return await agent3(messages)


async def run_with_history(user_input: str, scout_markdown: str, max_turns: int = 1):
    if tools.retriever is None:
        await init_tools()

    history = load_history(HISTORY_PATH, max_turns)
    messages = build_messages(user_input, scout_markdown, history)
    result = await agent3(messages)

    if "content" in result and "error" not in result:
        save_history(user_input, result["content"])

    return result
```

**设计要点**：
- `build_messages()` 把 system、scout、history、当前输入拼成标准 messages
- `run()` 是基础入口，`run_with_history()` 自动维护历史
- 通过 `tools.retriever is None` 判断是否需要热备，避免 `from .tools import retriever` 的引用陷阱

### 3.6 claw/agent3main.py

Agent3 独立交互式测试入口。

```bash
python -m claw.agent3main
```

启动后通过 `input()` 输入问题，自动维护历史，输入 `exit` 退出。

### 3.7 claw/main.py 中的位置

```
用户输入
  ↓
Agent1（情绪） + Agent2（断点） 并发
  ↓
Agent2.5（认知侦察） → scout markdown
  ↓
Agent3（教学执行） → 最终教学回应
```

---

## 四、运行方式

### 4.1 环境要求

- Python 3.13+
- 安装依赖：`httpx`, `python-dotenv`, `sentence-transformers`, `faiss-cpu`, `numpy`, `PyMuPDF`
- 项目根目录 `.env` 文件包含 `Deepseek_key` 和 `Tavily_key`

### 4.2 独立测试

```bash
cd "C:/Users/49523/复习/需求反推知识点"
python -m claw.agent3main
```

### 4.3 主链路测试

```bash
cd "C:/Users/49523/复习/需求反推知识点"
python -m claw.main
```

输入用户消息，Agent1 + Agent2 + Agent2.5 执行后自动进入 Agent3。

---

## 五、设计演进与关键认知

### 5.1 工具系统：装饰器 + 独立 schema

**最初想法**：用装饰器把函数和 schema 一起注册。  
**当前做法**：装饰器只注册函数，`TOOLS_SCHEMA` 单独写成列表。

**原因**：
- 函数注册表和 LLM payload schema 是两个东西
- 分开后 `execute_tool` 直接 `TOOL_REGISTRY[name](**args)`，更直观
- 规模小（2 个工具），不需要复杂注册表

### 5.2 messages 由外部传入

**最初想法**：Agent3 内部自己 load skill、自己组装 messages。  
**当前做法**：`agent3(messages)` 只接收外部 messages。

**原因**：
- Agent3 是执行层，不应该关心 skill 怎么来的
- 外部组装方便复用和调试
- 历史对话、scout 等上下文由 main.py 统一管理

### 5.3 ReAct 闭环在 Agent3 内部

**关键决策**：工具调用和后续教学生成必须在同一个 `agent3()` 调用内完成。

**原因**：
- Agent3 自己判断是否需要更多信息
- 如果拆到 main.py 每一轮重新调用，会丧失上下文连续性
- 工具只是扩展 Agent3 的能力，不是独立流程

### 5.4 全局变量引用陷阱

**现象**：每次调用 Agent3 都重新加载 sentence-transformers 模型。  
**根因**：`from .tools import retriever` 只复制了初始 `None`，`init_tools()` 重新赋值后 `main.py` 看不到。  
**处理**：改为 `from . import tools`，判断 `tools.retriever is None`。

### 5.5 模型选择：pro vs flash

**现象**：flash 频繁空转，`completion_token: 8000` 但 content 为空；pro 稳定。  
**结论**：当前复杂结构化输出任务固定使用 `deepseek-v4-pro`。  
**兜底**：Agent2 / Agent2.5 增加空 content 重试机制（最多 2 次）。

### 5.6 历史对话维护

**当前做法**：`dialogue_history.json` 保存全部历史，`load_history()` 只取最近 N 轮。  
**优点**：简单、可回溯。  
**缺点**：文件会无限增长，长期需要归档或定期清理。

---

## 六、当前状态（v1）

- [x] Agent3 prompt 设计完成
- [x] 工具系统设计（tavily_search + read_plan）
- [x] ChunkRetriever 热备
- [x] ReAct 闭环实现
- [x] 对话历史维护
- [x] 独立测试入口
- [x] 主链路接入
- [x] 模型固定为 deepseek-v4-pro
- [ ] read_plan 真实数据填充与测试
- [ ] tavily_search 在教学场景中的触发测试
- [ ] Agent3 SKILL.md 根据真实输出调优
- [ ] 历史文件归档策略

---

## 七、下一步

1. 填充 `Agent3/data/plan.md`，测试 read_plan 工具
2. 设计能触发 tavily_search 的测试用例
3. 跑端到端多轮对话，观察 Agent3 是否稳定使用工具
4. 根据输出质量回调优 SKILL.md

---

## 八、关键经验

1. **变量导入会复制值**：`from module import var` 不是引用，重新赋值后本层看不到
2. **复杂结构化输出不要用 flash**：便宜但空转率高，实际成本可能更高
3. **工具注册表和 schema 分开**：注册表给执行用，schema 给 LLM 看
4. **ReAct 闭环要在 Agent 内部完成**：保持上下文连续性
5. **防御性复制输入 messages**：避免副作用
6. **空 content 要重试兜底**：API 偶发不稳定时需要自愈能力
