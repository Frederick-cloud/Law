import os
from google import genai

# 设置你的 API Key
os.environ["HUGGINGFACEHUB_API_TOKEN"] = "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"

# 初始化最新的客户端
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

try:
    for m in client.models.list():
        print(f"可用模型名: {m.name}")
except Exception as e:
    print(f"API Error: {e}")