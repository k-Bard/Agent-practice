"""
Round 5: Reflection
核心：自检纠错闭环 — 输出前检查，发现问题自动修正

与 Round 4 的区别：
  Round 4: 生成即输出，不检查
  Round 5: 生成 → 反思自检 → 发现问题 → 修正 → 再检 → 通过才输出

两种模式（面试重点）：
  Self-Critique: 同一个 LLM 自检（成本低，但有盲区）
  Verifier: 独立 prompt 校验（更客观，成本翻倍）
  本实现选择 Self-Critique 模式——适合大多数场景
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

TOOLS = [
    {"type": "function", "function": {
        "name": "calculator", "description": "执行数学计算。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather", "description": "查询指定城市的实时天气。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称"}
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
        "description": "将重要信息存入长期记忆。仅当用户明确说'记住'时调用。",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "记忆主题"},
            "value": {"type": "string", "description": "记忆内容"},
        }, "required": ["key", "value"]},
    }},
    {"type": "function", "function": {
        "name": "recall_from_memory", "description": "从长期记忆中检索信息。",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "检索关键词"}
        }, "required": ["key"]},
    }},
    {"type": "function", "function": {
        "name": "save_user_preference", "description": "记录用户的偏好设置。",
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

SCRATCHPAD = {}
MAX_CONTEXT_LENGTH = 3000
MAX_REFLECTION_ROUNDS = 2


def safe_print(s: str):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", errors="replace").decode("ascii"))


# ===== Reflection 系统提示词（Round 5 核心）=====
REFLECTION_PROMPT = """你是输出质检员，严格审查以下回复。

审查维度：
1. 准确性：数值计算是否正确？事实是否准确？
2. 完整性：是否回答了用户的所有问题？（最容易漏）
3. 一致性：回复内部有无自相矛盾之处？
4. 实用性：用户能否直接使用这个回复？是否遗漏了关键信息？

输出 JSON（严格此格式）：
{"passed": true/false, "issues": ["问题1", "问题2"], "fix": "具体修改建议"}"""


def compress_context(messages: list) -> list:
    if len(messages) <= 4:
        return messages
    early = messages[1:-4]
    safe_print("[Memory] Compressing...")
    summary_prompt = "压缩为一句话摘要：\n" + "\n".join(
        f"{m['role']}: {str(m.get('content', ''))[:100]}" for m in early
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": summary_prompt}],
    )
    summary = resp.choices[0].message.content
    return [messages[0], {"role": "system", "content": f"[摘要] {summary}"}] + messages[-4:]


def check_scratchpad(tool_name: str, args: dict) -> str | None:
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
    if tool_name in ("get_weather", "calculator", "search_knowledge", "get_time"):
        return "execution"
    if tool_name in ("save_to_memory", "save_user_preference"):
        return "memory_write"
    if tool_name == "recall_from_memory":
        return "memory_read"
    return "unknown"


def write_to_scratchpad(tool_name: str, args: dict, result: str):
    if tool_name == "get_weather":
        SCRATCHPAD[f"天气_{args.get('city', '')}"] = result
    elif tool_name == "calculator":
        SCRATCHPAD[args.get("expression", "")] = result
    elif tool_name == "search_knowledge":
        SCRATCHPAD[f"知识_{args.get('query', '')}"] = result
    elif tool_name == "get_time":
        SCRATCHPAD["当前时间"] = result


def reflect(answer: str, user_query: str, tool_context: str) -> dict:
    """Reflection 阶段：检查输出质量"""
    check_prompt = f"""原始用户请求：{user_query}

工具调用结果：
{tool_context}

待审查的回复：
{answer}

请审查以上回复。输出 JSON。"""

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": REFLECTION_PROMPT},
            {"role": "user", "content": check_prompt},
        ],
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {"passed": True, "issues": [], "fix": ""}


def collect_tool_context(messages: list) -> str:
    ctx = []
    for m in messages:
        if m["role"] == "tool":
            ctx.append(m.get("content", "")[:200])
        elif m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                try:
                    name = tc.function.name
                    args = tc.function.arguments
                except AttributeError:
                    name = tc["function"]["name"]
                    args = tc["function"]["arguments"]
                ctx.append(f"调用 {name}({args})")
    return "\n".join(ctx[-10:])


AGENT_SYSTEM = """你是一个严谨的助手。回答用户问题时：
1. 完整回答用户的所有子问题，不要遗漏
2. 涉及计算时，使用 calculator 工具，不要心算
3. 得出答案后自检一遍

回复时不要使用emoji。"""


def run(user_input: str) -> str:
    ltm = load_long_term_memory()
    profile_hint = ""
    if ltm.get("user_profile"):
        profile_hint = "已知用户偏好: " + ", ".join(
            f"{k}={v}" for k, v in ltm["user_profile"].items()
        )

    messages = [{"role": "system", "content": AGENT_SYSTEM}]
    if profile_hint:
        messages.append({"role": "system", "content": f"[用户画像] {profile_hint}"})
    messages.append({"role": "user", "content": user_input})

    safe_print(f"[User] {user_input}")
    if profile_hint:
        safe_print(f"[Profile] {profile_hint}")

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
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                category = classify_tool(name)

                cached = check_scratchpad(name, args)
                if cached:
                    safe_print(f"[Memory] Scratchpad hit, skip {name}")
                    result = f"[缓存] {cached}"
                else:
                    fn = TOOL_MAP.get(name)
                    result = fn(args) if fn else f"未知工具: {name}"
                    if category == "execution":
                        write_to_scratchpad(name, args, result)
                    elif category == "memory_write":
                        safe_print(f"[Write] {name} -> long-term")

                safe_print(f"[Act] {name}({json.dumps(args, ensure_ascii=False)})")
                safe_print(f"[Result] {result[:100]}")

            messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                fn = TOOL_MAP.get(name)
                result = fn(args) if fn else "未知工具"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            # === Reflection 阶段 ===
            answer = msg.content
            tool_ctx = collect_tool_context(messages)

            for ref_round in range(MAX_REFLECTION_ROUNDS):
                safe_print(f"\n[Reflection Round {ref_round + 1}]")
                check = reflect(answer, user_input, tool_ctx)

                if check.get("passed", True):
                    safe_print("[Reflection] PASSED")
                    break
                else:
                    issues = check.get("issues", [])
                    fix = check.get("fix", "")
                    safe_print(f"[Reflection] FAILED: {'; '.join(issues)}")
                    safe_print(f"[Reflection] Fix: {fix}")

                    correction_prompt = f"""上一轮回复存在问题：
{chr(10).join(f'- {i}' for i in issues)}

修改建议：{fix}

请修正你的回复。"""
                    messages.append({"role": "user", "content": correction_prompt})

                    resp2 = client.chat.completions.create(
                        model="deepseek-chat", messages=messages, tools=TOOLS
                    )
                    msg2 = resp2.choices[0].message

                    if msg2.tool_calls:
                        for tc in msg2.tool_calls:
                            name = tc.function.name
                            args = json.loads(tc.function.arguments)
                            fn = TOOL_MAP.get(name)
                            result = fn(args) if fn else "未知工具"
                            safe_print(f"[Fix Act] {name}({json.dumps(args, ensure_ascii=False)})")
                            safe_print(f"[Fix Result] {result[:100]}")
                        messages.append({"role": "assistant", "tool_calls": msg2.tool_calls})
                        for tc in msg2.tool_calls:
                            name = tc.function.name
                            args = json.loads(tc.function.arguments)
                            fn = TOOL_MAP.get(name)
                            result = fn(args) if fn else "未知工具"
                            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                        break  # 继续 agent 循环
                    else:
                        answer = msg2.content
                        tool_ctx = collect_tool_context(messages)

            safe_print(f"\n[Final]\n{answer}")

            ltm = load_long_term_memory()
            ltm["conversation_summaries"].append({
                "time": get_time(),
                "user": user_input[:80],
                "answer": answer[:200],
            })
            if len(ltm["conversation_summaries"]) > 10:
                ltm["conversation_summaries"] = ltm["conversation_summaries"][-10:]
            save_long_term_memory(ltm)
            return answer


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        run(input("你: "))
