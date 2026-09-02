from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import psycopg2
import jwt

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta, timezone


# =========================
# إعدادات التطبيق
# =========================

load_dotenv()

app = Flask(__name__)

CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET")

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


# =========================
# قاعدة البيانات
# =========================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL غير موجود")

    return psycopg2.connect(DATABASE_URL)


def init_db():

    if not DATABASE_URL:
        print("تحذير: DATABASE_URL غير موجود، سيتم تشغيل API بدون قاعدة بيانات.")
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL DEFAULT 'محادثة جديدة',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL
                REFERENCES conversations(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    conn.commit()

    cur.close()
    conn.close()

    print("PostgreSQL جاهز ✅")


# =========================
# JWT
# =========================

def create_token(user_id, username):

    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET غير موجود")

    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=30)
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm="HS256"
    )


def get_current_user():

    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):
        return None

    token = auth.split(" ", 1)[1].strip()

    if not token:
        return None

    if not JWT_SECRET:
        return None

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"]
        )

        return payload

    except jwt.ExpiredSignatureError:

        return None

    except jwt.InvalidTokenError:

        return None


def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        user = get_current_user()

        if not user:
            return jsonify({
                "error": "يجب تسجيل الدخول"
            }), 401

        return function(user, *args, **kwargs)

    return wrapper


# =========================
# إنشاء قاعدة البيانات
# =========================

try:
    init_db()
except Exception as e:
    print("خطأ في PostgreSQL:", e)


# =========================
# تسجيل حساب جديد
# =========================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True) or {}

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if len(username) < 3:
        return jsonify({
            "error": "اسم المستخدم يجب أن يكون 3 أحرف على الأقل"
        }), 400

    if len(username) > 50:
        return jsonify({
            "error": "اسم المستخدم طويل جداً"
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
        }), 400

    if not DATABASE_URL:
        return jsonify({
            "error": "قاعدة البيانات غير متصلة"
        }), 500

    try:

        password_hash = generate_password_hash(password)

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
            RETURNING id, username
        """, (username, password_hash))

        user_id, saved_username = cur.fetchone()

        conn.commit()

        cur.close()
        conn.close()

        token = create_token(
            user_id,
            saved_username
        )

        return jsonify({
            "message": "تم إنشاء الحساب بنجاح",
            "token": token,
            "user": {
                "id": user_id,
                "username": saved_username
            }
        }), 201

    except psycopg2.errors.UniqueViolation:

        if 'conn' in locals():
            conn.rollback()
            conn.close()

        return jsonify({
            "error": "اسم المستخدم موجود من قبل"
        }), 409

        print("REGISTER ERROR:", repr(e), flush=True)

        if 'conn' in locals():
            try:
                conn.rollback()
                conn.close()
            except:
                pass

        return jsonify({
            "error": "حدث خطأ أثناء إنشاء الحساب"
        }), 500


# =========================
# تسجيل الدخول
# =========================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json(silent=True) or {}

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:

        return jsonify({
            "error": "اسم المستخدم وكلمة المرور مطلوبان"
        }), 400

    if not DATABASE_URL:

        return jsonify({
            "error": "قاعدة البيانات غير متصلة"
        }), 500

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, password_hash
            FROM users
            WHERE username = %s
        """, (username,))

        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user:

            return jsonify({
                "error": "اسم المستخدم أو كلمة المرور غير صحيحة"
            }), 401

        user_id, saved_username, password_hash = user

        if not check_password_hash(
            password_hash,
            password
        ):

            return jsonify({
                "error": "اسم المستخدم أو كلمة المرور غير صحيحة"
            }), 401

        token = create_token(
            user_id,
            saved_username
        )

        return jsonify({
            "message": "تم تسجيل الدخول بنجاح",
            "token": token,
            "user": {
                "id": user_id,
                "username": saved_username
            }
        })

    except Exception:

        return jsonify({
            "error": "حدث خطأ أثناء تسجيل الدخول"
        }), 500


# =========================
# معلومات المستخدم الحالي
# =========================

@app.route("/me", methods=["GET"])
@login_required
def me(user):

    return jsonify({
        "user": {
            "id": user["user_id"],
            "username": user["username"]
        }
    })


# =========================
# جلب محادثات المستخدم
# =========================

@app.route("/conversations", methods=["GET"])
@login_required
def conversations(user):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, created_at, updated_at
        FROM conversations
        WHERE user_id = %s
        ORDER BY updated_at DESC
    """, (user["user_id"],))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    result = []

    for row in rows:

        result.append({
            "id": row[0],
            "title": row[1],
            "created_at": row[2].isoformat(),
            "updated_at": row[3].isoformat()
        })

    return jsonify({
        "conversations": result
    })


# =========================
# جلب محادثة واحدة
# =========================

@app.route("/conversations/<int:conversation_id>", methods=["GET"])
@login_required
def get_conversation(user, conversation_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title
        FROM conversations
        WHERE id = %s
        AND user_id = %s
    """, (conversation_id, user["user_id"]))

    conversation = cur.fetchone()

    if not conversation:

        cur.close()
        conn.close()

        return jsonify({
            "error": "المحادثة غير موجودة"
        }), 404

    cur.execute("""
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY id ASC
    """, (conversation_id,))

    messages = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        "conversation": {
            "id": conversation[0],
            "title": conversation[1],
            "messages": [
                {
                    "role": row[0],
                    "content": row[1],
                    "created_at": row[2].isoformat()
                }
                for row in messages
            ]
        }
    })


# =========================
# حذف محادثة
# =========================

@app.route("/conversations/<int:conversation_id>", methods=["DELETE"])
@login_required
def delete_conversation(user, conversation_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM conversations
        WHERE id = %s
        AND user_id = %s
    """, (conversation_id, user["user_id"]))

    deleted = cur.rowcount

    conn.commit()

    cur.close()
    conn.close()

    if deleted == 0:

        return jsonify({
            "error": "المحادثة غير موجودة"
        }), 404

    return jsonify({
        "message": "تم حذف المحادثة"
    })


# =========================
# Chat
# =========================

@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json(silent=True) or {}

    message = data.get("message", "").strip()

    if not message:

        return jsonify({
            "error": "الرسالة فارغة"
        }), 400

    history = data.get("messages", [])

    # المستخدم الحالي إذا كان مسجل الدخول
    user = get_current_user()

    conversation_id = data.get("conversation_id")

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    # =========================
    # سجل المحادثة للـAI
    # =========================

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

    # منع تكرار الرسالة الحالية
    if not messages or messages[-1].get("content") != message:

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

        # =========================
        # حفظ المحادثة إذا المستخدم
        # مسجل الدخول
        # =========================

        if user:

            conn = get_db()
            cur = conn.cursor()

            # إذا عندنا conversation_id
            if conversation_id:

                cur.execute("""
                    SELECT id
                    FROM conversations
                    WHERE id = %s
                    AND user_id = %s
                """, (
                    conversation_id,
                    user["user_id"]
                ))

                exists = cur.fetchone()

                if not exists:
                    conversation_id = None

            # إنشاء محادثة جديدة
            if not conversation_id:

                title = message[:80]

                cur.execute("""
                    INSERT INTO conversations
                    (user_id, title)
                    VALUES (%s, %s)
                    RETURNING id
                """, (
                    user["user_id"],
                    title
                ))

                conversation_id = cur.fetchone()[0]

            # حفظ رسالة المستخدم
            cur.execute("""
                INSERT INTO messages
                (conversation_id, role, content)
                VALUES (%s, %s, %s)
            """, (
                conversation_id,
                "user",
                message
            ))

            # حفظ رد الذكاء الاصطناعي
            cur.execute("""
                INSERT INTO messages
                (conversation_id, role, content)
                VALUES (%s, %s, %s)
            """, (
                conversation_id,
                "assistant",
                reply
            ))

            cur.execute("""
                UPDATE conversations
                SET updated_at = NOW()
                WHERE id = %s
            """, (conversation_id,))

            conn.commit()

            cur.close()
            conn.close()

        return jsonify({
            "reply": reply,
            "conversation_id": conversation_id
        })

    except Exception as e:

        print("Chat error:", e)

        return jsonify({
            "error": str(e)
        }), 500


# =========================
# الصفحة الرئيسية
# =========================

@app.route("/")
def home():

    return "Wasim AI API is running."


# =========================
# تشغيل محلي
# =========================

if __name__ == "__main__":

    print("وسيم AI API شغال 🤖")

    app.run(
        host="127.0.0.1",
        port=5001
    )
