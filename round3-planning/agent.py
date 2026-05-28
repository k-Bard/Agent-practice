"""
Round 3: Planning
核心：Plan-and-Execute — LLM 先拆任务列计划，再分步执行，失败时 re-plan

与 Round 2 的区别：
  Round 2: think → act → think → act (交错进行，无全局规划)
  Round 3: plan → execute step 1 → execute step 2 → ... → synthesize
"""
import json, os, datetime, sys
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key"),
    base_url="https://api.deepseek.com/v1",
)

# ===== 工具实现（同 Round 2）=====
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

TOOLS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "执行数学计算。当用户问题涉及数值计算时使用。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '(100-20)*0.8'"}
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气。当用户询问某地天气、温度时使用。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称，如'北京'"}
        }, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "get_time",
        "description": "获取当前日期和时间。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "搜索内部知识库获取政策、规则、FAQ。当用户询问退货规则、发货时效等问题时使用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词，如'退货政策'"}
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "translate",
        "description": "将中文文本翻译为其他语言。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要翻译的文本"},
            "target_lang": {"type": "string", "description": "目标语言，如'英文'、'日文'"},
        }, "required": ["text"]},
    }},
]

TOOL_MAP = {
    "calculator": lambda a: calculator(a.get("expression", "")),
    "get_weather": lambda a: get_weather(a.get("city", "")),
    "get_time": lambda a: get_time(),
    "search_knowledge": lambda a: search_knowledge(a.get("query", "")),
    "translate": lambda a: translate(a.get("text", ""), a.get("target_lang", "英文")),
}

# ===== Planning Prompt（Round 3 的核心）=====
PLANNER_SYSTEM = """你是一个任务规划专家。收到用户请求后，先制定分步计划，再逐步执行。

规划规则：
1. 将复杂任务拆解为独立的步骤，每个步骤对应一个工具调用或一个分析决策
2. 能并行的步骤同时调用（如同时查两个城市的天气）
3. 有依赖关系的步骤必须串行（Step 2 需要 Step 1 的结果）
4. 每个步骤说明目的和预期工具

当所有工具调用完成后，综合结果生成清晰的中文回复。

如果某步骤返回 FAILED，调整剩余计划后继续，不要重复已成功的步骤。"""


def safe_print(s: str):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", errors="replace").decode("ascii"))


def run(user_input: str) -> str:
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": user_input},
    ]
    safe_print(f"[User] {user_input}\n")

    step = 0
    while True:
        step += 1
        safe_print(f"--- Step {step} ---")
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=TOOLS
        )
        msg = resp.choices[0].message

        if msg.content:
            safe_print(f"[Think] {msg.content[:200]}...")

        if msg.tool_calls:
            tool_results = []
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                fn = TOOL_MAP.get(name)
                result = fn(args) if fn else f"未知工具: {name}"
                safe_print(f"[Act] {name}({json.dumps(args, ensure_ascii=False)})")
                safe_print(f"[Result] {result}")
                tool_results.append((tc, result))

            messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
            for tc, result in tool_results:
                status = "SUCCESS" if "错误" not in result and "未找到" not in result else "FAILED"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[{status}] {result}\n如果此步骤失败，请在继续前调整计划。",
                })
        else:
            safe_print(f"\n[Final Answer]\n{msg.content}")
            return msg.content


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        run(input("你: "))
