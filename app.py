
import requests
import re
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template

# =========================
# CONFIG
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # 🔐 secure

app = Flask(__name__)

# =========================
# STATE
# =========================
user_state = {}
leads = []

# =========================
# GOOGLE SHEETS
# =========================
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os, json

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

sheet = None  # safe default

try:
    creds_json = os.getenv("GOOGLE_CREDS")

    # ✅ If env exists (Render)
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        print("✅ Using ENV credentials")

    # ✅ Else use local file (VS Code)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        print("✅ Using local credentials.json")

    client = gspread.authorize(creds)
    sheet = client.open("Chatbot Leads").sheet1
    print("✅ Google Sheets connected")

except Exception as e:
    print("❌ Google Sheets ERROR:", e)

# =========================
# GEMINI AI
# =========================
def ask_ai(question, relevant_info):
    if not relevant_info.strip():
        return "I'm not sure about that. Please contact support."

    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""
You are a helpful assistant.

Answer using ONLY the information below.

IMPORTANT:
- Always give COMPLETE sentences
- Keep answer short (1-2 lines)

Information:
{relevant_info}

Question:
{question}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 200,
            "temperature": 0.3
        }
    }

    try:
        res = requests.post(url, json=payload, timeout=15)
        data = res.json()

        if "error" in data:
            print("GEMINI ERROR:", data["error"])
            return "AI not working. Please try again."

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("ERROR:", e)
        return "Server busy. Try again."

# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/leads")
def leads_page():
    data = sheet.get_all_records()
    return render_template("leads.html", leads=data)

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json["message"]
    user_id = "default"

    if user_id not in user_state:
        user_state[user_id] = {
            "name": None,
            "phone": None,
            "awaiting_name": False,
            "awaiting_phone": False
        }

    state = user_state[user_id]
    q = user_msg.lower()

    # =========================
    # BASIC RESPONSES
    # =========================
    if q in ["hi", "hello", "hey"]:
        return jsonify({"reply": "Hi 👋 How can I help you today?"})

    if "how are you" in q:
        return jsonify({"reply": "I'm doing great! How can I help you today?"})

    # =========================
    # NAME
    # =========================
    if state["awaiting_name"]:
        invalid_names = ["ok", "okay", "hi", "hello", "yes", "no"]

        name = user_msg.strip().lower()

        if name in invalid_names:
            return jsonify({"reply": "Please enter your actual name."})

        if 2 <= len(user_msg) <= 30 and user_msg.replace(" ", "").isalpha():
            formatted_name = user_msg.title()

            state["name"] = formatted_name
            state["awaiting_name"] = False
            state["awaiting_phone"] = True
            leads.append({"name": formatted_name})

            return jsonify({"reply": f"Nice to meet you, {formatted_name}! Share phone number."})

        return jsonify({"reply": "Please enter a valid name."})

    # =========================
    # PHONE
    # =========================
    if state["awaiting_phone"]:

        if not state["name"]:
            state["awaiting_phone"] = False
            state["awaiting_name"] = True
            return jsonify({"reply": "Please enter your name first."})

        phone = user_msg.replace(" ", "").replace("+91", "")

        if re.fullmatch(r"[6-9]\d{9}", phone):

            if leads:
                leads[-1]["phone"] = phone

            if sheet:
                try:
                    sheet.append_row([
                        state["name"],
                        phone,
                        "New Lead",
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Website Chatbot"
                    ])
                except Exception as e:
                    print("Sheet error:", e)

            state["awaiting_phone"] = False
            state["awaiting_name"] = False
            state["name"] = None

            return jsonify({"reply": "Thanks! We will contact you soon."})

        return jsonify({"reply": "Enter valid phone number."})

    # =========================
    # RULE-BASED
    # =========================
    # fees FIRST
    if "fee" in q or "price" in q or "cost" in q:
        return jsonify({"reply": "The fee for each course is ₹10,000."})

    # then course
    if "course" in q:
        return jsonify({"reply": "We offer Python, Java, and Data Science courses."})

    if "time" in q:
        return jsonify({"reply": "Classes run from 9 AM to 6 PM."})

    if "demo" in q:
        state["awaiting_name"] = True
        return jsonify({"reply": "We offer demo classes.\n\nMay I know your name?"})

    # =========================
    # AI FALLBACK
    # =========================
    with open("knowledge.txt", "r", encoding="utf-8") as f:
        knowledge = f.read()

    relevant = get_relevant_info(user_msg, knowledge)

    if not relevant.strip():
        return jsonify({
            "reply": "I can help with courses, fees, timings, and demo classes. What would you like to know?"
        })

    reply = ask_ai(user_msg, relevant)
    return jsonify({"reply": reply})

# =========================
# RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)