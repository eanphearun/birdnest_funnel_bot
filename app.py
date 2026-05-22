import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import os
import requests
from flask import Flask, request

TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
BIRD_BOT_LINK = "https://t.me/bird_nest_house_bot"   # your mini‑app

app = Flask(__name__)

# ---------- Lead scoring & qualification ----------
user_state = {}    # {chat_id: {"step": "ask_product", "score": 0, "answers": {}}}

SCORE_MAP = {
    "product": {"drink": 5, "dry_nest": 10, "gift": 8},
    "purpose": {"personal": 5, "resale": 20, "gift_purpose": 10},
    "budget": {"low": 5, "medium": 15, "high": 30},
    "location": {"pp": 10, "provinces": 5, "other": 5}
}

def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    requests.post(url, json=payload, timeout=10)

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    requests.post(url, json=payload, timeout=10)

def append_lead_to_sheet(first_name, product, purpose, budget, location, lead_score, hot, chat_id):
    try:
        creds_json = os.environ.get("GSPREAD_CREDENTIALS_JSON")
        if not creds_json:
            print("No GSPREAD_CREDENTIALS_JSON set")
            return
        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Bird Nest Leads").sheet1
        sheet.append_row([
            first_name,
            product,
            purpose,
            budget,
            location,
            lead_score,
            "HOT" if hot else "Cold",
            str(chat_id),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
    except Exception as e:
        print(f"Sheet error: {e}")

# ---------- Keyboards for each step ----------
def product_keyboard():
    return {"inline_keyboard": [
        [{"text": "🥤 ទឹកត្រចៀកកាំ (Drink)", "callback_data": "product_drink"}],
        [{"text": "🥚 ត្រចៀកកាំស្ងួត (Dry Nest)", "callback_data": "product_dry_nest"}],
        [{"text": "🎁 ឈុតអំណោយ (Gift Set)", "callback_data": "product_gift"}]
    ]}

def purpose_keyboard():
    return {"inline_keyboard": [
        [{"text": "ផ្ទាល់ខ្លួន", "callback_data": "purpose_personal"}],
        [{"text": "សម្រាប់លក់បន្ត", "callback_data": "purpose_resale"}],
        [{"text": "ជាអំណោយ", "callback_data": "purpose_gift_purpose"}]
    ]}

def budget_keyboard():
    return {"inline_keyboard": [
        [{"text": "ក្រោម $50", "callback_data": "budget_low"}],
        [{"text": "$50 - $200", "callback_data": "budget_medium"}],
        [{"text": "លើស $200", "callback_data": "budget_high"}]
    ]}

def location_keyboard():
    return {"inline_keyboard": [
        [{"text": "ភ្នំពេញ", "callback_data": "location_pp"}],
        [{"text": "ខេត្ត", "callback_data": "location_provinces"}],
        [{"text": "ផ្សេងៗ", "callback_data": "location_other"}]
    ]}

# ---------- Start the funnel ----------
def start_funnel(chat_id, first_name):
    user_state[chat_id] = {"step": "ask_product", "score": 0, "answers": {}}
    send_message(
        chat_id,
        f"👋 សួស្ដី {first_name}! អរគុណដែលចាប់អារម្មណ៍ផលិតផលរបស់យើង។\n\n"
        "ដើម្បីជួយអ្នកបានល្អបំផុត សូមឆ្លើយសំណួរខ្លីៗមួយចំនួន។",
        reply_markup=product_keyboard()
    )

# ---------- Process callback queries (all button presses) ----------
def handle_callback(callback):
    data = callback["data"]
    cb_id = callback["id"]
    msg = callback.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    user_info = callback.get("from", {})
    first_name = user_info.get("first_name", "អ្នក")

    if chat_id not in user_state:
        # Not in funnel – start it
        start_funnel(chat_id, first_name)
        answer_callback(cb_id)
        return

    state = user_state[chat_id]
    step = state["step"]

    # --- Product step ---
    if step == "ask_product" and data.startswith("product_"):
        product = data.split("_")[1]
        state["answers"]["product"] = product
        state["score"] += SCORE_MAP["product"].get(product, 0)
        state["step"] = "ask_purpose"
        send_message(chat_id, "តើអ្នកទិញសម្រាប់គោលបំណងអ្វី?", reply_markup=purpose_keyboard())
        answer_callback(cb_id)
        return

    # --- Purpose step ---
    if step == "ask_purpose" and data.startswith("purpose_"):
        purpose = data.split("_")[1] if data != "purpose_gift_purpose" else "gift_purpose"
        state["answers"]["purpose"] = purpose
        state["score"] += SCORE_MAP["purpose"].get(purpose, 0)
        state["step"] = "ask_budget"
        send_message(chat_id, "តើថវិការបស់អ្នកប្រហែលប៉ុន្មាន?", reply_markup=budget_keyboard())
        answer_callback(cb_id)
        return

    # --- Budget step ---
    if step == "ask_budget" and data.startswith("budget_"):
        budget = data.split("_")[1]
        state["answers"]["budget"] = budget
        state["score"] += SCORE_MAP["budget"].get(budget, 0)
        state["step"] = "ask_location"
        send_message(chat_id, "តើអ្នកស្ថិតនៅទីតាំងណា?", reply_markup=location_keyboard())
        answer_callback(cb_id)
        return

    # --- Location step (final) ---
    if step == "ask_location" and data.startswith("location_"):
        location = data.split("_")[1]
        state["answers"]["location"] = location
        state["score"] += SCORE_MAP["location"].get(location, 0)
        # Qualification complete – send summary to owner
        lead_score = state["score"]
        hot = lead_score >= 40
        summary = (
            f"📊 *អតិថិជនថ្មី (Lead)*\n"
            f"ឈ្មោះ: {first_name}\n"
            f"ផលិតផល: {state['answers'].get('product')}\n"
            f"គោលបំណង: {state['answers'].get('purpose')}\n"
            f"ថវិកា: {state['answers'].get('budget')}\n"
            f"ទីតាំង: {state['answers'].get('location')}\n"
            f"ពិន្ទុ: {lead_score} {('🔥 HOT' if hot else '🧊 Cold')}\n"
            f"User ID: `{chat_id}`"
        )
        send_message(OWNER_ID, summary, parse_mode="Markdown")

        append_lead_to_sheet(
            first_name,
            state['answers'].get('product'),
            state['answers'].get('purpose'),
            state['answers'].get('budget'),
            state['answers'].get('location'),
            lead_score,
            hot,
            chat_id
        )

        # Final message to user
        if hot:
            final_text = (
                "🔥 អរគុណ! អ្នកជាអតិថិជនដែលមានសក្តានុពលខ្ពស់។\n"
                "ម្ចាស់ហាងនឹងទាក់ទងអ្នកឆាប់ៗនេះ។\n\n"
                "👉 ឬអ្នកអាចចូលទៅបញ្ជាទិញដោយផ្ទាល់៖"
            )
        else:
            final_text = (
                "អរគុណ! យើងបានកត់ត្រាចំណាប់អារម្មណ៍របស់អ្នក។\n"
                "សូមចូលមើលហាងយើងសម្រាប់ព័ត៌មានបន្ថែម។\n\n"
                "👉 បើក Mini App ទិញទំនិញ៖"
            )
        send_message(
            chat_id,
            final_text,
            reply_markup={"inline_keyboard": [[{"text": "🛒 បើក Mini App", "url": BIRD_BOT_LINK}]]}
        )
        del user_state[chat_id]
        answer_callback(cb_id)
        return

    # Fallback
    answer_callback(cb_id)

# ---------- Webhook ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "callback_query" in data:
        handle_callback(data["callback_query"])
        return 'ok', 200

    msg = data.get("message", {})
    if msg:
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        user = msg.get("from", {})
        first_name = user.get("first_name", "អ្នក")

        # If user sends any text message, start the funnel
        start_funnel(chat_id, first_name)
        return 'ok', 200

    return 'ok', 200

@app.route('/')
def home():
    return 'Funnel Bot is running'