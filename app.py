from flask import Flask, render_template, request, jsonify, redirect
import sqlite3
from datetime import datetime, timedelta
import requests

app = Flask(__name__)

# Razorpay Test Key
RAZORPAY_KEY_ID = "rzp_test_NhQFMV57BI5o45"

# Smart Plug API URL
SMART_PLUG_URL = "https://www.virtualsmarthome.xyz/url_routine_trigger/activate.php?trigger=d613829d-a350-476b-b520-15e33c3d39f5&token=965a8bd9-75b5-4963-99dc-c2bc65767c17&response=json"

# Initialize SQLite DB
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            phone TEXT PRIMARY KEY,
            expiry_date DATE,
            daily_usage INTEGER DEFAULT 0,
            last_used_date DATE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plug_status (
            id INTEGER PRIMARY KEY DEFAULT 1,
            last_activation_time DATETIME
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO plug_status (id, last_activation_time) VALUES (1, '2000-01-01 00:00:00')")
    conn.commit()
    conn.close()

init_db()

# Helper: Check if subscription is active
def is_subscription_active(phone):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM customers WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return False
    expiry_date = datetime.strptime(result[0], "%Y-%m-%d").date()
    return expiry_date >= datetime.now().date()

# Helper: Get plug status
def get_plug_status():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT last_activation_time FROM plug_status WHERE id = 1")
    result = cursor.fetchone()
    conn.close()
    if not result:
        return {"active": False}
    last_activation = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
    time_elapsed = datetime.now() - last_activation
    active = time_elapsed.total_seconds() < 1800  # 30 minutes
    minutes_left = max(0, 30 - int(time_elapsed.total_seconds() / 60))
    return {"active": active, "minutes_left": minutes_left}

# Routes
@app.route("/")
def home():
    return render_template("index.html", razorpay_key=RAZORPAY_KEY_ID)

@app.route("/check_subscription", methods=["POST"])
def check_subscription():
    phone = request.form.get("phone")
    active = is_subscription_active(phone)
    return jsonify({"active": active})

@app.route("/activate_plug", methods=["POST"])
def activate_plug():
    phone = request.form.get("phone")
    if not is_subscription_active(phone):
        return jsonify({"success": False, "message": "Subscription expired"})

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT daily_usage, last_used_date FROM customers WHERE phone = ?", (phone,))
    user = cursor.fetchone()
    today = datetime.now().date()

    # Reset daily count if new day
    if user and user[1] != today.strftime("%Y-%m-%d"):
        cursor.execute("UPDATE customers SET daily_usage = 0, last_used_date = ? WHERE phone = ?", (today, phone))
        conn.commit()

    # Check daily limit
    cursor.execute("SELECT daily_usage FROM customers WHERE phone = ?", (phone,))
    daily_usage = cursor.fetchone()[0]
    if daily_usage >= 2:
        conn.close()
        return jsonify({"success": False, "message": "Daily limit reached (2 uses per day)"})

    # Check if plug is already in use
    plug_status = get_plug_status()
    if plug_status["active"]:
        conn.close()
        return jsonify({"success": False, "message": f"Plug in use. Time left: {plug_status['minutes_left']} minutes"})

    # Activate plug
    requests.get(SMART_PLUG_URL)

    # Update DB
    cursor.execute("UPDATE plug_status SET last_activation_time = ? WHERE id = 1", (datetime.now(),))
    cursor.execute("UPDATE customers SET daily_usage = daily_usage + 1, last_used_date = ? WHERE phone = ?", (today, phone))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Smart Plug Activated for 30 minutes!"})

@app.route("/create_order", methods=["POST"])
def create_order():
    plan = request.form.get("plan")
    phone = request.form.get("phone")
    plan_prices = {"daily": 7900, "weekly": 14900, "monthly": 19900}  # in paise
    return jsonify({
        "amount": plan_prices[plan],
        "plan": plan,
        "phone": phone
    })

@app.route("/handle_payment", methods=["POST"])
def handle_payment():
    phone = request.form.get("phone")
    plan = request.form.get("plan")
    plan_days = {"daily": 1, "weekly": 7, "monthly": 30}

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM customers WHERE phone = ?", (phone,))
    result = cursor.fetchone()

    if result:
        expiry_date = datetime.strptime(result[0], "%Y-%m-%d")
    else:
        expiry_date = datetime.now()

    new_expiry = expiry_date + timedelta(days=plan_days[plan])
    cursor.execute("""
        INSERT INTO customers (phone, expiry_date) VALUES (?, ?)
        ON CONFLICT(phone) DO UPDATE SET expiry_date = ?
    """, (phone, new_expiry.strftime("%Y-%m-%d"), new_expiry.strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()

    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)