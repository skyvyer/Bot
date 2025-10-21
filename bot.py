import os
import sqlite3
from datetime import datetime
from dateutil import parser as dtparser
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.getenv("TELEGRAM_TOKEN",)
DB = "tasks.db"

bot = telebot.TeleBot(TOKEN)
scheduler = BackgroundScheduler()
scheduler.start()

REMINDER_DAYS = [7, 3, 1, 0]

SUBJECTS = [
    "Иностранный язык",
    "Информатика",
    "История России",
    "ЛинАл",
    "МатАнал",
    "ОРГ",
    "Физика",
    "Химия",
    "Экономика"
]

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ===
def init_db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            telegram_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            description TEXT,
            deadline TEXT,
            task_type TEXT,
            created_by INTEGER,
            notified TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requirements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            text TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS semester_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            text TEXT
        )
    """)
    conn.commit()
    return conn

conn = init_db()
cur = conn.cursor()

# === ВСПОМОГАТЕЛЬНЫЕ ===
def parse_date(text):
    try:
        return dtparser.parse(text, dayfirst=True)
    except Exception:
        return None

def add_task(subject, description, deadline, task_type, created_by):
    cur.execute(
        "INSERT INTO tasks(subject, description, deadline, task_type, created_by) VALUES (?,?,?,?,?)",
        (subject, description, deadline, task_type, created_by)
    )
    conn.commit()

def get_all_tasks():
    cur.execute("SELECT id, subject, description, deadline, task_type FROM tasks ORDER BY deadline")
    return cur.fetchall()

def get_upcoming_tasks(days=7):
    now = datetime.utcnow()
    cur.execute("SELECT subject, description, deadline, task_type FROM tasks")
    result = []
    for subj, desc, dl, ttype in cur.fetchall():
        try:
            deadline = dtparser.parse(dl)
        except Exception:
            continue
        if 0 <= (deadline - now).days <= days:
            result.append((subj, desc, deadline, ttype))
    result.sort(key=lambda x: x[2])
    return result

# === МЕНЮ ===
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ Добавить задание", "📋 Показать все")
    markup.row("📆 Ближайшие дедлайны")
    markup.row("📚 Требования преподавателей", "🗓 Задания на семестр")
    return markup

# === /START ===
@bot.message_handler(commands=['start'])
def start(msg):
    cur.execute("INSERT OR IGNORE INTO users(telegram_id, username) VALUES (?,?)",
                (msg.from_user.id, msg.from_user.username))
    conn.commit()
    bot.send_message(
        msg.chat.id,
        "Привет! 👋\nЯ помогу тебе не забывать о дедлайнах и условиях для автомата.\n\nВыбери действие:",
        reply_markup=main_menu()
    )

# === ДОБАВЛЕНИЕ ЗАДАНИЙ ===
user_states = {}

@bot.message_handler(func=lambda m: m.text == "➕ Добавить задание")
def add_task_start(msg):
    user_states[msg.chat.id] = {'step': 'subject', 'data': {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for i in range(0, len(SUBJECTS), 3):
        markup.row(*SUBJECTS[i:i+3])
    markup.row("⬅️ Отмена")
    bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in SUBJECTS)
def select_subject(msg):
    if msg.chat.id not in user_states or user_states[msg.chat.id].get('step') != 'subject':
        return
    state = user_states[msg.chat.id]
    state['data']['subject'] = msg.text
    state['step'] = 'description'
    bot.send_message(msg.chat.id, "Введите описание задания (или '-' если нет):")

@bot.message_handler(func=lambda m: m.text == "⬅️ Отмена")
def cancel(msg):
    if msg.chat.id in user_states:
        del user_states[msg.chat.id]
    bot.send_message(msg.chat.id, "❌ Добавление отменено.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.chat.id in user_states)
def add_task_flow(msg):
    state = user_states[msg.chat.id]
    step = state['step']
    text = msg.text.strip()

    if step == 'description':
        state['data']['description'] = text if text != '-' else ''
        state['step'] = 'deadline'
        bot.send_message(msg.chat.id, "Введите дедлайн (например, 25.10.2025 23:59):")

    elif step == 'deadline':
        dt = parse_date(text)
        if not dt:
            bot.send_message(msg.chat.id, "❌ Не понял дату. Попробуй ещё раз (например, 25.10.2025 23:59).")
            return
        state['data']['deadline'] = dt.isoformat()
        state['step'] = 'type'
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("Домашнее", "Лабораторная", "Контрольная")
        bot.send_message(msg.chat.id, "Выберите тип задания:", reply_markup=markup)

    elif step == 'type':
        subject = state['data']['subject']
        desc = state['data']['description']
        deadline = state['data']['deadline']
        task_type = text
        add_task(subject, desc, deadline, task_type, msg.from_user.id)
        del user_states[msg.chat.id]
        bot.send_message(msg.chat.id, f"✅ Задание по <b>{subject}</b> добавлено!", parse_mode="HTML", reply_markup=main_menu())

# === ТРЕБОВАНИЯ ПРЕПОДОВ ===
@bot.message_handler(func=lambda m: m.text == "📚 Требования преподавателей")
def requirements_menu(msg):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ Добавить требование", "📄 Показать требования")
    markup.row("⬅️ Назад")
    bot.send_message(msg.chat.id, "📚 Раздел: требования преподавателей", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "➕ Добавить требование")
def add_requirement(msg):
    user_states[msg.chat.id] = {'step': 'req_subject', 'data': {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for i in range(0, len(SUBJECTS), 3):
        markup.row(*SUBJECTS[i:i+3])
    markup.row("⬅️ Отмена")
    bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id]['step'] == 'req_subject' and m.text in SUBJECTS)
def req_subject(msg):
    user_states[msg.chat.id]['data']['subject'] = msg.text
    user_states[msg.chat.id]['step'] = 'req_text'
    bot.send_message(msg.chat.id, "Введите требования / условия для автомата:")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id]['step'] == 'req_text')
def req_text(msg):
    data = user_states[msg.chat.id]['data']
    cur.execute("INSERT INTO requirements(subject, text) VALUES (?,?)", (data['subject'], msg.text))
    conn.commit()
    del user_states[msg.chat.id]
    bot.send_message(msg.chat.id, "✅ Требование добавлено!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "📄 Показать требования")
def show_requirements(msg):
    cur.execute("SELECT subject, text FROM requirements ORDER BY subject")
    rows = cur.fetchall()
    if not rows:
        bot.send_message(msg.chat.id, "Пока нет сохранённых требований.")
        return
    text = "📚 <b>Требования преподавателей:</b>\n\n"
    for subj, t in rows:
        text += f"📘 <b>{subj}</b>\n{t}\n\n"
    bot.send_message(msg.chat.id, text, parse_mode="HTML")

# === ЗАДАНИЯ НА СЕМЕСТР ===
@bot.message_handler(func=lambda m: m.text == "🗓 Задания на семестр")
def sem_menu(msg):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ Добавить семестровое задание", "📄 Показать все семестровые")
    markup.row("⬅️ Назад")
    bot.send_message(msg.chat.id, "🗓 Раздел: задания на семестр", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "➕ Добавить семестровое задание")
def add_sem_task(msg):
    user_states[msg.chat.id] = {'step': 'sem_subject', 'data': {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for i in range(0, len(SUBJECTS), 3):
        markup.row(*SUBJECTS[i:i+3])
    markup.row("⬅️ Отмена")
    bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id]['step'] == 'sem_subject' and m.text in SUBJECTS)
def sem_subject(msg):
    user_states[msg.chat.id]['data']['subject'] = msg.text
    user_states[msg.chat.id]['step'] = 'sem_text'
    bot.send_message(msg.chat.id, "Введите задание на семестр по этому предмету:")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id]['step'] == 'sem_text')
def sem_text(msg):
    data = user_states[msg.chat.id]['data']
    cur.execute("INSERT INTO semester_tasks(subject, text) VALUES (?,?)", (data['subject'], msg.text))
    conn.commit()
    del user_states[msg.chat.id]
    bot.send_message(msg.chat.id, "✅ Семестровое задание добавлено!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "📄 Показать все семестровые")
def show_sem_tasks(msg):
    cur.execute("SELECT subject, text FROM semester_tasks ORDER BY subject")
    rows = cur.fetchall()
    if not rows:
        bot.send_message(msg.chat.id, "Пока нет сохранённых заданий на семестр.")
        return
    text = "🗓 <b>Задания на семестр:</b>\n\n"
    for subj, t in rows:
        text += f"📘 <b>{subj}</b>\n{t}\n\n"
    bot.send_message(msg.chat.id, text, parse_mode="HTML")

# === КНОПКА НАЗАД ===
@bot.message_handler(func=lambda m: m.text == "⬅️ Назад")
def back(msg):
    bot.send_message(msg.chat.id, "Возвращаюсь в главное меню:", reply_markup=main_menu())

# === НАПОМИНАНИЯ ===
def check_deadlines():
    now = datetime.utcnow()
    cur.execute("SELECT id, subject, description, deadline, task_type, notified FROM tasks")
    for tid, subj, desc, dl, ttype, notified in cur.fetchall():
        try:
            deadline = dtparser.parse(dl)
        except Exception:
            continue
        days_left = (deadline - now).total_seconds() / 86400
        for d in REMINDER_DAYS:
            key = f"d{d}"
            if key not in (notified or '') and d - 0.5 < days_left <= d + 0.01:
                cur.execute("SELECT telegram_id FROM users")
                for (uid,) in cur.fetchall():
                    try:
                        bot.send_message(
                            uid,
                            f"⏰ Напоминание: <b>{subj}</b> ({ttype})\n"
                            f"До дедлайна ≈ {d} дн.\n"
                            f"🕓 {deadline.strftime('%d.%m.%Y %H:%M')}\n"
                            f"{desc}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                notified = (notified or '') + key + ';'
                cur.execute("UPDATE tasks SET notified=? WHERE id=?", (notified, tid))
                conn.commit()

scheduler.add_job(check_deadlines, 'interval', minutes=10)

# === ЗАПУСК ===
if __name__ == "__main__":
    print("✅ Бот запущен!")
    bot.infinity_polling()
