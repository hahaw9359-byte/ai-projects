# Agent1 情绪指纹模块设计文档

> 本文档记录 Agent1（情绪指纹）模块的文件结构、数据流、JSON Schema 与硬编码规则。
> 位置：`claw/Aegnt1/README.md`

---

## 一、模块定位

Agent1 只做一件事：**根据用户当前输入，生成当前轮情绪指纹**。

- 不做跨轮总结（交给硬编码规则）
- 不做教学决策（交给 Agent3）
- 不进画像更新（情绪是短期信号，不污染画像）

Agent1 与 `portrait/`（初始化流程）平级，互不依赖。

### Agent1 与画像的关系

- Agent1 **读取** `profile.json`：把用户长期画像作为判断情绪的背景信息喂给 LLM。
- Agent1 **不更新** `profile.json`：情绪是短期波动，不进画像。
- 画像更新由独立模块负责：当 `data/pending_tags.json` 满 50 条时，基于标签重新计算画像权重。

所以 Agent1 的输入里包含画像，但输出里只有情绪指纹。

---

## 二、目录结构

```
claw/
├── data/                         # 运行时数据
│   ├── emotion_current.json      # Agent1 → Agent3 的当前情绪指纹（1份，覆盖写）
│   └── emotion_history.json      # Agent1 自用历史（保留最近3版）
├── onboarding/                   # 初始化模块
├── portrait/                     # 初始化主流程
└── Aegnt1/                       # 情绪指纹模块
    ├── __init__.py
    ├── README.md                 # 本文件
    ├── main.py                   # Agent1 主流程
    ├── llm_call.py               # 调用 LLM 生成 current_round
    ├── context_delta.py          # 硬编码对比规则
    └── history_manager.py        # 历史文件读写
```

---

## 三、数据流

```
用户当前输入
    ↓
llm_call.py（LLM）生成 current_round 情绪语义
    ↓
history_manager.py 读取 emotion_history.json
    ↓
context_delta.py 计算趋势 / 重复 / streak
    ↓
合并为完整情绪指纹
    ↓
├─→ 覆盖写入 data/emotion_current.json（给 Agent3）
└─→ 滑动窗口写入 data/emotion_history.json（Agent1 自用）
```

---

## 四、JSON Schema

### 4.1 emotion_current.json（给 Agent3）

只保留**当前轮** + 硬编码派生的 `context_delta`。

```json
{
  "round_id": "r_42",
  "timestamp": "2026-07-29T16:05:41",
  "current_round": {
    "primary_emotion": "frustrated",
    "intensity": 0.7,
    "objective_tag": "concept_gap",
    "confidence": 0.85,
    "triggers": ["transform 没例子"],
    "tone_tags": ["疲惫", "重复"]
  },
  "context_delta": {
    "emotion_trend": "worsening",
    "streak_rounds_blocked": 2,
    "repeated_phrases": ["听不懂"],
    "repeated_concepts": ["transform"]
  }
}
```

### 4.2 emotion_history.json（Agent1 自用）

保留最近 3 版完整指纹，头部插入，尾部淘汰。

```json
{
  "max_versions": 3,
  "history": [
    { "round_id": "r_42", "timestamp": "...", "current_round": {...}, "context_delta": {...} },
    { "round_id": "r_41", "timestamp": "...", "current_round": {...}, "context_delta": {...} },
    { "round_id": "r_40", "timestamp": "...", "current_round": {...}, "context_delta": {...} }
  ]
}
```

---

## 五、字段枚举

### 5.1 primary_emotion（主观情绪）

LLM 从以下选项中选择：

```python
PRIMARY_EMOTIONS = [
    "frustrated",    # 沮丧
    "confused",      # 困惑
    "neutral",       # 平静
    "curious",       # 好奇
    "confident",     # 自信
    "anxious",       # 焦虑
    "bored"          # 无聊
]
```

### 5.2 objective_tag（客观归因）

LLM 从以下选项中选择，用于帮助 Agent3 做教学决策：

```python
OBJECTIVE_TAGS = [
    "concept_gap",          # 概念没懂
    "too_fast",             # 节奏太快
    "too_slow",             # 节奏太慢
    "example_needed",       # 需要例子
    "practice_needed",      # 需要练习
    "unclear_question",     # 问题本身不清楚
    "external_distraction", # 外部干扰
    "confidence_drop",      # 自信心下降
    "unknown"               # 无法判断
]
```

### 5.3 emotion_trend（情绪趋势）

硬编码计算，基于最近 3 轮 `intensity`：

```python
EMOTION_TRENDS = [
    "improving",    # 变好
    "worsening",    # 变坏
    "stable"        # 持平
]
```

---

## 六、硬编码规则（context_delta）

`context_delta.py` 只计算以下信号：

| 字段 | 含义 | 计算规则 |
|------|------|----------|
| `emotion_trend` | 情绪走势 | 比较本轮与上两轮 `intensity` |
| `streak_rounds_blocked` | 连续卡了几轮 | 统计历史中出现 `is_blocked` 的连续轮数（由 Agent2 输出决定） |
| `repeated_phrases` | 用户重复说的话 | 匹配预定义关键词列表，如 `["听不懂", "卡了", "为什么"]` |
| `repeated_concepts` | 用户重复提到的概念 | 从 `current_round.triggers` 中提取概念词，看是否连续出现 |

**原则**：只算"主要信息"，不塞复杂语义判断。

---

## 七、文件职责

### 7.1 main.py

Agent1 入口。接收用户输入和画像，返回完整情绪指纹，并写入文件。

伪代码：

```python
def 运行(用户输入, 画像):
    当前指纹 = llm_call.发送(用户输入, 画像)
    历史 = history_manager.读历史()
    差异 = context_delta.计算(当前指纹, 历史)
    当前指纹["context_delta"] = 差异
    history_manager.写当前(当前指纹)
    history_manager.写历史(当前指纹)
    return 当前指纹
```

### 7.2 llm_call.py

复制 `onboarding/LLMagent0.py` 的 `Request_s` 结构，但 `skill_path` 指向 `Aegnt1/SKILL.md`。

负责让 LLM 输出 `current_round` 部分。

### 7.3 context_delta.py

纯函数，输入"当前指纹 + 历史"，输出 `context_delta` 字典。

不读写文件，不调用 LLM。

### 7.4 history_manager.py

封装 `data/emotion_current.json` 和 `data/emotion_history.json` 的读写。

- `读历史()`：不存在时返回 `{"max_versions": 3, "history": []}`
- `写当前(指纹)`：覆盖 `emotion_current.json`
- `写历史(指纹)`：头部插入，超过 3 版删除尾部

---

## 八、相对导入关系

`Aegnt1/main.py` 内部导入：

```python
from .llm_call import 情绪LLM
from .context_delta import 计算上下文差异
from .history_manager import 读历史, 写历史, 写当前
```

`Aegnt1/llm_call.py` 不依赖其他模块，只读取本目录下的 `SKILL.md`。

---

## 九、给 Agent3 的输入边界

Agent3 拿到的只是 `data/emotion_current.json`，不再包含原始历史。

Agent3 如果需要历史，去读自己的 `data/teaching_history.json`。

---

## 十、暂不实现

以下功能当前版本不实现：

- 回滚逻辑
- 情绪数据进画像更新
- Agent1 与 Agent2 的协作（两者并发，互不依赖）
- 复杂的历史语义总结

---

## 十一、命名说明

本模块目录名为 `Aegnt1`（按当前项目实际目录）。如果后续统一命名为 `agent1`，同步修改本文档与导入路径即可。
