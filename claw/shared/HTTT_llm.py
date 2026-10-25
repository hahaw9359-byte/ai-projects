import httpx
import asyncio
import json
from  dotenv import load_dotenv
from .tik_token import Tiktoken


import os

load_dotenv()


class LLM_client():
    def __init__(self,api_key = None, URL = None,model = None,maxtoken = 5000,limit_token = 30000, reasoning_effort = None):
        try:
            self.api_key = api_key or os.getenv("Deepseek_key")
            self.url = URL or "https://api.deepseek.com/v1/chat/completions"
            self.model = model or "deepseek-v4-pro"
            self.client = httpx.AsyncClient()
            self.max_token = maxtoken
            self.limit_token = limit_token
            self.reasoning_effort = reasoning_effort
            self.tiktoken = Tiktoken()
            
        except Exception:
            self.skill_content = None
            self.api_key = None
            self.url = None
            self.model = None
            self.client = None 
            
    async def close(self):
        if self.client is not None:
            await self.client.aclose()

    async def send(self, message, tools=None, max_retries: int = 2):
        # 1. token 预估
        预估token = self.tiktoken.计算token(message)
        if isinstance(预估token, dict) and "error" in 预估token:
            return {"error": "tiktoken_failed", "detail": 预估token["error"]}

        prompt_token = 预估token["token"] + self.max_token
        if prompt_token > self.limit_token:
            return {
                "error": "token_limit_exceeded",
                "detail": f"预估 {prompt_token} 超过限制 {self.limit_token}"
            }

        # 2. 构造请求
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": message,
            "max_tokens": self.max_token
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if tools is not None:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 3. 发送请求，带重试降级
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.post(
                    self.url,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                return self._parse_response(response)

            except httpx.TimeoutException as e:
                last_error = {"error": "timeout", "detail": str(e), "attempt": attempt + 1}
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                return last_error

            except httpx.RequestError as e:
                # 网络层错误：DNS 失败、连接被拒绝、TLS 握手失败等
                last_error = {"error": "network_error", "detail": str(e), "attempt": attempt + 1}
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                return last_error

            except Exception as e:
                # 未知异常，不重试，直接返回
                return {"error": "unknown_error", "detail": str(e), "attempt": attempt + 1}

        return last_error

    def _parse_response(self, response):
        # 4. 先检查 HTTP 状态码
        if response.status_code >= 500:
            return {
                "error": "server_error",
                "detail": f"远程服务器错误: {response.text[:200]}",
                "status_code": response.status_code
            }

        if response.status_code == 401:
            return {"error": "auth_error", "detail": "api key 无效或已过期", "status_code": 401}

        if response.status_code == 429:
            return {"error": "rate_limited", "detail": "请求过于频繁", "status_code": 429}

        if response.status_code != 200:
            return {
                "error": "http_error",
                "detail": response.text[:200],
                "status_code": response.status_code
            }

        # 5. 解析 JSON
        try:
            data = response.json()
        except ValueError:
            return {"error": "json_decode_error", "detail": "LLM 返回非 JSON 数据", "raw": response.text[:200]}

        # 6. 提取字段，带兜底
        try:
            choices = data.get("choices") or []
            if not choices:
                return {"error": "empty_choices", "detail": "LLM 返回 choices 为空"}

            message_obj = choices[0].get("message", {})
            contents = message_obj.get("content") or ""
            tool_calls = message_obj.get("tool_calls")
            reasoning = message_obj.get("reasoning_content") or ""
            tokens = data.get("usage", {})

            return {
                "content": contents,
                "prompt_token": tokens.get("prompt_tokens", 0),
                "completion_token": tokens.get("completion_tokens", 0),
                "reasoning_len": len(reasoning),
                "tool_calls": tool_calls
            }
        except Exception as e:
            return {"error": "field_extract_error", "detail": f"字段提取失败: {str(e)}", "raw": data}