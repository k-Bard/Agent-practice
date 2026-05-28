"""
Round 2: Tools
核心：Tool Description 设计 + 多工具调度
LLM 从 5 个工具中自主选择——什么时候调哪个，全看 description
"""
import json, os, datetime, sys
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key"),
    base_url="https://api.deepseek.com/v1",
)

# ===== 工具实现 =====
def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        return f"不允许的字符"
    try:
        return str(eval(expression))
    except Exception as e:
        return f"计算错误: {e}"

def get_weather(city: str) -> str:
    data = {"北京": "晴 28°C", "上海": "阴 25°C", "深圳": "雨 30°C"}
    return data.get(city, f"{city}: 多云 22°C")

def get_time(_unused: str = "") -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def search_knowledge(query: str) -> str:
    kb = {
        "退货": "7天内可申请退货，需保持商品完好，退款1-3个工作日到账",
        "发货": "16:00前下单当天发货，全国3-5天送达",
        "支付": "支持微信、支付宝、花呗分期，满500免息",
    }
    for k, v in kb.items():
        if k in query:
            return v
    return f"未找到与'{query}'相关的知识"

def translate(text: str, target_lang: str = "英文") -> str:
    mock_trans = {
        ("你好", "英文"): "Hello",
        ("谢谢", "英文"): "Thank you",
        ("再见", "英文"): "Goodbye",
    }
    return mock_trans.get((text, target_lang), f"[{target_lang}翻译] {text}")

# ===== 工具注册 =====
# 关键：description 决定了 LLM 能否在正确时机选中这个工具
TOOLS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "执行数学计算，支持加减乘除、括号、百分比。当用户问题涉及数值计算时使用。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '(100-20)*0.8'"}
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气。当用户询问某地天气、温度、是否下雨时使用。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称，如'北京'"}
        }, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "get_time",
        "description": "获取当前日期和时间。当用户问现在几点、今天几号时使用。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "搜索内部知识库，获取政策、规则、FAQ等信息。当用户询问退货规则、发货时效、支付方式等政策问题时使用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词，如'退货政策'、'发货时间'"}
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "translate",
        "description": "将中文文本翻译为其他语言。当用户要求翻译某段文字时使用。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要翻译的文本"},
            "target_lang": {"type": "string", "description": "目标语言，如'英文'、'日文'"},
        }, "required": ["text"]},
    }},
]

# ===== 工具调度器 =====
TOOL_MAP = {
    "calculator": lambda args: calculator(args.get("expression", "")),
    "get_weather": lambda args: get_weather(args.get("city", "")),
    "get_time": lambda args: get_time(),
    "search_knowledge": lambda args: search_knowledge(args.get("query", "")),
    "translate": lambda args: translate(args.get("text", ""), args.get("target_lang", "英文")),
}


def safe_print(s: str):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", errors="replace").decode("ascii"))


def run(user_input: str) -> str:
    messages = [
        {"role": "system", "content": "你是一个有用的助手。回复时不要使用emoji。"},
        {"role": "user", "content": user_input},
    ]
    safe_print(f"[User] {user_input}")

    while True:
        safe_print("[Thinking...]")
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=TOOLS
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                fn = TOOL_MAP.get(name)
                if fn:
                    result = fn(args)
                    safe_print(f"[Act] {name}({json.dumps(args, ensure_ascii=False)})")
                else:
                    result = f"未知工具: {name}"
                    safe_print(f"[Act] UNKNOWN: {name}")

            messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                fn = TOOL_MAP.get(name)
                result = fn(args) if fn else "未知工具"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            safe_print(f"[Answer] {msg.content}")
            return msg.content


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        run(input("你: "))
