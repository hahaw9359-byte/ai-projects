# Agent2 总结

> 更新日期：2026-08-06
> 状态：已跑通，可独立运行并输出断点诊断
> 说明：Agent2 负责断点诊断，只接收外部构造好的 messages，输出结构化 JSON

---

## 一、职责边界

Agent2 是**学习断点诊断器**。输入是最近 3 轮用户输入，输出是结构化的断点诊断报告。

只做一件事：**判断用户当前学习状态出现了哪种断点**。

不输出教学策略，不把脉，不替 Agent2.5/Agent3 做决策。

---

## 二、目录结构

```
claw/
├── Agent2/
│   ├── __init__.py
│   ├── duanadianzhenduan.md    # Agent2 skill prompt
│   ├── LLM_call.py              # 封装 Agent2 调用
│   ├── save_and_trend.py        # 持久化当前状态 + 最近 3 轮
│   ├── data/                    # 输出数据
│   │   ├── breakpoint_current.json
│   │   └── breakpoint_recent.json
│   └── AGENT2_SUMMARY.md        # 本文件
├── shared/
│   ├── HTTT_llm.py              # 异步 LLM client
│   ├── context_store.py         # 用户输入历史
│   └── tik_token.py             # token 估算
├── agent2main.py                # Agent2 独立测试入口
└── main.py                      # 总入口：并发 Agent1 + Agent2
```

---

## 三、核心文件说明

### 3.1 Agent2/duanadianzhenduan.md

断点诊断 skill prompt。

- 按**三段式排除法**执行：提取信号 → 逐一排除 → 综合判断
- 输出 7 种断点类型：情绪阻断 / 认知过载 / 前置缺失 / 讲法不对口 / 多义混淆 / 假性掌握 / 无断点
- 输出结构：diagnosis / strengths / knowledge_flow / diagnostic_reasoning / resistance_signals

### 3.2 Agent2/LLM_call.py

```python
from ..shared.HTTT_llm import LLM_client
import json
import re
from .save_and_trend import save_and_trend

client = LLM_client()

async def agent2(messages):
    result = await client.send(messages)
    # ... 错误处理、markdown 清洗、json 解析、持久化
    return parsed_json
```

**设计要点**：
- `messages` 完全由**外部调用层**构造，Agent2 不自己读 skill 或拼 prompt
- 内部只做：调用 LLM → 清洗 markdown → 解析 JSON → 保存文件
- 返回解析后的 dict

### 3.3 Agent2/save_and_trend.py

```python
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def save_and_trend(breakpoint_data):
    # 1. breakpoint_current.json：当前轮状态（给 Agent2.5 用）
    # 2. breakpoint_recent.json：最近 3 轮历史
```

### 3.4 main.py 中的调用方式

```python
from claw.Agent1.LLM_call import agent1, client as agent1_client
from claw.Agent2.LLM_call import agent2, client as agent2_client
from claw.shared.context_store import append_user_input, get_recent_user_inputs

append_user_input(query)
recent_queries = get_recent_user_inputs(3)

context = "\n\n".join(
    [f"第 {i+1} 轮：{q}" for i, q in enumerate(recent_queries)]
)

messages = [
    {"role": "system", "content": skill_content},
    {"role": "user", "content": f"最近三轮用户输入：\n{context}\n\n请输出断点诊断 JSON。"}
]

emotion_data, breakpoint_data = await asyncio.gather(
    agent1(query),
    agent2(messages)
)
```

---

## 四、运行方式

### 独立测试

```bash
python -m claw.agent2main
```

手动输入最近 3 轮 + 本轮用户输入。

### 并发测试（Agent1 + Agent2）

```bash
python -m claw.main
```

输入用户消息，自动记录历史并并发分析情绪和断点。

---

## 五、输出文件

### breakpoint_current.json

当前轮的完整断点诊断，Agent2.5 读取这个文件做策略匹配。

### breakpoint_recent.json

数组，最多保留最近 3 轮断点诊断。用于趋势分析和调试。

---

## 六、当前状态

- [x] Agent2 skill prompt 设计完成
- [x] Agent2 调用封装完成
- [x] 断点诊断 JSON 输出完成
- [x] 当前状态 + 历史记录持久化完成
- [x] 独立测试入口完成
- [x] 与 Agent1 并发调用验证完成
- [ ] 接入 Agent2.5 做交叉策略匹配
- [ ] Agent3 拿策略包生成教学回复

---

## 七、关键经验

1. **messages 外部传入**：Agent2 不自己拼 prompt，调用层负责构造完整 messages，更灵活。
2. **并发调用**：Agent1 和 Agent2 用 `asyncio.gather()` 并行执行，最后统一关闭两个 client。
3. **断点诊断 skill 很重**：输出 JSON 结构复杂，需要模型有较强的遵循指令能力。
4. **上下文只给 3 轮用户输入**：不塞 AI 回复，用户输入本身就是反馈信号。
