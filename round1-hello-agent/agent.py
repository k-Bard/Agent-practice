"""
Round 1: Hello Agent
Agent 的本质：observe → think → act → observe 循环
不是框架，是这个循环。
"""
import json, os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key"),
    base_url="https://api.deepseek.com/v1",
)

# 工具：安全的数学计算器
def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        return f"不允许的字符"
    try:
        return str(eval(expression))
    except Exception as e:
        return f"计算错误: {e}"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "执行数学计算，如 '2+3*4'、'(100-20)/2'",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式"}
            },
            "required": ["expression"],
        },
    },
}]

def run(user_input: str) -> str:
    messages = [{"role": "user", "content": user_input}]
    print(f"[User] {user_input}")

    while True:
        # think: LLM 决定下一步
        print("[Thinking...]")
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=TOOLS
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # act: 执行工具
            tc = msg.tool_calls[0]
            args = json.loads(tc.function.arguments)
            result = calculator(args["expression"])
            print(f"[Act] calculator({args['expression']}) -> {result}")

            # observe: 把结果喂回 LLM
            messages.append({"role": "assistant", "tool_calls": [tc]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            # 最终回复
            print(f"[Answer] {msg.content}")
            return msg.content


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        user_input = sys.argv[1]
    else:
        user_input = input("你: ")
    run(user_input)
