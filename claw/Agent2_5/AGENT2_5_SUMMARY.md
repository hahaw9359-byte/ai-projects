# Agent2.5 认知侦察兵模块总结

> 更新日期：2026-08-11
> 状态：Agent2.5 已接入主链路，可正常运行，输出 Markdown 格式认知侦察结果
> 说明：v2 精简——砍掉回应正文/必要条件/绝对禁忌，增加画像输入；Agent 2.5 只做情报层，Agent 3 做执行层

---

## 一、Agent2.5 定位

Agent2.5 是 Claw 系统的**认知侦察兵**，位于 Agent1（情绪指纹）和 Agent2（断点诊断）之后，Agent3（教学执行）之前。

**核心职责**：接收 Agent1 的情绪指纹和 Agent2 的断点诊断，读懂学习者当前真正需要什么，输出可直接用于生成回应的 Markdown 分析。

**设计原则**：
- 不翻译字段，读字段之间的张力和矛盾
- 以行为/状态为准，不以用户言语为准
- 每个揣测必须有数据证据
- 不强行推测，数据不足时明确标注
- 输出 Markdown 格式，不做硬性 JSON 约束

---

## 二、输入与输出

### 2.1 输入

Agent2.5 接收三份数据：

1. **emotion_current.json**（来自 Agent1）：当前轮情绪指纹
2. **breakpoint_diagnosis.json**（来自 Agent2）：当前对话的断点诊断报告
3. **画像摘要**（来自 Profile 系统，可选）：学习者的长期偏好——学习风格权重、卡壳反应模式、巩固方式、主动性、压力耐受。格式化为简洁文本（~100 token）后注入。

#### 情绪指纹示例

```json
{
  "round_id": "r_42",
  "timestamp": "2026-07-29T16:05:41",
  "current_round": {
    "primary_emotion": "frustrated",
    "emotion_subtype": "anger",
    "intensity": 0.8,
    "objective_tag": "concept_gap",
    "confidence": 0.85,
    "triggers": ["transform 没例子", "讲了三遍还是不懂"],
    "tone_tags": ["急躁", "重复", "质问"]
  },
  "context_delta": {
    "emotion_trend": "worsening",
    "streak_rounds_blocked": 2,
    "repeated_phrases": ["听不懂", "为什么"],
    "repeated_concepts": ["transform"]
  }
}
```

#### 断点诊断示例

```json
{
  "diagnosis": {
    "primary": {
      "type": "前置缺失",
      "subtype": "概念前置",
      "confidence": 0.85
    },
    "secondary": null,
    "overlap": null
  },
  "strengths": {
    "confirmed_concepts": [{"concept": "变量赋值", "evidence": "用户能正确复述 x = 5 的含义"}],
    "effective_approaches": [],
    "stable_behaviors": []
  },
  "knowledge_flow": [
    {
      "node_id": 1,
      "concept": "变量赋值",
      "user_state": "通",
      "evidence": "用户能正确复述 x = 5 的含义",
      "transition": "→"
    },
    {
      "node_id": 2,
      "concept": "函数传参",
      "user_state": "卡",
      "evidence": "用户说 transform 没例子，听不懂",
      "transition": "✕",
      "suspected_cause": "用户缺少函数作为值的直觉，直接跳到 transform 的高级用法",
      "cause_confidence": 0.8
    }
  ],
  "diagnostic_reasoning": {
    "observed_signals": ["用户反复说听不懂", "用户问 transform 没例子"],
    "excluded_types": [
      {"type": "情绪阻断", "reason": "情绪虽然激烈，但用户仍在追问知识点"},
      {"type": "认知过载", "reason": "不是信息太多，而是缺前置概念"}
    ],
    "confirming_evidence": ["用户无法用自己的话解释 transform 的作用"],
    "attempted_interventions": ["AI 已尝试解释 transform 原理，但用户继续追问例子"],
    "key_node": "用户缺少函数作为值的前置概念，导致 transform 无法理解"
  },
  "resistance_signals": {
    "target": "教学方式",
    "behavior": "催促质疑AI",
    "match": "匹配"
  }
}
```

### 2.2 输出（v3 四段式）

Agent2.5 输出 Markdown 格式分析，包含四个段落——递进关系：揣测状态 → 定位断点 → 教学建议 → 用户模式：

| 段落 | 含义 | 给 Agent 3 的用途 |
|------|------|------------------|
| **揣测结论** | 想要什么 / 不想要什么 / 推测可能的动向 | 决定教学姿态：退阶/承接/暂停，预判用户反应 |
| **断点链条** | 从 Agent2a knowledge_flow 提取的通-卡-缺结构 | 定位知识缺口，决定从哪切入 |
| **教学方式推荐** | 切入角度 + 表达形式 + 教学姿态 | 直接可用的教学方案 |
| **用户习惯** | 画像中本轮相关的偏好模式 | 风格微调依据，了解卡壳反应和压力模式 |

**v2→v3 变化**：
- 「认知通道」拆分为「断点链条」「教学方式推荐」「用户习惯」三段——从抽象描述变为直接可用的决策依据
- 新增「推测可能的动向」子段落——给 Agent 3 预判能力

### 2.3 持久化

输出保存到 `Agent2_5/data/teaching_state.md`，格式为带时间戳的 Markdown 文件。

---

## 三、代码实现

### 3.1 文件结构

```
claw/
├── Agent2_5/
│   ├── __init__.py
│   ├── SKILL.md               # 认知侦察兵角色定义
│   ├── LLM_call.py            # 封装 Agent2.5 调用 + Markdown 输出处理
│   ├── main.py                # 入口：构造 messages，接收两份 JSON dict
│   ├── save_state.py          # 持久化 teaching_state.md
│   ├── README.md              # 模块使用说明
│   ├── AGENT2_5_SUMMARY.md    # 本文件
│   ├── data/                  # 运行时数据
│   │   ├── sample_emotion_current.json
│   │   ├── sample_breakpoint_diagnosis.json
│   │   └── teaching_state.md
│   └── tests/                 # 测试
│       ├── test_single.py
│       ├── test_harness.py
│       ├── test_cases.json
│       └── output/
├── shared/
│   ├── HTTT_llm.py            # 异步 LLM client
│   └── tik_token.py           # token 估算
├── agent2_5_main.py           # Agent2.5 独立测试入口
└── main.py                    # Claw 主入口：Agent1 + Agent2 并发 → Agent2.5
```

### 3.2 Agent2_5/SKILL.md

定义认知侦察兵的角色和工作方式。核心指令：

- 把数据当作一次呼吸的记录，不孤立看字段
- 寻找字段之间的张力、矛盾、背离
- 不翻译字段，揣测用户真正需要什么
- 每个结论必须有数据证据

### 3.3 Agent2_5/LLM_call.py

```python
from ..shared.HTTT_llm import LLM_client
from .save_state import save_state

client = LLM_client(maxtoken=8000)


async def agent2_5(messages):
    result = await client.send(messages)

    if "error" in result:
        return {"error": result["error"]}

    content = result.get("content", "")
    if not content:
        return {"error": "LLM 返回空内容"}

    save_state(content)
    return {
        "content": content,
        "prompt_token": result.get("prompt_token", 0),
        "completion_token": result.get("completion_token", 0)
    }
```

**设计要点**：
- `maxtoken=8000`：Markdown 输出比 JSON 更松散，5000 会被截断
- 返回原始 Markdown 字符串，不再做 JSON 解析
- 解析成功后调用 `save_state()` 持久化
- client 作为模块级变量，复用连接池

### 3.4 Agent2_5/main.py（v2：增加画像注入）

```python
import os
import json
from .LLM_call import agent2_5


SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


def _format_profile(profile_json):
    """将画像 JSON 格式化为简洁的文本摘要."""
    if not profile_json:
        return "画像数据暂不可用"
    lines = []
    category_names = {
        "learning_style": "学习风格",
        "blockage_response": "卡壳反应",
        "consolidation_style": "巩固方式",
        "agency": "主动性",
        "stress_tolerance": "压力耐受"
    }
    for category, weights in profile_json.items():
        if not weights:
            continue
        sorted_items = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        parts = [f"{k}:{v:.2f}" for k, v in sorted_items[:2]]
        name = category_names.get(category, category)
        lines.append(f"{name}：{' / '.join(parts)}")
    return "\n".join(lines)


def build_messages(emotion_json, breakpoint_json, profile_json=None):
    skill = load_skill()
    profile_text = _format_profile(profile_json)
    user_content = f"""请根据以下数据进行认知侦察...

## 输入 1：Agent1 情绪指纹
```json
{json.dumps(emotion_json, ensure_ascii=False, indent=2)}
```

## 输入 2：Agent2 断点诊断
```json
{json.dumps(breakpoint_json, ensure_ascii=False, indent=2)}
```

## 输入 3：画像摘要（学习者的长期偏好）
{profile_text}
"""
    return [
        {"role": "system", "content": skill},
        {"role": "user", "content": user_content}
    ]


async def run(emotion_json, breakpoint_json, profile_json=None):
    messages = build_messages(emotion_json, breakpoint_json, profile_json)
    return await agent2_5(messages)
```

**v2 关键变化**：
- `_format_profile()` 将画像 JSON 转为 ~100 token 的简洁文本摘要
- `build_messages()` 增加第三个可选参数 `profile_json`
- `run()` 和 `run_from_files()` 均支持画像传入
- user prompt 增加「输入 3：画像摘要」段落

### 3.5 Agent2_5/save_state.py

```python
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def save_state(content):
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now().isoformat()

    current = f"""---
timestamp: {now}
---

{content}
"""
    with open(f"{DATA_DIR}/teaching_state.md", "w", encoding="utf-8") as f:
        f.write(current)
```

### 3.6 claw/agent2_5_main.py

Agent2.5 独立测试入口，读取 `data/sample_emotion_current.json` 和 `data/sample_breakpoint_diagnosis.json`。

```bash
python -m claw.agent2_5_main
```

### 3.7 claw/main.py 中的位置

```
用户输入
  ↓
Agent1（情绪） + Agent2（断点） 并发
  ↓
Agent2.5（认知侦察）
  ↓
输出 Markdown 分析结果
```

---

## 四、运行方式

### 4.1 环境要求

- Python 3.13+
- 安装依赖：`httpx`, `python-dotenv`
- 项目根目录 `.env` 文件包含 `Deepseek_key`

### 4.2 独立测试

```bash
cd "C:/Users/49523/复习/需求反推知识点"
python -m claw.agent2_5_main
```

按回车运行，按 `q` 退出。

### 4.3 主链路测试

```bash
cd "C:/Users/49523/复习/需求反推知识点"
python -m claw.main
```

输入用户消息，Agent1 + Agent2 并发执行后自动进入 Agent2.5。

### 4.4 批量测试

```bash
cd "C:/Users/49523/复习/需求反推知识点"
python -m claw.Agent2_5.tests.test_harness
```

结果保存到 `Agent2_5/tests/output/`。

---

## 五、设计演进与关键认知

### 5.1 v3：四段式输出（2026-08-11）

**变化**：「认知通道」拆分为「断点链条」「教学方式推荐」「用户习惯」三段。揣测结论新增「推测可能的动向」。

**原因**：
- 「认知通道」太抽象——"他的学习发生在操作验证中"这种描述 Agent 3 不知道怎么用。拆成"断点在哪→该怎么教→他有什么习惯"三段后，Agent 3 拿到的是直接可用的决策依据。
- 「推测可能的动向」给 Agent 3 预判能力——如果按当前方向回应，他大概率会追问？跳过？接受？Agent 3 可以据此准备退路或追问钩子。

**新结构**：揣测结论（什么状态）→ 断点链条（卡在哪）→ 教学方式推荐（怎么教）→ 用户习惯（他的模式）

### 5.2 v2：砍三段输出 + 接入画像（2026-08-11）

**变化**：删除回应正文、回应的必要条件、绝对禁忌三个段落。增加画像作为第三输入。

**原因**：
- **回应正文**会让 Agent 3 产生锚定效应——拿到成品文本后自然偏向"校对"而非"生成"，Agent 3 被架空
- **必要条件/绝对禁忌**形式太绝对——2.5 说"禁止问X"是在替 Agent 3 做决策。正确做法是 2.5 在认知通道里说"用户当前无法处理需要内省的问题"，Agent 3 自己推导该避免什么
- **画像接入 2.5**——画像回答的是"这个人一般怎么学"，和"这轮该怎么教"是同一层次的决策。放在 2.5 里统一判断，Agent 3 不需要再纠结权重

**新定位**：Agent 2.5 = 情报层（输出 WHY），Agent 3 = 执行层（推导 WHAT）。传递情报，不传递指令。

### 5.2 从 JSON 到 Markdown 的输出格式变化

**最初设计**：Agent2.5 输出结构化 JSON，定义 `state`、`action`、`agent3_prompt` 等字段，Agent3 直接读取。

**变化原因**：
- Agent2.5 的核心是"读懂一个人"，更适合自由文本表达
- Markdown 能承载揣测、证据、回应正文、禁忌清单等复杂信息
- Agent3 需要的是"侦察结论"，而不是被提前约束的状态标签

**当前状态**：输出 Markdown，Agent3 负责解析并生成最终回应。

### 5.3 maxtoken 从 5000 调到 8000 的问题

**现象**：Agent2.5 调用时 `completion_token` 接近 5000，content 为空，报 "LLM 返回空内容"。

**根因**：`LLM_client()` 默认 `maxtoken=5000`。Markdown 输出比 JSON 更松散，容易超过 5000 token 上限，导致输出被截断，content 为空。

**处理**：`Agent2_5/LLM_call.py` 中显式设置为 `LLM_client(maxtoken=8000)`。

**关键认知**：
- 不能假设一种输出格式需要的 token 和另一种相同
- Markdown 自由文本的 token 消耗通常高于等效 JSON
- 出现 `completion_token` 接近 `maxtoken` 且 content 为空，优先怀疑截断

### 5.4 Agent2 也遇到同样的 maxtoken 问题

**现象**：`python -m claw.main` 中 Agent2 报 `json解析失败`，单独跑 `agent2main` 正常。

**根因**：`Agent2/LLM_call.py` 的 `maxtoken` 被设为 2000，Agent2 输出复杂 JSON 时不够用。

**处理**：`Agent2/LLM_call.py` 的 `maxtoken` 改为 8000。

### 5.5 Agent2.5 在 Claw 主链路中的位置

Agent2.5 不是替代 Agent1 或 Agent2，而是**站在两者之上做融合判断**。

| Agent | 职责 | 输出 |
|-------|------|------|
| Agent1 | 读当前轮情绪 | emotion_current.json |
| Agent2 | 读断点和知识流 | breakpoint_diagnosis.json |
| Agent2.5 | 读懂人，给 Agent3 提供回应依据 | teaching_state.md |
| Agent3 | 生成最终教学回应 | 待实现 |

### 5.6 当前已发现的缺陷

**Agent2.5 缺少明确的知识点教学指向**。

它有情绪和断点数据，也能分析状态，但输出里没有"该讲什么知识点、用什么方式讲、补什么前置"的明确指导。这会让下游 Agent3 缺少可直接参考的教学抓手。

**暂定解决方案**：后续在 Agent2.5 输出中增加「教学建议」或「知识点处理方向」板块，或作为结构化字段传给 Agent3。

---

## 六、当前状态（v3）

- [x] Agent2.5 prompt 设计完成（v3 四段式：揣测结论/断点链条/教学方式推荐/用户习惯）
- [x] v3 输出：认知通道拆分为断点链条+教学方式推荐+用户习惯；揣测结论新增推测动向
- [x] 画像注入：`main.py` + `claw/main.py`
- [x] 调用封装（V4 Flash 0731, maxtoken=8000）
- [x] 独立测试 + 批量测试
- [x] 主链路接入
- [ ] Agent3 对接（接收四段情报，生成回应）
- [ ] 端到端集成测试

---

## 七、下一步

1. 推进 Agent3：接收 2.5 的四段情报，生成最终教学回应
2. Agent3 稳定后，根据联调反馈回调优 2.5
3. 根据真实测试反馈迭代 `SKILL.md` 和 `main.py`

---

## 八、关键经验

1. **输出格式影响 token 需求**：Markdown 自由文本比 JSON 更耗 token，不能沿用同一 maxtoken
2. **截断的典型症状**：`completion_token` 接近 `maxtoken` 且 content 为空
3. **模块职责分层**：Agent2.5 只做"读懂"，不做"回应生成"，边界清晰
4. **数据驱动迭代**：先跑通链路，再优化细节，比一开始就穷举组合更有效
5. **调试时不要污染调用层**：临时调试代码要确保不引入新的异常（如遗漏 import）
6. **Agent2.5 的当前短板**：有状态分析，但缺知识点教学方向，需要后续补齐
