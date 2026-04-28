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

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Chatbot Leads").sheet1

# =========================
# RETRIEVAL
# =========================
def get_relevant_info(question, knowledge):
    lines = knowledge.split("\n")

    keywords_map = {
        "course": ["course", "courses"],
        "fees": ["fee", "fees", "price", "cost"],
        "demo": ["demo", "trial"],
        "time": ["time", "timing", "schedule"]
    }

    q = question.lower()
    matched_keywords = []

    for key, words in keywords_map.items():
        for w in words:
            if w in q:
                matched_keywords.append(key)

    relevant = []

    for line in lines:
        for key in matched_keywords:
            if key in line.lower():
                relevant.append(line)
                break

    return "\n".join(relevant)

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

    # =========================
    # NAME
    # =========================
    if state["awaiting_name"]:

        invalid_names = ["ok", "okay", "hi", "hello", "yes", "no", "hmm", "cool"]

        name = user_msg.strip().lower()

        # ❌ reject common chat words
        if name in invalid_names:
            return jsonify({"reply": "Please enter your actual name."})

        # ✅ validate proper name
        if 2 <= len(user_msg) <= 30 and user_msg.replace(" ", "").isalpha():
            formatted_name = user_msg.title()

            state["name"] = formatted_name
            state["awaiting_name"] = False
            state["awaiting_phone"] = True
            leads.append({"name": formatted_name})

            return jsonify({"reply": f"Nice to meet you, {formatted_name}! Share phone number."})

        return jsonify({"reply": "Please enter a valid name (only letters)."})

    # =========================
    # PHONE
    # =========================
    if state["awaiting_phone"]:

        # safety
        if not state["name"]:
            state["awaiting_phone"] = False
            state["awaiting_name"] = True
            return jsonify({"reply": "Please enter your name first."})

        # normalize phone
        phone = user_msg.replace(" ", "").replace("+91", "")

        if re.fullmatch(r"[6-9]\d{9}", phone):

            if leads:
                leads[-1]["phone"] = phone

            sheet.append_row([
                state["name"],
                phone,
                "New Lead",
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Website Chatbot"
            ])

            # reset
            state["awaiting_phone"] = False
            state["awaiting_name"] = False
            state["name"] = None
            state["phone"] = None

            return jsonify({"reply": "Thanks! We will contact you soon."})

        return jsonify({"reply": "Enter valid phone number."})


    # =========================
    # RULE-BASED
    # =========================
    q = user_msg.lower()

    if "course" in q:
        return jsonify({"reply": "We offer Python, Java, and Data Science courses."})

    if "fee" in q or "price" in q or "cost" in q:
        return jsonify({"reply": "The fee for each course is ₹10,000."})

    if "time" in q:
        return jsonify({"reply": "Classes run from 9 AM to 6 PM."})

    if "demo" in q:
        state["awaiting_name"] = True
        state["awaiting_phone"] = False
        state["name"] = None

        return jsonify({
            "reply": "We offer demo classes on weekends.\n\nMay I know your name?"
        })


    # =========================
    # AI (fallback)
    # =========================
    with open("knowledge.txt", "r", encoding="utf-8") as f:
        knowledge = f.read()

    relevant = get_relevant_info(user_msg, knowledge)

    if not relevant.strip():
        return jsonify({"reply": "I'm not sure about that. Please contact support."})

    reply = ask_ai(user_msg, relevant)

    return jsonify({"reply": reply})

# =========================
# RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)