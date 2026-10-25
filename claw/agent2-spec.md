# Agent 2 技术规格 & 测试方案

> 日期：2026-08-01
> 状态：设计阶段 → 明天开写代码

---

## 一、方法论（从 Agent 0/1 的教训）

**核心打法：列可能性 → 设指标 → 跑一轮 → 看数据 → 调一个变量 → 再跑。**

禁止行为：
- 反复算成本不跑代码
- 纠结模型选型不设测试
- 改多个变量同时测

---

## 二、Agent 管道 & 时间预算

```
Agent 1 (V4 Pro, ~1s)  ──┐
                          ├─ 并发，取 max ≈ 5s (Agent 2a 是瓶颈)
Agent 2a (Qwen 7B, ~5s) ─┘

Agent 2.5 (V4 Flash, ~10-20s)
    输入：Agent 2a 诊断 + 15K 上下文 + 画像 + 知识进度
    输出：策略文档 ~1500 token

Agent 3 (V4 Pro, ~5-10s)
    输入：策略文档 + 当前消息 + RAG（不给上下文）
    输出：教学文本

总计：5 + 20 + 10 = 35s（目标 < 120s ✅）
```

---

## 三、多后端框架

每个 Agent 从配置读模型名，换模型改一行配置。

```python
# claw/shared/config.py
from dataclasses import dataclass

@dataclass
class AgentConfig:
    agent1_model: str = "deepseek-v4-pro"
    agent2a_model: str = "qwen2.5:7b"        # Ollama 本地
    agent2b_model: str = "deepseek-v4-flash"  # V4 Flash
    agent3_model: str = "deepseek-v4-pro"

    @property
    def agent2a_backend(self):
        if "qwen" in self.agent2a_model.lower():
            return "ollama"    # http://localhost:11434/v1
        return "deepseek"     # https://api.deepseek.com/v1

    @property
    def agent2b_backend(self):
        if "flash" in self.agent2b_model.lower():
            return "deepseek"
        if "qwen" in self.agent2b_model.lower():
            return "ollama"
        return "deepseek"
```

```python
# claw/shared/HTTT_llm.py → 加多后端支持
class MultiBackendClient:
    def __init__(self, config: AgentConfig):
        self.clients = {
            "deepseek": httpx.AsyncClient(
                base_url="https://api.deepseek.com/v1",
                headers={"Authorization": f"Bearer {os.getenv('Deepseek_key')}"}
            ),
            "ollama": httpx.AsyncClient(
                base_url="http://localhost:11434/v1",
            ),
        }

    async def send(self, backend: str, model: str, messages: list) -> dict:
        client = self.clients[backend]
        resp = await client.post("/chat/completions", json={
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 4000,
        })
        return resp.json()

    async def close(self):
        for c in self.clients.values():
            await c.aclose()
```

---

## 四、Agent 2a — 断点诊断

### 输入

```yaml
Agent 1 情绪指纹: { state, emotion, *_sub, trust_signal }  # ~300 token
用户本轮消息: "..."                                          # ~200 token
用户近 3 轮消息: ["...", "...", "..."]                      # ~800 token
今日画像摘要: { learning_style, blockage_response, ... }     # ~300 token
---
总计: ~1600 token
```

### 推理约束（三段式，不可跳过）

```
第一步：提取信号（只摘录，不判断）
  - 从 Agent 1 提取：主情绪 + 子类 + trust_signal
  - 从用户消息提取：关键动词/模式（跳过/追问/质疑/确认/沉默）
  - 从画像提取：与本轮相关的维度状态

第二步：逐一排除（按固定顺序，每个断点回答"存在吗？为什么？"）
  1. 情绪阻断     → Agent 1 frustrated 高分 + 用户归因指向自己？
  2. 认知过载     → 回复变短 + 跳过增多 + 情绪平稳？
  3. 前置缺失     → 反复追问但不同角度 + 画像显示前置未确认？
  4. 讲法不对口   → 指向 AI 表达 + 能正确复述知识本身？
  5. 多义混淆     → "这不是 X 吗" + "那到底是 A 还是 B"？
  6. 假性掌握     → "我学过" + 独立操作时暴露断层？
  7. 无断点        → 以上都不符合？

第三步：综合判断
  - 主诊断：未被排除的候选中证据最充分的一个
  - 次诊断：备选
  - 核心证据：摘录 2-3 条原文支撑
  - 置信度：0-1
```

### 输出格式

```json
{
  "has_breakpoint": true,
  "primary": {
    "type": "前置缺失",
    "confidence": 0.82,
    "evidence": [
      "用户连续3轮追问装饰器但未追问闭包",
      "知识表显示闭包未确认",
      "画像显示前置缺失模式"
    ]
  },
  "secondary": {
    "type": "讲法不对口",
    "confidence": 0.35,
    "evidence": ["用户说'你的类比例子不行'"]
  },
  "excluded": [
    {"type": "情绪阻断", "reason": "Agent 1 情绪平稳，无自我否定信号"},
    {"type": "认知过载", "reason": "回复长度稳定，无跳过信号"}
  ],
  "signal_summary": {
    "emotion": "confused=4, frustrated=1",
    "behavior": "反复追问同一概念，换角度三次未放弃",
    "profile_note": "类比权重0.71，但本轮跳过类比追问底层"
  }
}
```

### 模型候选 & 测试顺序

| 顺序 | 模型 | 原因 |
|---|---|---|
| 1 | Qwen 2.5 7B 本地 | 免费，先试 |
| 2 | Qwen 2.5 32B API（硅基流动） | 7B 不够就升级 |
| 3 | V4 Flash | 都不够就上车 |

---

## 五、Agent 2a 验收指标

### 测试集：25 组人工标注样本

- 20 组含断点（每种断点类型至少 3 组）
- 5 组无断点（正常学习状态）

### 指标

| 指标 | 计算方式 | 通过标准 |
|---|---|---|
| 准确率 | 主诊断匹配 / 总数 | ≥ 80%（20/25） |
| 证据有效性 | 人工检查：核心证据能否独立支撑诊断 | ≥ 80% |
| 假阳性率 | 5 组无断点中被误判为有断点 | ≤ 20%（最多 1 组） |
| 排除法完整度 | 是否对每类断点都给出了排除理由 | 100%（必须） |

### 不通过 → 调哪个

| 症状 | 调什么 |
|---|---|
| 准确率低，假阳性高 | prompt 排除法约束不够紧，加"必须给出排除理由" |
| 证据总是选不准 | prompt 里要求"摘录原文，不要改写" |
| 模型选的断点类型永远那 1-2 种 | 排除法顺序问题，调成强制逐一遍历 |
| 7B 和 32B 差距大 | 7B 对推理链路跟随不够，换 32B |

---

## 六、Agent 2.5 — 意图揣测 + 策略文档

### 输入

```yaml
Agent 2a 诊断: <断点诊断完整 JSON>                        # ~500 token
用户近 10 轮上下文: "..."                                  # ~10000 token
今日画像: { 完整画像 }                                     # ~500 token
知识进度: { 当前单元, 已掌握, 前置状态, 卡点历史 }           # ~300 token
Agent 1 情绪指纹: <完整 JSON>                              # ~300 token
---
总计: ~12000 token
```

### 推理约束

```
第一步：确认诊断
  - Agent 2a 的诊断和画像是否冲突？
  - 和当前知识进度是否吻合？
  - 有冲突 → 标注，不推翻 2a 诊断（2a 是近距离信号）

第二步：推测意图
  - 用户在逃避什么？（如果有）
  - 用户真正的需求是什么？（表层 vs 深层）
  - 用户现在的心理状态适合什么类型的输入？

第三步：设计路径
  - 切入角度：从哪个点开始讲？
  - 讲法风格：类比/结构/实践？
  - 关键确认点：讲完哪一段需要确认用户理解？（至少 2 个）
  - 避免什么：本轮绝对不能碰的话题/方式

第四步：上下文摘录
  - 近 3 轮里影响本轮教学的关键信息（用户原话 + 交互结果）
  - 100-200 字，给 Agent 3 接上下文用

第五步：风险预案
  - 如果本轮教学不通，退阶路径是什么？
  - 如果用户跳过，下一轮从哪接？
```

### 输出：策略文档（~1500 token）

```markdown
# 本轮教学策略

## 诊断确认
Agent 2a 诊断：前置缺失（闭包）
画像冲突：无。画像显示结构型偏好，本轮用结构展开不冲突。
知识进度：装饰器单元，前置"闭包"标记为"未确认"。

## 意图推测
用户表面在问"装饰器为什么需要闭包"，实际在试图跳过闭包直接理解装饰器。
深层需求：想要一个不需要理解闭包也能用装饰器的说法。
心理状态：困惑但未失控，还在主动探索（从3个角度追问）。

## 教学路径
切入角度：先确认用户对"函数是一等公民"的理解程度。
讲法风格：结构型。从内存模型出发，不讲类比。
关键确认点：
  - 确认点1：讲完"函数在堆上存储"后，让用户用自己的话复述
  - 确认点2：讲完"闭包 = 函数带着变量走"后，追问"那装饰器拿到的是什么？"
避免：不提 async/await（用户上一轮想跳过去逃避，别再给岔路）

## 上下文摘录
- 用户第3轮："你的类比例子不行，装饰器和排队有什么关系？" → 拒绝了类比
- 用户第2轮："闭包我知道，就是内层函数能访问外层变量" → 有表层认知，但可能不知道内存机制
- 用户第1轮："装饰器还是没懂" → 确认卡住

## 风险预案
退阶路径：如果确认点1（函数一等公民）不通 → 不继续讲闭包，先退到"Python 变量在内存中怎么存的"
跳过预案：如果用户喊跳过 → 不追，留一句"这个知识点后面自然会对上"，标记跳过的位置
```

### 模型候选 & 测试顺序

| 顺序 | 模型 | 原因 |
|---|---|---|
| 1 | V4 Flash | 性价比最优解 |
| 2 | V4 Pro | Flash 策略文档质量不够就升级 |
| 3 | Qwen 32B API | 最后的省钱选项 |

---

## 七、Agent 2.5 验收指标

### 测试集：Agent 2a 的 25 组样本 + 补充上下文

每组样本补上：10 轮上下文 + 画像 + 知识进度。

### 指标

| 指标 | 计算方式 | 通过标准 |
|---|---|---|
| 教学路径可用率 | Agent 3 能否直接按策略文档产出教学（人工判断） | ≥ 80% |
| 上下文摘录准确度 | 摘录是否覆盖了 Agent 3 需要的关键信息 | ≥ 85% |
| 风险预案覆盖 | 退阶路径和跳过预案是否都有 | 100%（必须） |
| 诊断利用度 | 是否引用了 Agent 2a 的诊断结论 | 100%（必须） |

---

## 八、Agent 3 验收指标

### 输入

```yaml
策略文档: <Agent 2.5 输出，~1500 token>
当前用户消息: "..."                                        # ~200 token
RAG 知识: { 装饰器章节相关段落 }                            # ~800 token
---
总计: ~2500 token（不给上下文，省一大笔）
```

### 指标

| 指标 | 计算方式 | 通过标准 |
|---|---|---|
| 策略执行度 | 教学是否按策略文档的切入角度和讲法风格展开 | ≥ 90% |
| 确认点覆盖 | 策略文档要求的确认点是否都在教学中出现 | 100%（必须） |
| 上下文衔接度 | 教学是否自然接上用户上一句（靠策略文档的上下文摘录） | ≥ 80% |
| 边界意识 | 是否在不确定时标注"这部分不完全确定" | 不扣分，加分 |

---

## 九、测试顺序（明天执行）

```
第1轮：Agent 2a 挂 Qwen 7B → 跑 25 组 → 看指标
  通过？→ 锁定 2a，进入 2.5
  不通过？→ 调 prompt → 再跑（最多 3 轮）
  3 轮不通过？→ 换 Qwen 32B API → 再跑

第2轮：Agent 2.5 挂 V4 Flash → 跑 25 组 → 看指标
  通过？→ 锁定 2.5，进入 Agent 3
  不通过？→ 换 V4 Pro → 再跑

第3轮：Agent 3 挂 V4 Pro → 拿 Agent 2.5 的输出 → 跑 25 组 → 看指标
  通过？→ 全链路跑通 ✅
  不通过？→ 调 Agent 3 prompt → 再跑

第4轮：全链路集成测试
  Agent 1 + 2a 并发 → Agent 2.5 → Agent 3
  测延迟、测串联质量、测异常处理
```

---

## 十、文件结构（目标）

```
claw/
├── Agent1/
│   ├── qingxuzhiwen.md        # prompt ✅
│   └── LLM_call.py            # 调用封装 ✅
├── Agent2/
│   ├── duandian.md            # 2a 断点诊断 prompt（明天写）
│   ├── celve.md               # 2.5 策略文档 prompt（明天写）
│   ├── LLM_call_2a.py         # 2a 调用封装
│   └── LLM_call_2b.py         # 2.5 调用封装
├── Agent3/
│   └── jiaoxue.md             # Agent 3 教学 prompt（待写）
├── shared/
│   ├── HTTT_llm.py            # 多后端 client ✅（需改造成 MultiBackend）
│   ├── config.py              # AgentConfig（明天写）
│   └── tik_token.py           # token 估算 ✅
├── tests/
│   ├── test_agent2a.json      # 25 组断点诊断测试样本
│   └── test_agent2b.json      # 25 组策略文档测试样本（含上下文）
└── test_runner.py             # 测试执行器（批量跑 + 输出指标）
```
