import os
import re
import fitz  # PyMuPDF
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
import sys
import io

sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1. 环境配置
os.environ["HUGGINGFACEHUB_API_TOKEN"] = "sk-"


# 2. 定义状态
class State(TypedDict):
    messages: Annotated[list, add_messages]


# 3. 初始化 Qwen 模型
endpoint_llm = HuggingFaceEndpoint(
    repo_id="Qwen/Qwen2.5-72B-Instruct",
    task="conversational",
    max_new_tokens=1024,
)
llm = ChatHuggingFace(llm=endpoint_llm)


# 4. 法律文件处理工具
class LawFileTool:
    def __init__(self, directory):
        self.directory = directory

    def search_and_parse(self, keyword: str, target_clause: str = None):
        """搜索 PDF 并解析特定条文"""
        # 在文件夹中匹配文件
        files = [f for f in os.listdir(self.directory) if keyword in f and f.endswith('.pdf')]
        if not files:
            return f"未找到包含 '{keyword}' 的法律文件。"

        file_path = os.path.join(self.directory, files[0])
        doc = fitz.open(file_path)
        full_text = "".join([page.get_text() for page in doc])
        doc.close()

        #
        # 使用正则分条（匹配：第x条）
        clauses = re.split(r'(?=\n第[一二三四五六七八九十百]+条)', full_text)

        if target_clause:
            # 搜索特定条文
            for c in clauses:
                if target_clause in c:
                    return f"已在《{files[0]}》中找到：\n{c.strip()}"
            return f"文件中未找到 {target_clause}。"

        # 如果没指定条文，返回前3条作为预览
        return f"已找到文件《{files[0]}》，共有 {len(clauses)} 条。前3条预览：\n" + "\n".join(clauses[:3])


law_tool = LawFileTool(directory="/Users/lxj/Documents/Law")


# 5. 定义节点逻辑
def chatbot_node(state: State):
    system_msg = SystemMessage(content=(
        "你是一个法律助手。用户要求解析法律时，你必须：\n"
        "1. 将阿拉伯数字转换为中文大写数字（如：将32改为三十二）。\n"
        "2. 严格按此格式回复：[PARSE_LAW:文件名关键字,第XX条]。\n"
        "例如用户说：'解析反洗钱法第32条'，你回复：'[PARSE_LAW:反洗钱,第三十二条]'。"
    ))
    response = llm.invoke([system_msg, state["messages"][-1]])
    return {"messages": [response]}


def tool_executor_node(state: State):
    last_content = state["messages"][-1].content

    # 模拟工具：天气
    if "[QUERY_WEATHER:" in last_content:
        city = last_content.split("[QUERY_WEATHER:")[1].split("]")[0]
        return {"messages": [AIMessage(content=f"{city}天气晴朗。")]}

    # 核心工具：法律解析
    if "[PARSE_LAW:" in last_content:
        # 解析参数，例如 [PARSE_LAW:反洗钱,第三十二条]
        params = last_content.split("[PARSE_LAW:")[1].split("]")[0].split(",")
        keyword = params[0]
        target = params[1] if len(params) > 1 else None

        result = law_tool.search_and_parse(keyword, target)
        return {"messages": [AIMessage(content=result)]}

    return {"messages": []}


# 6. 构建图
workflow = StateGraph(State)
workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools", tool_executor_node)
workflow.add_edge(START, "chatbot")


def route_decision(state: State):
    content = state["messages"][-1].content
    if "[QUERY_WEATHER:" in content or "[PARSE_LAW:" in content:
        return "tools"
    return END


workflow.add_conditional_edges("chatbot", route_decision)
workflow.add_edge("tools", END)
app = workflow.compile()

# 7. 运行
if __name__ == "__main__":
    print("--- 法律解析助手已就绪 ---")
    while True:
        sys.stdout.write("\nUser: ")
        sys.stdout.flush()
        raw_data = sys.stdin.buffer.readline()
        u_input = raw_data.decode('utf-8', errors='ignore').strip()
        if u_input.lower() == 'q': break
        for event in app.stream({"messages": [HumanMessage(content=u_input)]}):
            for value in event.values():
                print(f"Assistant: {value['messages'][-1].content}")