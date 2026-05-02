import random
import sqlite3
import asyncio
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler,
    ContextTypes
)

# ================== НАСТРОЙКИ ==================

TELEGRAM_BOT_TOKEN = "ВСТАВЬ_НОВЫЙ_ТОКЕН"

ADMIN_USERNAMES = ["baby_illusion", "borzata174"]
MIN_MESSAGES_TO_PLAY = 30

TRIGGER_WORDS = ["привет", "как ты", "салам"]
REPLY_WORDS = ["Привет 👋", "Салам 🤝", "Здорова 😎"]

WAITING_NUMBERS = 1
WAITING_VIP_NUMBERS = 2

CHELYABINSK_WIN_PHRASES = [
    "✅ Чётко, братан! Ты сегодня главный на районе!",
    "💰 Бабки в карман! Ты порвал бингу!",
    "🏧 Респект тебе, бро!",
    "🦾 Никто не ожидал, а ты выиграл!",
    "🍻 Сегодня твой день!"
]

# ================== БАЗА ДАННЫХ ==================

class Database:
    def __init__(self, db_file="bot_data.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            vip INTEGER DEFAULT 0,
            reputation INTEGER DEFAULT 0,
            donations INTEGER DEFAULT 0,
            msg_count_total INTEGER DEFAULT 0
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            banned_at TEXT,
            reason TEXT
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            username TEXT
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchangers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            username TEXT
        )
        """)

        self.conn.commit()

    # ---------- USERS ----------

    def ensure_user(self, user_id, username):
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
            (user_id, username)
        )
        self.cursor.execute(
            "UPDATE users SET username=? WHERE user_id=?",
            (username, user_id)
        )
        self.conn.commit()

    def inc_msg(self, user_id):
        self.cursor.execute(
            "UPDATE users SET msg_count_total=msg_count_total+1 WHERE user_id=?",
            (user_id,)
        )
        self.conn.commit()

    def get_msg(self, user_id):
        self.cursor.execute(
            "SELECT msg_count_total FROM users WHERE user_id=?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def add_win(self, user_id):
        self.cursor.execute(
            "UPDATE users SET wins=wins+1, games_played=games_played+1 WHERE user_id=?",
            (user_id,)
        )
        self.conn.commit()

    def add_game(self, user_id):
        self.cursor.execute(
            "UPDATE users SET games_played=games_played+1 WHERE user_id=?",
            (user_id,)
        )
        self.conn.commit()

    def get_stats(self, user_id):
        self.cursor.execute(
            "SELECT wins, games_played, vip, reputation, msg_count_total FROM users WHERE user_id=?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return row if row else (0, 0, 0, 0, 0)

    # ---------- VIP ----------

    def set_vip(self, user_id, value=True):
        self.cursor.execute(
            "UPDATE users SET vip=? WHERE user_id=?",
            (1 if value else 0, user_id)
        )
        self.conn.commit()

    def is_vip(self, user_id):
        self.cursor.execute(
            "SELECT vip FROM users WHERE user_id=?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return row and row[0] == 1

    # ---------- BAN ----------

    def ban_user(self, user_id, reason=None):
        self.cursor.execute(
            "INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason) VALUES (?,?,?)",
            (user_id, datetime.now().isoformat(), reason)
        )
        self.conn.commit()

    def unban_user(self, user_id):
        self.cursor.execute(
            "DELETE FROM banned_users WHERE user_id=?",
            (user_id,)
        )
        self.conn.commit()

    def is_banned(self, user_id):
        self.cursor.execute(
            "SELECT 1 FROM banned_users WHERE user_id=?",
            (user_id,)
        )
        return self.cursor.fetchone() is not None

db = Database()

# ================== ГЛОБАЛЬНЫЕ ==================

players = {}
game_active = False
game_vip_mode = False
bingo_history = []
history_msg_id = None
progress_msg_id = None 
# ================== КЛАВИАТУРЫ ==================

def permanent_keyboard():
    keyboard = [
        [KeyboardButton("🛍️ Магазины"), KeyboardButton("💱 Обменники")],
        [KeyboardButton("📜 Правила"), KeyboardButton("❓ VIP статус")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def game_keyboard():
    keyboard = [
        [KeyboardButton("🎰 БИНГО"), KeyboardButton("🛍️ Магазины")],
        [KeyboardButton("💱 Обменники"), KeyboardButton("📜 Правила")],
        [KeyboardButton("❓ VIP статус")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def private_keyboard():
    keyboard = [
        [KeyboardButton("👤 Мой профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ================== ВСПОМОГАТЕЛЬНЫЕ ==================

async def delete_message_after(context, chat_id, message_id, delay=20):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except:
        pass

def get_random_count():
    r = random.random() * 100
    if r < 65: return 1
    elif r < 85: return 2
    elif r < 93: return 3
    elif r < 98: return 4
    else: return 5

# ================== АДМИН-КОМАНДЫ ==================

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    keyboard = [
        [InlineKeyboardButton("🎲 Обычная (5 чисел)", callback_data="game_normal")],
        [InlineKeyboardButton("👑 VIP (4 числа)", callback_data="game_vip")]
    ]

    await update.message.reply_text(
        "Выберите тип игры:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    global game_active, players, bingo_history
    game_active = False
    players.clear()
    bingo_history.clear()

    await update.message.reply_text(
        "⏹️ Игра остановлена.",
        reply_markup=permanent_keyboard()
    )

# ================== CALLBACK ==================

async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    global game_active, game_vip_mode, players, bingo_history

    if query.data == "game_normal":
        game_vip_mode = False
    elif query.data == "game_vip":
        game_vip_mode = True

    if query.data in ("game_normal", "game_vip"):
        game_active = True
        players.clear()
        bingo_history.clear()

        numbers_count = 4 if game_vip_mode else 5
        mode_text = "VIP" if game_vip_mode else "Обычная"

        await query.message.edit_text(
            f"🎲 {mode_text} игра началась!\n\n"
            f"Участники загадывают {numbers_count} чисел от 1 до 100.\n"
            f"Нажмите «🎰 БИНГО» для участия.",
        )

# ================== БИНГО ==================

async def bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    if not game_active:
        await update.message.reply_text("Игра не активна.")
        return

    if not players:
        await update.message.reply_text("Нет участников.")
        return

    count = get_random_count()
    numbers = [random.randint(1, 100) for _ in range(count)]
    numbers_str = ", ".join(map(str, numbers))

    await update.message.reply_text(f"🎲 Выпало: {numbers_str}")

    bingo_history.append(numbers_str)
    if len(bingo_history) > 10:
        bingo_history.pop(0)

    winners = []

    for num in numbers:
        for uid, data in players.items():
            if num in data["numbers"]:
                data["found"].add(num)

    for uid, data in players.items():
        if len(data["found"]) == data["need"]:
            winners.append(uid)

    if winners:
        winner = random.choice(winners)
        db.add_win(winner)

        phrase = random.choice(CHELYABINSK_WIN_PHRASES)

        await update.message.reply_text(
            f"🏆 Победитель @{players[winner]['username']}!\n{phrase}"
        )

        for uid in players:
            if uid != winner:
                db.add_game(uid)

        players.clear() 
# ================== РЕГИСТРАЦИЯ ==================

async def handle_bingo_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not game_active:
        await update.message.reply_text("Игра не активна.")
        return ConversationHandler.END

    if db.is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return ConversationHandler.END

    if game_vip_mode and not db.is_vip(user.id):
        await update.message.reply_text("❌ Эта игра только для VIP.")
        return ConversationHandler.END

    if not game_vip_mode and db.get_msg(user.id) < MIN_MESSAGES_TO_PLAY:
        await update.message.reply_text(
            f"❌ Нужно {MIN_MESSAGES_TO_PLAY}+ сообщений в чате."
        )
        return ConversationHandler.END

    numbers_needed = 4 if game_vip_mode else 5

    await update.message.reply_text(
        f"Введите {numbers_needed} разных чисел от 1 до 100 через пробел."
    )

    return WAITING_VIP_NUMBERS if game_vip_mode else WAITING_NUMBERS


async def receive_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    parts = update.message.text.split()

    if len(parts) != 5:
        await update.message.reply_text("Нужно 5 чисел.")
        return WAITING_NUMBERS

    try:
        nums = list(map(int, parts))
    except:
        await update.message.reply_text("Введите числа корректно.")
        return WAITING_NUMBERS

    if len(set(nums)) != 5 or min(nums) < 1 or max(nums) > 100:
        await update.message.reply_text("Числа должны быть разными от 1 до 100.")
        return WAITING_NUMBERS

    players[user.id] = {
        "numbers": nums,
        "found": set(),
        "username": user.username or str(user.id),
        "need": 5
    }

    await update.message.reply_text("✅ Вы зарегистрированы!")
    return ConversationHandler.END


async def receive_vip_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    parts = update.message.text.split()

    if len(parts) != 4:
        await update.message.reply_text("Нужно 4 числа.")
        return WAITING_VIP_NUMBERS

    try:
        nums = list(map(int, parts))
    except:
        await update.message.reply_text("Введите числа корректно.")
        return WAITING_VIP_NUMBERS

    if len(set(nums)) != 4 or min(nums) < 1 or max(nums) > 100:
        await update.message.reply_text("Числа должны быть разными от 1 до 100.")
        return WAITING_VIP_NUMBERS

    players[user.id] = {
        "numbers": nums,
        "found": set(),
        "username": user.username or str(user.id),
        "need": 4
    }

    await update.message.reply_text("✅ Вы зарегистрированы в VIP игре!")
    return ConversationHandler.END


# ================== ПРОФИЛЬ ==================

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    wins, games, vip, rep, msgs = db.get_stats(user.id)

    percent = round((wins / games) * 100, 1) if games > 0 else 0

    await update.message.reply_text(
        f"👤 Профиль\n\n"
        f"🏆 Побед: {wins}\n"
        f"🎮 Игр: {games}\n"
        f"📈 Процент побед: {percent}%\n"
        f"👑 VIP: {'Да' if vip else 'Нет'}\n"
        f"💬 Сообщений: {msgs}"
    )


# ================== ТЕКСТ ==================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or str(user.id))

    if update.effective_chat.type != "private":
        db.inc_msg(user.id)

    text = update.message.text

    # триггер приветствия
    if any(word in text.lower() for word in TRIGGER_WORDS):
        await update.message.reply_text(random.choice(REPLY_WORDS))
        return

    if text == "🎰 БИНГО":
        return await handle_bingo_button(update, context)

    if text == "👤 Мой профиль":
        await show_profile(update, context)
        return

    if text == "📜 Правила":
        await update.message.reply_text(
            "📜 Правила:\n"
            "- Обычная игра: 5 чисел\n"
            "- VIP игра: 4 числа\n"
            f"- Нужно {MIN_MESSAGES_TO_PLAY}+ сообщений для обычной игры"
        )
        return

    if text == "❓ VIP статус":
        await update.message.reply_text(
            "👑 VIP даёт доступ к VIP игре (4 числа).\n"
            "VIP выдаётся администратором."
        )
        return 
# ================== АДМИН: VIP И БАН ==================

async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /add_vip @username")
        return

    username = context.args[0].lstrip("@")

    db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row = db.cursor.fetchone()

    if not row:
        await update.message.reply_text("Пользователь не найден.")
        return

    db.set_vip(row[0], True)
    await update.message.reply_text(f"✅ @{username} получил VIP.")


async def remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /remove_vip @username")
        return

    username = context.args[0].lstrip("@")

    db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row = db.cursor.fetchone()

    if not row:
        await update.message.reply_text("Пользователь не найден.")
        return

    db.set_vip(row[0], False)
    await update.message.reply_text(f"✅ @{username} лишён VIP.")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /ban 123456789")
        return

    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("ID должен быть числом.")
        return

    db.ban_user(uid)
    await update.message.reply_text("✅ Пользователь заблокирован.")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username not in ADMIN_USERNAMES:
        await update.message.reply_text("❌ Только администратор.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /unban 123456789")
        return

    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("ID должен быть числом.")
        return

    db.unban_user(uid)
    await update.message.reply_text("✅ Пользователь разбанен.")


# ================== START ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or str(user.id))

    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "👋 Привет!\nИспользуй кнопки ниже.",
            reply_markup=private_keyboard()
        )
    else:
        await update.message.reply_text(
            "Бот готов.",
            reply_markup=permanent_keyboard()
        )


# ================== КОМАНДЫ МЕНЮ ==================

async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Старт"),
        BotCommand("startgame", "Запустить игру"),
        BotCommand("stopgame", "Остановить игру"),
        BotCommand("bingo", "Прокрутить числа"),
        BotCommand("add_vip", "Выдать VIP"),
        BotCommand("remove_vip", "Снять VIP"),
        BotCommand("ban", "Забанить"),
        BotCommand("unban", "Разбанить"),
    ])


async def post_init(application):
    await set_commands(application)


# ================== ЗАПУСК ==================

if __name__ == "__main__":

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🎰 БИНГО$"), handle_bingo_button)
        ],
        states={
            WAITING_NUMBERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_numbers)
            ],
            WAITING_VIP_NUMBERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_vip_numbers)
            ],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("stopgame", stopgame))
    app.add_handler(CommandHandler("bingo", bingo))
    app.add_handler(CommandHandler("add_vip", add_vip))
    app.add_handler(CommandHandler("remove_vip", remove_vip))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))

    app.add_handler(CallbackQueryHandler(inline_callback))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Бот полностью запущен.")
    app.run_polling() 
