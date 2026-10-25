import tiktoken

class Tiktoken():
    
    def __init__(self,model = None):
        try:
            self.Tik_model = tiktoken.get_encoding(model or "cl100k_base")
        except Exception:
            self.Tik_model = None
            
    def 计算token(self,messages):
        if self.Tik_model is None:
            return{
                "error":"tiktoken 初始化失败"
            }
        total = 0
        for g in messages:
            total += len(self.Tik_model.encode(g.get("content") or " ")) + 2
        return{
            "token": int(total)
            }