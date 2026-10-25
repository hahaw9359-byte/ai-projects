# Agent2.5 认知侦察兵

位置：`claw/Agent2_5/`

## 职责

接收 Agent1 的情绪指纹和 Agent2 的断点诊断，作为认知侦察兵读懂学习者当前真正需要什么，输出可直接用于回应的 Markdown 分析。

## 输入

- `emotion_current.json`：Agent1 输出的当前情绪指纹
- `breakpoint_diagnosis.json`：Agent2 输出的断点诊断报告

## 输出

- `data/teaching_state.md`：LLM 返回的 Markdown 格式认知侦察结果
- `tests/output/*.md`：批量测试时每个用例的输出

## 文件结构

```
Agent2_5/
├── __init__.py
├── main.py              # 入口：读取两份 JSON，返回 Markdown
├── LLM_call.py          # 调用 DeepSeek V4 Flash
├── save_state.py        # 保存 teaching_state.md
├── SKILL.md             # 认知侦察兵角色定义
├── README.md            # 本文件
├── data/
│   ├── sample_emotion_current.json
│   ├── sample_breakpoint_diagnosis.json
│   └── teaching_state.md
└── tests/
    ├── test_single.py   # 单测：跑一个样本
    ├── test_harness.py  # 批量测试，记录 token
    ├── test_cases.json  # 测试用例
    └── output/          # 测试结果（Markdown）
```

## 运行方式

从 `claw` 的父目录运行：

```bash
python -m claw.Agent2_5.tests.test_single
python -m claw.Agent2_5.tests.test_harness
```

## 输出格式

SKILL.md 要求 LLM 输出 Markdown，包含：

- 揣测结论（他真正想要什么/不想要什么）
- 他的认知通道
- 回应正文
- 回应的必要条件
- 绝对禁忌

## 设计原则

- 不翻译字段，读字段之间的张力。
- 以行为/状态为准，不以用户言语为准。
- 每个揣测必须有数据证据。
- 不强行推测，数据不足时明确标注。
