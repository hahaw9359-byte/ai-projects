from .tool.tik_token import Tiktoken
import json
from dotenv import load_dotenv
import os
import requests

skill_path = r"C:\Users\49523\复习\需求反推知识点\claw\onboarding\SKILL.md"
with open(skill_path, "r", encoding="utf-8") as f:
    skill_content = f.read()
load_dotenv()

class Request():
    def __init__(
        self,
        model = None,
        api_key = None,
        URL = None,
        max_token = 10000,
        limit_token = 20000
        ):
        try:
            self.tiktoken = Tiktoken(model)  # 初始化tiktoken类，传入model参数
            self.api_key = api_key  or os.getenv("Deepseek_key")  # 获取API Key
            self.ual = URL or "https://api.deepseek.com/v1/chat/completions"
            self.max_token = max_token  # 最大token数
            self.limit_token = limit_token  # 限制token数
        except Exception:
            self.tiktoken = None
            self.api_key = None
            self.ual = None
            self.max_token = None
            self.limit_token = None
    
    def 发送(self,query):
        if self.api_key is None or self.ual is None :
                return [{"error": "API Key 或 UAL 未初始化 或 tiktoken 初始化失败"}]
        message = [
                {"role": "system", "content": skill_content},
                {"role": "user", "content": f"计算之后得json内容{query}"}
            ]  
        预估token = self.tiktoken.计算token(message)
        if isinstance(预估token, dict) and "error" in 预估token:
            return [{"error": f"tiktoken 初始化失败: {预估token['error']}"}]
        prompt_token = 预估token["token"] + self.max_token
        if prompt_token > self.limit_token:
            return [{"error": "token爆炸无法发送"}]
        headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
        }
        payload = {
                    "model": "deepseek-v4-flash",
                    "temperature": 0.3,
                    "messages": message,
                    "max_tokens": self.max_token,
        }
        try:
            response = requests.post(self.ual, headers=headers, json=payload, timeout=(3, 120))
            data = response.json()
            if response.status_code ==200:
                contents = (data.get("choices") or [{}])[0].get("message", {}).get("content") or "无内容"
                tokens = data.get("usage", {})
                prompt_token = tokens.get("prompt_tokens", 0)
                completion_token = tokens.get("completion_tokens", 0)
                tool_calls = (data.get("choices") or [{}])[0].get("message",{}).get("tool_calls") or None
                return {
                    "content": contents,
                    "prompt_token": prompt_token,
                     "completion_token": completion_token,
                      "tool_calls": tool_calls
                 }
            else:
                 return [{"error": f"请求发送失败: {response.text[:200]}"}]
        except requests.exceptions.ReadTimeout:
             return [{"error":"服务器相应太慢超时"}]
        except requests.exceptions.Timeout:
               return [{"error": "请求超时"}]
        except requests.exceptions.RequestException as e:
              return [{"error":f"出错了:{str(e)}"}]
