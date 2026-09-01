from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """أنت وسيم، مساعد ذكاء اصطناعي شخصي ومتعدد الاستخدامات.

تكيّف تلقائياً مع:
- لغة المستخدم وطريقة كلامه.
- سياق المحادثة السابقة.
- نوع المهمة التي يقوم بها.

كن ودوداً وطبيعياً في الدردشة.
كن دقيقاً ومنظماً في التقنية والبرمجة.
كن تعليمياً وواضحاً في الدراسة.
كن مبدعاً في الكتابة والأفكار.
لا تفرض شخصية واحدة أو أسلوباً ثابتاً على كل المحادثات.

إذا تحدث المستخدم باللهجة الجزائرية، يمكنك الرد بها بشكل طبيعي عندما يكون ذلك مناسباً.
لا تكرر اسم "وسيم" في كل رد.
لا تقل إنك مجرد نموذج لغوي إلا إذا كان السؤال متعلقاً بذلك.
"""


@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json(silent=True) or {}

    message = data.get("message", "").strip()

    if not message:
        return jsonify({
            "error": "الرسالة فارغة"
        }), 400


    # الحصول على سجل المحادثة من الواجهة
    history = data.get("messages", [])

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


    # إضافة المحادثة السابقة
    if isinstance(history, list):

        for item in history[-20:]:

            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content")

            if role in ["user", "assistant"] and content:

                messages.append({
                    "role": role,
                    "content": str(content)
                })


    # إضافة الرسالة الحالية
    messages.append({
        "role": "user",
        "content": message
    })


    if not GROQ_API_KEY:

        return jsonify({
            "error": "GROQ_API_KEY غير موجود"
        }), 500


    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }


    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": messages
    }


    try:

        response = requests.post(
            GROQ_URL,
            headers=headers,
            json=payload,
            timeout=60
        )

        result = response.json()


        if "choices" not in result:

            return jsonify({
                "error": result
            }), response.status_code or 500


        reply = (
            result["choices"][0]
            ["message"]
            ["content"]
        )


        return jsonify({
            "reply": reply
        })


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/")
def home():

    return "Wasim AI API is running."


if __name__ == "__main__":

    print("وسيم AI API شغال 🤖")

    app.run(
        host="127.0.0.1",
        port=5001
    )
