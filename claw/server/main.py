import asyncio
import json
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response

# ---- 加载环境变量 ----
from dotenv import load_dotenv
import os as _os
_env_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), '.env')
if _os.path.exists(_env_path):
    load_dotenv(_env_path)

# ---- Claw 管线组件 ----
from claw.Agent1.LLM_call import agent1, client as agent1_client
from claw.Agent2.LLM_call import agent2, agent2b, agent2c, flash_client as agent2_client, flash_client_2c
from claw.Agent2_5.LLM_call import agent2_5, client as agent2_5_client
from claw.Agent2_5.main import build_messages as build_agent2_5_messages
from claw.Agent3.main import run_with_history
from claw.Agent3.LLM_call import client as agent3_client
from claw.shared.context_store import append_user_input
from claw.shared.round_store import write_breakpoint
from claw.onboarding.LLMagent0 import Request_s as QuestionGenerator
from claw.onboarding.LLMagent_run import Request as ProfileNarrator
from claw.onboarding.map import SCORING_MAP, RISK_RULES
from claw.portrait.profile_normalizer import normalize_profile
from claw.shared.chunk_retriever import ChunkRetriever

# ---- 加载 skill 文件 ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_skill(filename):
    path = os.path.join(BASE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

agent1_skill = _load_skill("Agent1/qingxuzhiwen.md")
agent2a_skill = _load_skill("Agent2/duanadianzhenduan.md")
agent2b_skill = _load_skill("Agent2/youshishibie.md")
agent2c_skill = _load_skill("Agent2/zhishiliu.md")

# ---- 加载画像 ----
def _load_profile():
    profile_path = os.path.join(BASE_DIR, "profile.json")
    if not os.path.exists(profile_path):
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return None
    return None

# ---- 客户端生命周期 ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 关闭所有 HTTP client
    for client in [agent1_client, agent2_client, flash_client_2c, agent2_5_client, agent3_client]:
        try:
            await client.close()
        except Exception:
            pass

# ---- FastAPI 应用 ----
app = FastAPI(title="Claw Teaching System", lifespan=lifespan)

# 静态文件 & 模板
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/favicon.ico")
async def favicon():
    return Response(content="", media_type="image/x-icon")

# ---- 画像测试 API ----
@app.get("/api/onboarding/questions")
async def get_onboarding_questions(topic: str = ""):
    """生成 11 道诊断题。topic 为空时使用默认主题。"""
    try:
        gen = QuestionGenerator()
        loop = asyncio.get_event_loop()
        if topic:
            prompt = topic
        else:
            prompt = "给一个正在学习编程或技术的用户生成11道诊断题，用于了解他的学习风格、障碍响应、巩固方式、主动性和压力耐受。"
        result = await loop.run_in_executor(
            None, gen.发送, prompt
        )
        if isinstance(result, list) and result and "error" in result[0]:
            return {"error": result[0]["error"]}
        content = result.get("content", "")
        if not content:
            return {"error": "LLM 返回空内容"}
        # 尝试解析 JSON
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            questions = json.loads(cleaned)
            return {"questions": questions}
        except json.JSONDecodeError:
            # 解析 markdown 格式的题目
            parsed = _parse_markdown_questions(content)
            if parsed and len(parsed) >= 8:
                return {"questions": parsed}
            return {"questions_raw": content}
    except Exception as e:
        return {"error": str(e)}

def _parse_markdown_questions(content: str):
    """将 LLM 返回的 markdown 题目解析为结构化列表。"""
    questions = []
    # 支持多种题目分隔格式：
    #   **第 N 题** / ### N. / **N. / N.
    blocks = re.split(
        r'\n(?=\*\*第\s*\d+\s*题\*\*|###\s*\d+\.|\*\*\d+\.|\d+\.\s)',
        content
    )
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # 去掉题目编号/标题前缀
        q_text = re.sub(
            r'^(?:\*\*第\s*\d+\s*题\*\*|###\s*\d+\.\s*|\*\*\d+\.\s*|\d+\.\s*)',
            '', block
        ).strip()
        q_text = re.sub(r'\n---\s*$', '', q_text).strip()
        # 提取选项 A. / B. / C. / D.（支持带或不带 - 前缀）
        opt_pattern = re.findall(
            r'(?:^|\n)\s*-?\s*([A-D])\.\s*(.+?)(?=\n\s*-?\s*[A-D]\.|\n\*\*第|\n\d+\.\s|\n###|\Z)',
            block, re.DOTALL
        )
        options = {}
        for opt_letter, opt_text in opt_pattern:
            options[opt_letter] = opt_text.strip()
        if q_text and len(options) >= 2:
            questions.append({"text": q_text, "options": options})
    return questions

@app.post("/api/onboarding/submit")
async def submit_onboarding_answers(data: dict):
    """提交答案，生成画像并保存。"""
    try:
        answers = data.get("answers", {})
        if not answers or len(answers) < 11:
            return {"error": "请回答全部 11 道题"}
        
        # 使用 SCORING_MAP 计分
        raw_score = {}
        for qid in SCORING_MAP:
            choice = answers.get(qid)
            if not choice:
                continue
            selected = SCORING_MAP[qid][choice]
            for attr, score in selected.items():
                raw_score[attr] = raw_score.get(attr, 0) + score
        
        # 归一化生成画像
        profile = normalize_profile(raw_score)
        
        # 风险检测
        profile["risks"] = []
        for risk_name, rule in RISK_RULES.items():
            conditions = rule["conditions"]
            all_match = True
            for qid, choice in conditions:
                if answers.get(qid) != choice:
                    all_match = False
                    break
            if all_match:
                profile["risks"].append(risk_name)
        
        # 调用 LLM 生成画像叙述
        narrator = ProfileNarrator()
        loop = asyncio.get_event_loop()
        narration = await loop.run_in_executor(
            None, narrator.发送, json.dumps(profile, ensure_ascii=False)
        )
        if isinstance(narration, list) and narration and "error" in narration[0]:
            narrative_text = ""
        else:
            narrative_text = narration.get("content", "") if isinstance(narration, dict) else ""
        
        # 保存 profile.json
        profile_path = os.path.join(BASE_DIR, "profile.json")
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        
        return {
            "profile": profile,
            "narrative": narrative_text
        }
    except Exception as e:
        return {"error": str(e)}

# ---- 教学知识库 API ----
# ---- 画像查看 API ----
@app.get("/api/profile")
async def get_profile():
    """返回当前学习画像。"""
    profile = _load_profile()
    if profile is None:
        return {"profile": None}
    return {"profile": profile}

# ---- 教学知识库 API ----
KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Agent3", "data", "knowledge")
KB_COMBINED = os.path.join(KB_DIR, "_combined.md")
PLAN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Agent3", "data", "plan.md")
_kb_retriever = None

def _ensure_kb_dir():
    os.makedirs(KB_DIR, exist_ok=True)

async def _rebuild_combined():
    """将所有上传文件 + plan.md 合并为一个文件。"""
    _ensure_kb_dir()
    parts = []
    # 先加 plan.md
    if os.path.exists(PLAN_PATH):
        with open(PLAN_PATH, 'r', encoding='utf-8') as f:
            parts.append(f.read())
    # 再加所有上传文件
    for fn in sorted(os.listdir(KB_DIR)):
        if fn == '_combined.md':
            continue
        fp = os.path.join(KB_DIR, fn)
        if os.path.isfile(fp):
            with open(fp, 'r', encoding='utf-8') as f:
                parts.append(f.read())
    with open(KB_COMBINED, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(parts))
    # 重建检索器
    global _kb_retriever
    _kb_retriever = ChunkRetriever(KB_COMBINED)
    await _kb_retriever.warmup()

async def _get_kb():
    global _kb_retriever
    if _kb_retriever is None:
        await _rebuild_combined()
    return _kb_retriever

@app.get("/api/knowledge/files")
async def list_kb_files():
    """列出已上传的知识库文件。"""
    _ensure_kb_dir()
    files = []
    for fn in sorted(os.listdir(KB_DIR)):
        if fn == '_combined.md':
            continue
        fp = os.path.join(KB_DIR, fn)
        if os.path.isfile(fp):
            files.append({
                "name": fn,
                "size": os.path.getsize(fp),
                "size_human": _format_size(os.path.getsize(fp))
            })
    return {"files": files}

def _format_size(size):
    for unit in ['B', 'KB', 'MB']:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

@app.post("/api/knowledge/upload")
async def upload_kb_file(file: UploadFile = File(...)):
    """上传文件到知识库。"""
    if not file.filename:
        return {"error": "文件名为空"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.md', '.txt', '.json', '.pdf'):
        return {"error": f"不支持的文件类型: {ext}，仅支持 .md .txt .json .pdf"}
    _ensure_kb_dir()
    # 处理重名
    base, ext = os.path.splitext(file.filename)
    save_path = os.path.join(KB_DIR, file.filename)
    counter = 1
    while os.path.exists(save_path):
        save_path = os.path.join(KB_DIR, f"{base}_{counter}{ext}")
        counter += 1
    content = await file.read()
    # 尝试解码
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            text = content.decode('gbk')
        except UnicodeDecodeError:
            return {"error": "无法解码文件，请使用 UTF-8 编码"}
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(text)
    final_name = os.path.basename(save_path)
    # 重建索引
    await _rebuild_combined()
    return {"ok": True, "filename": final_name, "size": len(text)}

@app.delete("/api/knowledge/files/{filename}")
async def delete_kb_file(filename: str):
    """删除知识库文件。"""
    _ensure_kb_dir()
    fp = os.path.join(KB_DIR, filename)
    if not os.path.exists(fp):
        return {"error": "文件不存在"}
    os.remove(fp)
    await _rebuild_combined()
    return {"ok": True}


# ---- 管线函数 ----
async def run_pipeline(query: str, profile_data: Optional[dict] = None):
    """运行完整 Claw 管线，返回每一步的结果。"""
    append_user_input(query)

    # Step 1: 构造 messages
    agent1_messages = [
        {"role": "system", "content": agent1_skill},
        {"role": "user", "content": f"用户输入：{query}"}
    ]
    agent2a_messages = [
        {"role": "system", "content": agent2a_skill},
        {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请判断断点类型和子类。"}
    ]
    agent2b_messages = [
        {"role": "system", "content": agent2b_skill},
        {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请识别优势。"}
    ]
    agent2c_messages = [
        {"role": "system", "content": agent2c_skill},
        {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请提取知识流。"}
    ]

    # Step 2: 并发调用 Agent1 + Agent2a/b/c
    t0 = time.time()
    emotion_data, diag_data, strengths_data, flow_data = await asyncio.gather(
        agent1(agent1_messages),
        agent2(agent2a_messages),
        agent2b(agent2b_messages),
        agent2c(agent2c_messages)
    )
    step1_time = round(time.time() - t0, 1)

    # 合并断点数据
    breakpoint_data = {}
    if "error" not in diag_data:
        breakpoint_data.update(diag_data)
    if "error" not in strengths_data:
        breakpoint_data.update(strengths_data)
    if "error" not in flow_data:
        breakpoint_data.update(flow_data)

    if breakpoint_data:
        write_breakpoint(breakpoint_data)

    # Step 3: Agent2.5 认知侦察
    scout_result = None
    if "error" not in emotion_data and breakpoint_data:
        agent2_5_messages = build_agent2_5_messages(profile_data)
        scout_result = await agent2_5(agent2_5_messages)

    # Step 4: Agent3 教学执行
    agent3_result = None
    if scout_result and "error" not in scout_result:
        scout_content = scout_result.get("content", "")
        agent3_result = await run_with_history(
            query, scout_content, max_turns=2
        )

    total_time = round(time.time() - t0, 1)

    return {
        "emotion": emotion_data,
        "breakpoint": {
            "diagnosis": diag_data,
            "strengths": strengths_data,
            "knowledge_flow": flow_data
        },
        "scout": scout_result,
        "teaching": agent3_result,
        "timing": {"step1": step1_time, "total": total_time}
    }


# ---- WebSocket 端点 ----
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    profile_data = _load_profile()

    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "message":
                continue

            query = msg["content"].strip()
            if not query:
                continue

            # 发送进度：开始
            await ws.send_json({"type": "status", "step": "start", "message": "开始分析..."})

            # Step 1: 并发 Agent1 + Agent2
            await ws.send_json({"type": "status", "step": "agent1", "message": "Agent1 情绪指纹分析中..."})
            await ws.send_json({"type": "status", "step": "agent2", "message": "Agent2 断点诊断中..."})

            append_user_input(query)

            agent1_messages = [
                {"role": "system", "content": agent1_skill},
                {"role": "user", "content": f"用户输入：{query}"}
            ]
            agent2a_messages = [
                {"role": "system", "content": agent2a_skill},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请判断断点类型和子类。"}
            ]
            agent2b_messages = [
                {"role": "system", "content": agent2b_skill},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请识别优势。"}
            ]
            agent2c_messages = [
                {"role": "system", "content": agent2c_skill},
                {"role": "user", "content": f"本轮用户输入：\n{query}\n\n请提取知识流。"}
            ]

            t0 = time.time()
            try:
                emotion_data, diag_data, strengths_data, flow_data = await asyncio.gather(
                    agent1(agent1_messages),
                    agent2(agent2a_messages),
                    agent2b(agent2b_messages),
                    agent2c(agent2c_messages)
                )
            except Exception as e:
                await ws.send_json({"type": "error", "step": "agent1_2", "message": str(e)})
                continue

            step1_time = round(time.time() - t0, 1)

            # 发送 Agent1 结果
            await ws.send_json({
                "type": "result", "step": "agent1", "data": emotion_data, "timing": step1_time
            })

            # 发送 Agent2 结果
            breakpoint_data = {}
            if "error" not in diag_data:
                breakpoint_data.update(diag_data)
            if "error" not in strengths_data:
                breakpoint_data.update(strengths_data)
            if "error" not in flow_data:
                breakpoint_data.update(flow_data)

            await ws.send_json({
                "type": "result", "step": "agent2",
                "data": {
                    "diagnosis": diag_data,
                    "strengths": strengths_data,
                    "knowledge_flow": flow_data
                }
            })

            if breakpoint_data:
                write_breakpoint(breakpoint_data)

            # Step 2: Agent2.5
            if "error" in emotion_data or not breakpoint_data:
                await ws.send_json({"type": "error", "step": "skip", "message": "Agent1 或 Agent2 失败，跳过后续步骤"})
                await ws.send_json({"type": "done"})
                continue

            await ws.send_json({"type": "status", "step": "agent2_5", "message": "Agent2.5 认知侦察中..."})
            agent2_5_messages = build_agent2_5_messages(profile_data)
            scout_result = await agent2_5(agent2_5_messages)

            await ws.send_json({
                "type": "result", "step": "agent2_5", "data": scout_result
            })

            if "error" in scout_result:
                await ws.send_json({"type": "done"})
                continue

            # Step 3: Agent3
            await ws.send_json({"type": "status", "step": "agent3", "message": "Agent3 教学执行中..."})
            scout_content = scout_result.get("content", "")
            agent3_result = await run_with_history(
                query, scout_content, max_turns=2
            )

            await ws.send_json({
                "type": "result", "step": "agent3", "data": agent3_result
            })

            total_time = round(time.time() - t0, 1)
            await ws.send_json({
                "type": "done", "timing": {"step1": step1_time, "total": total_time}
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "step": "system", "message": str(e)})
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("claw.server.main:app", host="0.0.0.0", port=8080, reload=True)
