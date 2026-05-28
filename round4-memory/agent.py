"""
Round 4: Memory
核心：三层记忆的读写决策树

读写优先级（面试重点）：
  读: scratchpad → long-term → tool/ask_user
  写: 工具结果 → scratchpad(代码自动) | 用户信息 → long-term(LLM判断)

不该存的:
  临时计算值不进长期 | 大文件不进工作记忆 | 敏感明文不进任何记忆
"""
import json, os, datetime, sys
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key"),
    base_url="https://api.deepseek.com/v1",
)

# ===== 长期记忆存储 =====
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "long_term_memory.json")

def load_long_term_memory() -> dict:
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"user_profile": {}, "learned_facts": {}, "conversation_summaries": []}

def save_long_term_memory(data: dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== 工具实现 =====
def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        return "不允许的字符"
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

def save_to_memory(key: str, value: str) -> str:
    mem = load_long_term_memory()
    mem["learned_facts"][key] = value
    save_long_term_memory(mem)
    return f"[长期记忆] 已写入: {key} = {value}"

def recall_from_memory(key: str) -> str:
    mem = load_long_term_memory()
    if key in mem["learned_facts"]:
        return f"[长期记忆命中] {mem['learned_facts'][key]}"
    for k, v in mem["learned_facts"].items():
        if key in k or k in key:
            return f"[长期记忆模糊命中 {k}] {v}"
    if key in mem["user_profile"]:
        return f"[长期记忆命中] 偏好 {key}={mem['user_profile'][key]}"
    return "[长期记忆未命中]"

def save_user_preference(preference: str, value: str) -> str:
    mem = load_long_term_memory()
    mem["user_profile"][preference] = value
    save_long_term_memory(mem)
    return f"[长期记忆] 偏好已写入: {preference} = {value}"

# ===== 工具注册 =====
TOOLS = [
    {"type": "function", "function": {
        "name": "calculator", "description": "执行数学计算。当用户问题涉及数值计算时使用。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather", "description": "查询指定城市的实时天气。当用户询问某地天气、温度时使用。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称，如'北京'"}
        }, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "get_time", "description": "获取当前日期和时间。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search_knowledge", "description": "搜索内部知识库获取政策、规则、FAQ。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "save_to_memory",
        "description": "将信息存入长期记忆（跨会话持久化）。仅当用户明确说'记住'、分享了重要个人信息、或表达了可复用的偏好时才调用。不要存一次性计算结果。",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "记忆主题"},
            "value": {"type": "string", "description": "记忆内容"},
        }, "required": ["key", "value"]},
    }},
    {"type": "function", "function": {
        "name": "recall_from_memory",
        "description": "从长期记忆中检索。当用户问及可能在之前的对话中提过的信息时，先调用此工具。",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "检索关键词"}
        }, "required": ["key"]},
    }},
    {"type": "function", "function": {
        "name": "save_user_preference",
        "description": "记录用户偏好（长期记忆）。当用户表达喜好、习惯时会话结束后仍需要保留的信息时使用。",
        "parameters": {"type": "object", "properties": {
            "preference": {"type": "string", "description": "偏好名称"},
            "value": {"type": "string", "description": "偏好值"},
        }, "required": ["preference", "value"]},
    }},
]

TOOL_MAP = {
    "calculator": lambda a: calculator(a.get("expression", "")),
    "get_weather": lambda a: get_weather(a.get("city", "")),
    "get_time": lambda a: get_time(),
    "search_knowledge": lambda a: search_knowledge(a.get("query", "")),
    "save_to_memory": lambda a: save_to_memory(a.get("key", ""), a.get("value", "")),
    "recall_from_memory": lambda a: recall_from_memory(a.get("key", "")),
    "save_user_preference": lambda a: save_user_preference(a.get("preference", ""), a.get("value", "")),
}

# ===== 工作记忆 =====
SCRATCHPAD = {}

# ===== 记忆决策树 =====
MEMORY_SYSTEM = """你是一个有分层记忆的助手。记忆的读写遵循以下决策树：

[读决策] 需要信息时按此优先级：
  1. 工作记忆(scratchpad) — 同会话内已查过的结果，上下文中有
  2. 长期记忆(recall_from_memory) — 跨会话的用户信息/偏好
  3. 调用工具获取 — 以上都没有，首次查询
  4. 反问用户 — 工具也无法获取

[写决策] 存入信息时按此规则：
  执行层工具(calculator/get_weather/search_knowledge/get_time):
    → 结果自动进入工作记忆，不进长期（代码层自动处理，你不需要管）

  内存层工具(save_to_memory/save_user_preference):
    → 仅当以下情况之一成立时才调用:
      a) 用户明确说"记住"、"别忘了"、"存下来"
      b) 用户分享了身份信息（名字、手机、地址）
      c) 用户表达了持久偏好（"我喜欢XX"、"我一般用XX"）
    → 禁止调用的情况:
      a) 一次性计算结果（3+5=8不值得跨会话保留）
      b) 临时查询结果（今天天气、当前时间）
      c) 用户没有明确要求记住的闲聊内容

回复时不要使用emoji。"""

MAX_CONTEXT_LENGTH = 3000


def safe_print(s: str):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", errors="replace").decode("ascii"))


def compress_context(messages: list) -> list:
    if len(messages) <= 4:
        return messages
    early = messages[1:-4]
    safe_print("[Memory] Compressing context...")
    summary_prompt = "将以下对话压缩为一句话摘要：\n" + "\n".join(
        f"{m['role']}: {str(m.get('content', ''))[:100]}" for m in early
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": summary_prompt}],
    )
    summary = resp.choices[0].message.content
    safe_print(f"[Memory] Summary: {summary}")
    return [messages[0], {"role": "system", "content": f"[摘要] {summary}"}] + messages[-4:]


def check_scratchpad(tool_name: str, args: dict) -> str | None:
    """读决策第1步：检查工作记忆是否已有结果"""
    if tool_name == "get_weather":
        key = f"天气_{args.get('city', '')}"
        if key in SCRATCHPAD:
            return SCRATCHPAD[key]
    elif tool_name == "search_knowledge":
        key = f"知识_{args.get('query', '')}"
        if key in SCRATCHPAD:
            return SCRATCHPAD[key]
    elif tool_name == "calculator":
        expr = args.get("expression", "")
        if expr in SCRATCHPAD:
            return SCRATCHPAD[expr]
    return None


def classify_tool(tool_name: str) -> str:
    """分类工具类型，决定写入策略"""
    if tool_name in ("get_weather", "calculator", "search_knowledge", "get_time"):
        return "execution"  # 执行层 → 只写工作记忆
    if tool_name in ("save_to_memory", "save_user_preference"):
        return "memory_write"  # 记忆层 → 写长期记忆
    if tool_name == "recall_from_memory":
        return "memory_read"
    return "unknown"


def write_to_scratchpad(tool_name: str, args: dict, result: str):
    """写决策：执行层工具 → 自动写工作记忆"""
    if tool_name == "get_weather":
        SCRATCHPAD[f"天气_{args.get('city', '')}"] = result
    elif tool_name == "calculator":
        SCRATCHPAD[args.get("expression", "")] = result
    elif tool_name == "search_knowledge":
        SCRATCHPAD[f"知识_{args.get('query', '')}"] = result
    elif tool_name == "get_time":
        SCRATCHPAD["当前时间"] = result


def run(user_input: str) -> str:
    # 会话启动：加载长期记忆中的用户画像
    ltm = load_long_term_memory()
    profile_hint = ""
    if ltm.get("user_profile"):
        profile_hint = "已知用户偏好: " + ", ".join(
            f"{k}={v}" for k, v in ltm["user_profile"].items()
        )

    messages = [{"role": "system", "content": MEMORY_SYSTEM}]
    if profile_hint:
        messages.append({"role": "system", "content": f"[用户画像-长期记忆] {profile_hint}"})

    messages.append({"role": "user", "content": user_input})

    safe_print(f"[User] {user_input}")
    if profile_hint:
        safe_print(f"[Long-term] {profile_hint}")

    step = 0
    while True:
        step += 1
        safe_print(f"\n--- Step {step} ---")

        total_len = sum(len(str(m.get("content", ""))) for m in messages)
        if total_len > MAX_CONTEXT_LENGTH:
            messages = compress_context(messages)

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
                category = classify_tool(name)

                # === 读决策：先检查工作记忆 ===
                cached = check_scratchpad(name, args)
                if cached:
                    safe_print(f"[Memory] Scratchpad hit! Skip {name}, use cached: {cached}")
                    result = f"[来自工作记忆缓存] {cached}"
                else:
                    fn = TOOL_MAP.get(name)
                    result = fn(args) if fn else f"未知工具: {name}"
                    # === 写决策 ===
                    if category == "execution":
                        safe_print(f"[Write] {name} → scratchpad (auto)")
                        write_to_scratchpad(name, args, result)
                    elif category == "memory_write":
                        safe_print(f"[Write] {name} → long-term (LLM decided)")
                    elif category == "memory_read":
                        safe_print(f"[Read] {name} → searched long-term")

                safe_print(f"[Act] {name}({json.dumps(args, ensure_ascii=False)})")
                safe_print(f"[Result] {result}")
                tool_results.append((tc, result))

            messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
            for tc, result in tool_results:
                messages.append({
                    "role": "tool", "tool_call_id": tc.id, "content": result,
                })
        else:
            safe_print(f"\n[Final]\n{msg.content}")
            # 会话结束：自动归档摘要到长期记忆
            ltm = load_long_term_memory()
            ltm["conversation_summaries"].append({
                "time": get_time(),
                "user": user_input[:80],
                "answer": msg.content[:200],
            })
            if len(ltm["conversation_summaries"]) > 10:
                ltm["conversation_summaries"] = ltm["conversation_summaries"][-10:]
            save_long_term_memory(ltm)
            return msg.content


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        run(input("你: "))
