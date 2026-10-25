# Agent1 情绪指纹模块总结

> 更新日期：2026-08-04
> 状态：Agent1 已跑通，输出情绪指纹并持久化到 `emotion_recent.json`
> 说明：本总结只覆盖 Agent1 本身，全局记忆/用户画像整合将在 Agent3 阶段处理

---

## 一、Agent1 定位

Agent1 是 Claw 系统的**情绪指纹提取器**。

**核心职责**：接收用户单轮输入，输出当前认知状态 + 情绪反应 + 信任信号。

**设计原则**：
- 只处理**当前轮输入**，不做跨轮判断
- 不打归一化，输出原始 0-5 分数
- 只输出结构化 JSON，不做解释
- 不直接参与教学决策，把结果交给 Agent3 汇总

---

## 二、输出结构

Agent1 输出一个 JSON 对象，包含四层：

```json
{
  "state": { ... },           // 认知状态层
  "emotion": { ... },         // 情绪层
  "xxx_sub": { ... },         // 情绪子类层（多个）
  "trust_signal": 0.6         // 信任信号
}
```

### 2.1 认知状态层（state）

5 个维度，互相独立，0-5 分。

| 状态 | 含义 |
|------|------|
| advancing | 推进中。学习在正常往前走，没有被卡住 |
| exploring | 探索中。遇到障碍但在面对，换角度追问、自己试了回来确认 |
| stalled | 停滞中。停了，没试、没求助、没跳过，原因不明 |
| skipping | 跳过中。绕开了当前知识点或话题 |
| flowing | 心流中。高度投入，主动输出理解、推导、追问更深层问题 |

### 2.2 情绪层（emotion）

6 个维度，互相独立，0-5 分。

| 情绪 | 含义 |
|------|------|
| calm | 平静，没有明显情绪波动 |
| confused | 困惑，矛头指向知识本身 |
| frustrated | 挫败，被障碍击穿，矛头转向自己或 AI |
| annoyed | 烦躁，对交互方式、节奏、表达清晰度不满 |
| anxious | 焦虑，压力在远方——时间、方向、目标 |
| confident | 自信，主动确认理解或毫不犹豫推进 |

### 2.3 情绪子类层（xxx_sub）

当某个情绪 > 0 时，填写对应子类。子类内部也打 0-5 分，每个子类附带一条用户原话 `quote`。

#### confused_sub
- curious：在探索，换角度追问，自己试了回来确认
- blocked：卡住但还在试，同一概念反复撞
- lost：停了在等你，不自己试了
- stall：停了且原因不明

#### frustrated_sub
- anger_at_ai：强烈攻击 AI，脏话或人格否定
- self_sad：否定自己，"我太笨""学不会"
- numb：麻木，从长篇跌到"嗯""好"

#### annoyed_sub
- wrong_method：嫌 AI 讲法不对，"换个方式""别给我代码"
- unclear_explanation：嫌 AI 讲不清楚，"你说的我听不懂"
- too_slow：嫌 AI 节奏慢，"直接说""别绕"
- bad_state：嫌自己状态差，"我脑子不转了"
- restless：焦躁，不耐烦但不带脏话
- unclear：烦躁但原因不明确

#### anxious_sub
- rushing：赶，快速翻页、回复短快
- doubt_direction：质疑目标，"学这个有用吗"
- doubt_self：质疑自己，"我是不是不适合学这个"
- restless：坐不住，想跳、想换

#### confident_sub
- confirming：主动确认，"我是不是可以这样理解"
- advancing：毫不犹豫推进，"知道了，继续"

### 2.4 信任信号（trust_signal）

用户对当前教学的信任程度，0-1 浮点数。

**规则**：直接根据语气给最终值，不要从基线加减，不要加权计算。

| 最终值 | 信号 |
|--------|------|
| 0.0 ~ 0.1 | 明确不信任——"你滚吧""换 AI""你被枪毙了" |
| 0.2 ~ 0.3 | 强烈质疑——"你会不会啊""你能不能说清楚" |
| 0.4 ~ 0.5 | 中等质疑——"你确定吗""这对吗" |
| 0.5 ~ 0.55 | 轻微不耐烦——"快点""直接说" |
| 0.6 | 无明显信号，默认基线 |
| 0.7 ~ 0.8 | 轻微接受——"好""继续""嗯" |
| 0.9 ~ 1.0 | 明确信任——"按你说的来""我相信你" |

**注意**：
- 只看当前轮，不看历史
- 骂人但继续交互，最低不要低于 0.3
- 质疑 AI 但未终止对话，给 0.3 左右
- 真正想放弃才给 0.1-0.2

---

## 三、代码实现

### 3.1 文件结构

```
claw/
├── Agent1/
│   ├── __init__.py
│   ├── qingxuzhiwen.md       # Agent1 prompt / skill
│   ├── LLM_call.py           # 封装 Agent1 调用 + JSON 清洗
│   ├── save_and_trend.py     # 持久化：维护 emotion_current.json + emotion_recent.json
│   ├── data/                 # 运行时生成的情绪数据
│   │   ├── emotion_current.json
│   │   └── emotion_recent.json
│   └── AGENT1_SUMMARY.md     # 本文件
├── shared/
│   ├── HTTT_llm.py           # 异步 LLM client
│   └── tik_token.py          # token 估算
└── agent1main.py             # Agent1 独立测试入口
```

### 3.2 shared/HTTT_llm.py

异步 LLM client，基于 `httpx.AsyncClient`。

**核心方法**：
- `__init__()`：加载 API key、模型、URL，初始化 httpx client
- `send(messages)`：发送消息，返回 dict，包含 `content` 或 `error`
- `close()`：关闭 httpx client，释放连接池

**关键配置**：
- 默认模型：`deepseek-v4-pro`
- 默认 URL：`https://api.deepseek.com/v1/chat/completions`
- 默认 `maxtoken=4000`（已修正，原 20000 与 limit_token=15000 冲突）
- 默认 `limit_token=15000`

**返回值结构**：
```python
# 成功
{
    "content": "LLM 返回的字符串",
    "prompt_token": 123,
    "completion_token": 456,
    "tool_calls": None
}

# 失败
{"error": "错误信息"}
```

### 3.3 Agent1/LLM_call.py

封装 Agent1 的调用逻辑：读取 skill → 调用 LLM → 清洗 Markdown → 解析 JSON → 持久化。

```python
from ..shared.HTTT_llm import LLM_client
import os
import json
import re
from .save_and_trend import save_and_trend

skill_path = os.path.join(os.path.dirname(__file__), "qingxuzhiwen.md")
with open(skill_path, "r", encoding="utf-8") as f:
    skill_content = f.read()

client = LLM_client()

async def agent1(query):
    messages = [
        {"role": "system", "content": skill_content},
        {"role": "user", "content": f"用户输入{query}"}
    ]
    result = await client.send(messages)

    if "error" in result:
        return {"error": result["error"]}

    content = result.get("content", "")
    if not content:
        return {"error": "LLM 返回空内容"}

    try:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        econtent = json.loads(content.strip())
        save_and_trend(econtent)
        return econtent
    except json.JSONDecodeError:
        return {"error": "json解析失败", "raw": content}
```

**设计要点**：
- 使用相对路径读取 skill prompt
- `agent1()` 返回解析后的情绪指纹 dict；出错时返回 `{"error": ...}`
- Markdown 代码块清洗放在 Agent1 内部，调用方拿到的是干净 JSON
- 解析成功后立即调用 `save_and_trend()` 持久化
- client 作为模块级变量，复用连接池

### 3.4 agent1main.py

Agent1 独立测试入口。

```bash
python -m claw.agent1main
```

**功能**：
- 循环读取用户输入
- 调用 `agent1(query)`
- 打印格式化后的情绪指纹
- 程序退出时关闭 client

**事件循环管理**：
```python
async def main():
    try:
        while True:
            query = input("用户：").strip()
            if query.lower() == "q":
                break

            emotion_data = await agent1(query)

            if "error" in emotion_data:
                print(f"调用失败：{emotion_data['error']}")
                continue

            print(json.dumps(emotion_data, ensure_ascii=False, indent=2))
    finally:
        print("关闭 HTTP client...")
        await client.close()

asyncio.run(main())
```

**关键注意**：`client.close()` 必须和 `main()` 在同一个事件循环里关闭，不能再用第二个 `asyncio.run()`。

### 3.5 Agent1/save_and_trend.py

负责情绪指纹的本地持久化。

```python
import os
import json
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def save_and_trend(emotion_data):
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now().isoformat()
    current = {
        "timestamp": now,
        "emotion_data": emotion_data
    }

    with open(f"{DATA_DIR}/emotion_current.json", "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    emotion_file = f"{DATA_DIR}/emotion_recent.json"
    emotion_recent = []
    if os.path.exists(emotion_file):
        with open(emotion_file, "r", encoding="utf-8") as f:
            emotion_recent = json.load(f)

    emotion_recent.append(current)
    with open(emotion_file, "w", encoding="utf-8") as f:
        json.dump(emotion_recent[-3:], f, ensure_ascii=False, indent=2)
```

**设计要点**：
- `emotion_current.json`：当前轮的情绪指纹（可后续删除，与 recent[-1] 重复）
- `emotion_recent.json`：最近 3 轮的情绪指纹，append 后裁剪，只保留最近 3 条
- Agent1 只维护**工作记忆**，不做跨轮趋势判断

---

## 四、运行方式

### 4.1 环境要求

- Python 3.13+
- 安装依赖：`httpx`, `python-dotenv`
- 项目根目录 `.env` 文件包含 `Deepseek_key`

### 4.2 启动命令

在项目根目录 `需求反推知识点` 下执行：

```bash
python -m claw.agent1main
```

### 4.3 退出

输入 `q` 退出，程序会自动调用 `client.close()` 释放连接池。

---

## 五、设计演进与关键认知

Agent1 的调试过程不只是修 bug，更是对异步 HTTP、包导入、资源管理等概念的重新理解。下面是关键认知的演进。

### 5.1 为什么用 httpx 而不是 requests

**第一版思路**：用 `requests.post()` 直接发 HTTP 请求。

问题：`requests` 是同步库，不能在 `async/await` 里用。如果在 async 函数里调用 `requests.post()`，会阻塞整个事件循环，其他并发任务全部卡住。

**演进**：换成 `httpx.AsyncClient`。

`httpx.AsyncClient` 的核心特点：
- 支持 `async/await`，不会阻塞事件循环
- 内部维护 TCP 连接池，多次请求可以复用连接
- 同一个 client 实例反复调用 `post()`，性能比每次新建连接好

### 5.2 对 client 关闭机制的理解过程

**第一阶段：不理解 close 的意义**

最初觉得：`httpx.AsyncClient()` 创建后直接用，程序退出就完了，为什么要 close？

后来发现：
- 单次脚本运行结束，操作系统会回收所有资源，确实可以不 close
- 但长期运行或反复创建 client 时，连接池会占用 socket（文件描述符），不释放会导致 FD 泄漏
- `close()` 是资源契约：告诉系统这个 client 用完了，可以释放连接池

**第二阶段：搞不清 close 的层级**

`LLM_client` 类里写：
```python
self.client = httpx.AsyncClient()
```

外部拿到的是 `LLM_client` 实例，不是 `httpx.AsyncClient` 实例。

所以 `client.close()` 调用的是 `LLM_client` 的方法，不是 `httpx.AsyncClient` 的方法。Python 不会自动穿透到内层对象。

**第三阶段：封装 close()**

在 `LLM_client` 类中显式定义：
```python
async def close(self):
    if self.client is not None:
        await self.client.aclose()
```

这样外部才能通过 `client.close()` 统一释放资源。

`aclose()` 是 `httpx.AsyncClient` 的异步关闭方法，调用它必须加 `await`。`if self.client is not None` 是防御性保护：如果 `__init__` 中某些初始化失败导致 `self.client = None`，直接调用 `aclose()` 会报错。

### 5.3 包导入与运行方式的理解过程

**第一阶段：直接运行脚本**

尝试：
```bash
python agent1main.py
```

问题：
- `agent1main.py` 在 `claw/` 子目录下，当前目录找不到
- `LLM_call.py` 里用了相对导入 `from ..shared.HTTT_llm import ...`，直接运行脚本时 `__package__` 是 `None`，相对导入会报 `ImportError: attempted relative import with no known parent package`

**第二阶段：理解 `python -m` 的含义**

`-m` 是把模块当作包的一部分来运行。`python -m claw.agent1main` 会先加载 `claw` 包，再执行 `claw/agent1main.py`。此时 `__package__ == "claw"`，相对导入能正确解析。

**第三阶段：导入路径的困惑**

尝试：
```python
from Aegnt1.LLM_call import agent1, client
```

报错 `No module named 'Aegnt1'`，因为 Python 在 `sys.path` 里找不到顶层模块 `Aegnt1`，它实际在 `claw/Aegnt1/` 下。

**第四阶段：统一绝对包路径导入**

改成：
```python
from claw.Agent1.LLM_call import agent1, client
```

这样 Python 先找到 `claw` 包，再往下找 `Agent1.LLM_call`，运行方式统一为 `python -m claw.agent1main`。

这个选择的好处：
- 不用写 `..shared` 这种相对路径
- 模块身份清晰
- 和 `python -m claw` 的运行方式保持一致

### 5.4 JSON 解析的认知

**第一阶段：以为 LLM 返回的就是字典**

实际上 LLM 返回的是**字符串**。可以直接 `print` 看到内容，但不能 `result["state"]`。

**第二阶段：`json.loads` 的作用**

`json.loads()` 把 JSON 字符串反序列化成 Python dict：
```python
content = '{"state": "flowing"}'
data = json.loads(content)  # 变成 dict
```

**第三阶段：Markdown 代码块问题**

LLM 输出经常带 ```json ... ``` 包装，`json.loads()` 不认识这些反引号。需要先清洗：
```python
content = result["content"].strip()
if content.startswith("```"):
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
emotion_data = json.loads(content.strip())
```

### 5.5 token 限制的设计逻辑

`HTTT_llm.py` 中的限制逻辑：
```python
prompt_token = 预估token["token"] + self.max_token
if prompt_token > self.limit_token:
    return {"error": "token爆炸无法发送"}
```

含义：**输入 token + 输出 token（max_token）不能超过总限制**。

最初配置 `maxtoken=20000`，`limit_token=15000`，导致任何请求都炸，因为输出上限已经超过了总上限。

修正为 `maxtoken=4000`，保证输入 + 输出 <= 15000 有合理空间。

### 5.6 已解决的代码问题清单

| 问题 | 原因 | 解决 |
|------|------|------|
| `SyntaxError: positional argument follows keyword argument` | `self.client.post(..., timeout=120, conn)` 位置参数在关键字参数后 | 删除多余参数 |
| `self.maxtoken` 与 `self.max_token` 混用 | 拼写不一致 | 统一为 `self.max_token` |
| `KeyError: 'content'` | `LLM_call.agent1()` 返回 `result["content"]`，但调用失败时 result 只有 `error` | 改成返回完整 result dict |
| `AttributeError: 'LLM_client' object has no attribute 'close'` | 外部调用的是 `LLM_client` 的方法，不是内层 `httpx.AsyncClient` | 在 `LLM_client` 中封装 `close()` |
| `UnboundLocalError: cannot access local variable 'econtent'` | `econtent = json.loads(...)` 缩进在 `if content.startswith("```"):` 内部，非代码块返回时变量未定义 | 将 `json.loads` 提到 if 外部；错误分支返回 `{"error": ...}` |
| `RuntimeError: Event loop is closed` | `finally` 中第二次调用 `asyncio.run(client.close())`，client 绑定的是已关闭的第一个 loop | 把 `await client.close()` 放到 `main()` 的 `finally` 里，只调用一次 `asyncio.run(main())` |

### 5.7 对 `asyncio.run()` 的理解

`asyncio.run()` 的完整生命周期：

1. **create event loop**：创建一个新的事件循环
2. **run coroutine**：运行传入的协程（如 `main()`）
3. **close event loop**：协程结束后，关闭事件循环

因此 `asyncio.run()` 是**一次性**的。第一次 `asyncio.run(main())` 结束后，事件循环已经关闭。如果此时再调用 `asyncio.run(client.close())`，会创建第二个事件循环去关闭第一个循环里的 `client`，而 `client` 内部的 httpx 连接池还绑定在第一个已关闭的 loop 上，于是报 `RuntimeError: Event loop is closed`。

正确做法是把资源释放放到 `main()` 的 `finally` 里：

```python
async def main():
    try:
        ...
    finally:
        await client.close()

asyncio.run(main())
```

### 5.8 测试用例

输入：
```text
每次在相对路径就出错，我真的服了，搞不懂这玩意为什么就这么难搞，傻逼玩意，我这次就要搞相对路径，操
```

输出关键指标：
- state：exploring=4
- emotion：frustrated=5, annoyed=3, confused=1
- trust_signal：0.1（偏低，已计划调整到 0.3-0.4）

---

## 六、当前状态

- [x] Agent1 prompt 设计完成
- [x] 异步 LLM client 封装完成
- [x] Agent1 调用封装完成
- [x] 独立测试入口完成
- [x] Markdown JSON 清洗完成
- [x] trust_signal 规则细化完成
- [x] 情绪指纹本地持久化完成（`emotion_recent.json` 最近 3 轮）
- [x] `UnboundLocalError` 与 `Event loop is closed` 已修复
- [ ] 删除 `emotion_current.json` 重复逻辑（可选）
- [ ] 与 Agent2 并发运行
- [ ] Agent3 汇总情绪指纹 + 用户画像做教学决策

---

## 七、下一步

1. 确认 `emotion_current.json` 是否保留；若只保留 `emotion_recent.json`，删除 `save_and_trend.py` 中重复写入逻辑
2. 接入 Agent2（断点诊断），实现 Agent1 + Agent2 并发调用
3. Agent3 消费 Agent1 + Agent2 的输出，生成教学策略
4. 全局情绪记忆/用户画像整合延后到 Agent3 阶段处理

---

## 八、关键经验

1. **包导入**：`-m` 运行和直接运行脚本在 `__package__` 上不同，跨包导入必须用 `-m`
2. **封装原则**：外部能调用的方法必须在类上显式定义，Python 不会自动穿透到内层对象
3. **资源释放**：长期 `httpx.AsyncClient` 需要显式 `aclose()`，关闭必须在创建它的同一个事件循环里完成
4. **LLM 输出清洗**：不要假设 LLM 一定返回干净 JSON，要做 Markdown 代码块清洗
5. **配置一致性**：`max_token` 必须小于 `limit_token`，否则任何请求都会触发限制
6. **变量作用域**：`if` 分支内赋值的变量，在分支外访问时要确保所有执行路径都会赋值
7. **职责边界**：Agent1 只输出当前轮情绪指纹和维护最近 N 轮工作记忆，跨轮趋势/全局记忆交给 Agent3
