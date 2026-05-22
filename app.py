import os
import time
import json
import requests
from flask import Flask, request
from datetime import datetime
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
BIRD_BOT_LINK = "https://t.me/bird_nest_house_bot"
GSPREAD_CREDENTIALS_JSON = os.environ.get("GSPREAD_CREDENTIALS_JSON", "")
SHEET_NAME = os.environ.get("SHEET_NAME", "Bird Nest Leads")

app = Flask(__name__)

user_state = {}
SCORE_MAP = {
    "product": {"drink": 5, "dry_nest": 10, "gift": 8},
    "purpose": {"personal": 5, "resale": 20, "gift_purpose": 10},
    "budget": {"low": 5, "medium": 15, "high": 30},
    "location": {"pp": 10, "provinces": 5, "other": 5}
}

# ---------- Helpers ----------
def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return requests.post(url, json=payload, timeout=10).json()

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    requests.post(url, json=payload, timeout=10)

def get_sheet():
    if not GSPREAD_CREDENTIALS_JSON:
        return None
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(GSPREAD_CREDENTIALS_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def append_lead_to_sheet(first_name, product, purpose, budget, location, lead_score, hot, chat_id):
    try:
        sheet = get_sheet()
        if not sheet:
            print("Sheet not available")
            return
        sheet.append_row([
            first_name, product, purpose, budget, location,
            lead_score, "HOT" if hot else "Cold", str(chat_id),
            datetime.now(pytz.timezone('Asia/Phnom_Penh')).strftime("%Y-%m-%d %H:%M:%S")
        ])
    except Exception as e:
        print(f"Sheet error: {e}")

def get_all_chat_ids():
    sheet = get_sheet()
    if not sheet:
        return []
    records = sheet.get_all_values()
    ids = set()
    for row in records[1:]:
        if len(row) > 7 and row[7].isdigit():
            ids.add(int(row[7]))
    return list(ids)

# ---------- Keyboards ----------
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

# ---------- Funnel start ----------
def start_funnel(chat_id, first_name):
    user_state[chat_id] = {"step": "ask_product", "score": 0, "answers": {}}
    send_message(
        chat_id,
        f"👋 សួស្ដី {first_name}! អរគុណដែលចាប់អារម្មណ៍ផលិតផលរបស់យើង។\n\n"
        "ដើម្បីជួយអ្នកបានល្អបំផុត សូមឆ្លើយសំណួរខ្លីៗមួយចំនួន។",
        reply_markup=product_keyboard()
    )

# ---------- Callback handling ----------
def handle_callback(callback):
    data = callback["data"]
    cb_id = callback["id"]
    msg = callback.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    user_info = callback.get("from", {})
    first_name = user_info.get("first_name", "អ្នក")

    if chat_id not in user_state:
        start_funnel(chat_id, first_name)
        answer_callback(cb_id)
        return

    state = user_state[chat_id]
    step = state["step"]

    # --- Product ---
    if step == "ask_product" and data.startswith("product_"):
        product = data.split("_")[1]
        state["answers"]["product"] = product
        state["score"] += SCORE_MAP["product"].get(product, 0)
        state["step"] = "ask_purpose"
        send_message(chat_id, "តើអ្នកទិញសម្រាប់គោលបំណងអ្វី?", reply_markup=purpose_keyboard())
        answer_callback(cb_id)
        return

    # --- Purpose ---
    if step == "ask_purpose" and data.startswith("purpose_"):
        purpose = data.split("_")[1] if data != "purpose_gift_purpose" else "gift_purpose"
        state["answers"]["purpose"] = purpose
        state["score"] += SCORE_MAP["purpose"].get(purpose, 0)
        state["step"] = "ask_budget"
        send_message(chat_id, "តើថវិការបស់អ្នកប្រហែលប៉ុន្មាន?", reply_markup=budget_keyboard())
        answer_callback(cb_id)
        return

    # --- Budget ---
    if step == "ask_budget" and data.startswith("budget_"):
        budget = data.split("_")[1]
        state["answers"]["budget"] = budget
        state["score"] += SCORE_MAP["budget"].get(budget, 0)
        state["step"] = "ask_location"
        send_message(chat_id, "តើអ្នកស្ថិតនៅទីតាំងណា?", reply_markup=location_keyboard())
        answer_callback(cb_id)
        return

    # --- Location (final) ---
    if step == "ask_location" and data.startswith("location_"):
        location = data.split("_")[1]
        state["answers"]["location"] = location
        state["score"] += SCORE_MAP["location"].get(location, 0)

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

    answer_callback(cb_id)

# ---------- Owner broadcast commands (added to funnel bot) ----------
def handle_owner_command(chat_id, text):
    if chat_id != OWNER_ID:
        return False

    parts = text.split(" ", 1)
    cmd = parts[0].lower()

    if cmd == "/broadcast" and len(parts) > 1:
        message_text = parts[1]
        user_ids = get_all_chat_ids()
        if not user_ids:
            send_message(chat_id, "No leads found in the sheet.")
            return True

        send_message(chat_id, f"Starting broadcast to {len(user_ids)} users...")
        success, failed = 0, 0
        for uid in user_ids:
            try:
                res = send_message(uid, message_text)
                if res.get("ok"):
                    success += 1
                else:
                    failed += 1
            except:
                failed += 1
            time.sleep(0.05)
        send_message(chat_id, f"Broadcast finished: {success} sent, {failed} failed.")
        return True

    if cmd == "/list":
        user_ids = get_all_chat_ids()
        send_message(chat_id, f"Total leads: {len(user_ids)}")
        return True

    if cmd == "/help" or cmd == "/start":
        send_message(chat_id,
            "Commands:\n"
            "/broadcast <message> – send promo to all leads\n"
            "/list – show lead count\n"
            "/help – this message"
        )
        return True

    return False

# ---------- Webhook ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    # 1) Callback queries (inline buttons)
    if "callback_query" in data:
        handle_callback(data["callback_query"])
        return 'ok', 200

    # 2) Normal message
    msg = data.get("message", {})
    if msg:
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()

        # Check for owner commands first
        if handle_owner_command(chat_id, text):
            return 'ok', 200

        # Otherwise, start funnel
        user = msg.get("from", {})
        first_name = user.get("first_name", "អ្នក")
        start_funnel(chat_id, first_name)
        return 'ok', 200

    return 'ok', 200

@app.route('/')
def home():
    return 'Funnel Bot is running'