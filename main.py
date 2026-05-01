import os
import random
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, ContextTypes

# ========== ТОКЕН ==========
TELEGRAM_BOT_TOKEN = "8760736290:AAE3gM-Xfm-Som6o80QeFx8hhRCHBj2cRBk"

ADMIN_USERNAMES = ["baby_illusion", "borzata174"]
MIN_MESSAGES_TO_PLAY = 30
TRIGGER_WORDS = ["привет", "как ты", "салам"]
REPLY_WORDS = ["Привет 👋", "Салам 🤝", "Здорова 😎"]

WAITING_NUMBERS = 1
WAITING_VIP_NUMBERS = 2

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_file="bot_data.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                wins INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                vip INTEGER DEFAULT 0,
                reputation INTEGER DEFAULT 0
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
        self.cursor.execute("SELECT COUNT(*) FROM shops")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO shops (name, username) VALUES (?, ?)", ("Jordan Shop", "Jordan_and_svenbot"))
        self.cursor.execute("SELECT COUNT(*) FROM exchangers")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO exchangers (name, username) VALUES (?, ?)", ("Tripo Exchange", "tripo3"))
        self.conn.commit()

    def ensure_user(self, user_id, username):
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        self.cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        self.conn.commit()

    def is_vip(self, user_id):
        self.cursor.execute("SELECT vip FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row and row[0] == 1

    def set_vip(self, user_id, vip):
        self.cursor.execute("UPDATE users SET vip = ? WHERE user_id = ?", (1 if vip else 0, user_id))
        self.conn.commit()

    def get_reputation(self, user_id):
        self.cursor.execute("SELECT reputation FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def set_reputation(self, user_id, level):
        if level not in (0,1,2):
            return False
        self.cursor.execute("UPDATE users SET reputation = ? WHERE user_id = ?", (level, user_id))
        self.conn.commit()
        return True

    def rep_text(self, level):
        return {0: "⚪ Обычный", 1: "🔶 Средний", 2: "🔴 Высокий"}.get(level, "⚪ Обычный")

    def is_banned(self, user_id):
        self.cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None

    def ban_user(self, user_id, reason=None):
        self.cursor.execute("INSERT OR IGNORE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, ?)",
                            (user_id, datetime.now().isoformat(), reason))
        self.conn.commit()

    def unban_user(self, user_id):
        self.cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def add_win(self, user_id):
        self.cursor.execute("UPDATE users SET wins = wins + 1, games_played = games_played + 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def add_game(self, user_id):
        self.cursor.execute("UPDATE users SET games_played = games_played + 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def get_stats(self, user_id):
        self.cursor.execute("SELECT wins, games_played, vip, reputation FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row if row else (0, 0, 0, 0)

    def get_shops(self):
        self.cursor.execute("SELECT name, username FROM shops")
        return self.cursor.fetchall()

    def add_shop(self, name, username):
        try:
            self.cursor.execute("INSERT INTO shops (name, username) VALUES (?, ?)", (name, username))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_shop(self, name):
        self.cursor.execute("DELETE FROM shops WHERE name = ?", (name,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def get_exchangers(self):
        self.cursor.execute("SELECT name, username FROM exchangers")
        return self.cursor.fetchall()

    def add_exchanger(self, name, username):
        try:
            self.cursor.execute("INSERT INTO exchangers (name, username) VALUES (?, ?)", (name, username))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_exchanger(self, name):
        self.cursor.execute("DELETE FROM exchangers WHERE name = ?", (name,))
        self.conn.commit()
        return self.cursor.rowcount > 0

db = Database()

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
players = {}
game_active = False
game_vip_mode = False
bingo_history = []
history_msg_id = None
progress_msg_id = None

def permanent_keyboard():
    buttons = [
        [KeyboardButton("📜 Правила")],
        [KeyboardButton("❓ VIP статус")],
        [KeyboardButton("🛍️ Магазины")],
        [KeyboardButton("💱 Обменники")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def game_keyboard():
    buttons = [
        [KeyboardButton("✍️ Записаться")],
        [KeyboardButton("🔢 Моя комбинация")],
        [KeyboardButton("📋 Список участников")],
        [KeyboardButton("📊 Прогресс")],
        [KeyboardButton("📜 Правила")],
        [KeyboardButton("❓ VIP статус")],
        [KeyboardButton("🛍️ Магазины")],
        [KeyboardButton("💱 Обменники")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def private_keyboard():
    buttons = [[KeyboardButton("👤 Мой профиль")]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        user_id = update.effective_user.id
        context.user_data["msg_count"] = context.user_data.get("msg_count", 0) + 1

# ========== АДМИН-КОМАНДЫ ==========
async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    keyboard = [
        [InlineKeyboardButton("🎲 Обычная (5 чисел)", callback_data="game_normal")],
        [InlineKeyboardButton("👑 VIP (4 числа, только для VIP)", callback_data="game_vip")]
    ]
    await update.message.reply_text("Выберите тип игры:", reply_markup=InlineKeyboardMarkup(keyboard))

async def game_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    global game_active, players, bingo_history, history_msg_id, progress_msg_id, game_vip_mode
    game_active = True
    players.clear()
    bingo_history.clear()
    history_msg_id = None
    progress_msg_id = None
    game_vip_mode = (query.data == "game_vip")
    mode_text = "VIP" if game_vip_mode else "обычная"
    numbers_count = 4 if game_vip_mode else 5
    try:
        await query.message.delete()
    except:
        pass
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"🎲 **{mode_text} игра началась!**\n\n"
            f"Участники загадывают **{numbers_count} чисел** от 1 до 100.\n"
            f"Нажмите кнопку «✍️ Записаться» (в этом чате).\n"
            f"Ответы бот будет присылать в личные сообщения.\n"
            f"{'Для VIP требуется VIP статус. ' if game_vip_mode else ''}"
            f"Для участия в обычной игре нужно иметь {MIN_MESSAGES_TO_PLAY}+ сообщений в чате."
        ),
        reply_markup=game_keyboard(),
        parse_mode="Markdown"
    )

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    global game_active, players, bingo_history, history_msg_id, progress_msg_id
    game_active = False
    players.clear()
    bingo_history.clear()
    history_msg_id = None
    progress_msg_id = None
    await update.message.reply_text(
        "⏹️ Игра остановлена. Данные очищены.",
        reply_markup=permanent_keyboard()
    )

def get_random_count():
    r = random.random() * 100
    if r < 65:
        return 1
    elif r < 85:
        return 2
    elif r < 93:
        return 3
    elif r < 98:
        return 4
    else:
        return 5

async def update_progress_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global progress_msg_id
    if not game_active or not players:
        return
    lines = []
    for uid, data in players.items():
        rep = db.get_reputation(uid)
        rep_star = db.rep_text(rep)
        vip_icon = "👑 " if db.is_vip(uid) else "  "
        lines.append(f"{vip_icon}@{data['username']} ({rep_star}): {len(data['found'])}/{data['max_needed']}")
    if not lines:
        return
    text = "📊 **Текущий прогресс в игре**\n" + "\n".join(lines)
    chat_id = update.effective_chat.id
    try:
        if progress_msg_id:
            await context.bot.edit_message_text(text, chat_id=chat_id, message_id=progress_msg_id, parse_mode="Markdown")
        else:
            msg = await update.message.reply_text(text, parse_mode="Markdown")
            progress_msg_id = msg.message_id
    except Exception:
        msg = await update.message.reply_text(text, parse_mode="Markdown")
        progress_msg_id = msg.message_id

async def bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not game_active:
        await update.message.reply_text("Игра не активна. Используйте /startgame.")
        return
    if not players:
        await update.message.reply_text("Нет участников. Пусть нажмут «Записаться».")
        return

    count = get_random_count()
    numbers = [random.randint(1, 100) for _ in range(count)]
    numbers_str = ", ".join(str(n) for n in numbers)

    if count == 5:
        message_text = f"✨✨✨ **ВЕЗУЧИЙ ПРОКРУТ!** ✨✨✨\n🎲 Выпало целых 5 чисел: {numbers_str} 🎲"
    elif count == 4:
        message_text = f"🎲 Выпало 4 числа: {numbers_str}"
    elif count == 3:
        message_text = f"🎲 Выпало 3 числа: {numbers_str}"
    elif count == 2:
        message_text = f"🎲 Выпало 2 числа: {numbers_str}"
    else:
        message_text = f"🎲 Выпало число: {numbers_str}"
    await update.message.reply_text(message_text, parse_mode="Markdown")

    history_entry = f"🎲 {numbers_str}"
    bingo_history.append(history_entry)
    if len(bingo_history) > 10:
        bingo_history.pop(0)

    for num in numbers:
        for uid, data in players.items():
            if num in data["numbers"] and num not in data["found"]:
                data["found"].add(num)
                try:
                    await context.bot.send_message(uid, f"✅ Ваше число {num} выпало! Осталось {data['max_needed'] - len(data['found'])}.")
                except Exception:
                    pass

    winners = [(uid, data["username"]) for uid, data in players.items() if len(data["found"]) == data["max_needed"]]

    if winners:
        for uid, uname in winners:
            db.add_win(uid)
            wins, _, vip, rep = db.get_stats(uid)
            rep_text = db.rep_text(rep)
            vip_text = "👑 VIP " if vip else ""
            await update.message.reply_text(
                f"🏆 **Победитель @{uname}!** ({vip_text}{rep_text})\n🎉 Всего побед: {wins}\nИгра окончена.",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(uid, f"🏆 ПОЗДРАВЛЯЕМ! Вы победили! Ваш статус: {vip_text}{rep_text}, всего побед: {wins}.")
            except Exception:
                pass
        for uid in players:
            if uid not in [w[0] for w in winners]:
                db.add_game(uid)
        await stopgame(update, context)
        return

    if players:
        max_found = max(len(data["found"]) for data in players.values())
        max_needed = next(iter(players.values()))["max_needed"]
        leaders = []
        for uid, data in players.items():
            if len(data["found"]) == max_found:
                rep = db.get_reputation(uid)
                rep_txt = db.rep_text(rep)
                leaders.append(f"@{data['username']} {max_found}/{max_needed} ({rep_txt})")
        if leaders:
            await update.message.reply_text(f"📊 Лучший прогресс: {', '.join(leaders)}")

    await update_progress_table(update, context)

    text = "🎰 **История выпавших чисел:**\n" + "\n".join(bingo_history)
    global history_msg_id
    chat_id = update.effective_chat.id
    try:
        if history_msg_id:
            await context.bot.edit_message_text(text, chat_id=chat_id, message_id=history_msg_id, parse_mode="Markdown")
        else:
            msg = await update.message.reply_text(text, parse_mode="Markdown")
            history_msg_id = msg.message_id
    except Exception:
        pass

# ========== АДМИН-УПРАВЛЕНИЕ ==========
async def set_reputation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /set_reputation @username уровень (0,1,2)\n0 – обычный, 1 – средний, 2 – высокий")
        return
    username = args[0].lstrip('@')
    try:
        level = int(args[1])
    except ValueError:
        await update.message.reply_text("Уровень должен быть числом 0, 1 или 2.")
        return
    if level not in (0,1,2):
        await update.message.reply_text("Уровень может быть 0, 1 или 2.")
        return
    db.cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    row = db.cursor.fetchone()
    if not row:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден в базе. Попросите его написать /start боту.")
        return
    uid = row[0]
    if db.set_reputation(uid, level):
        await update.message.reply_text(f"✅ Репутация @{username} установлена на уровень {level} ({db.rep_text(level)}).")
    else:
        await update.message.reply_text("Ошибка при установке репутации.")

async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_vip @username")
        return
    username = context.args[0].lstrip('@')
    db.cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    row = db.cursor.fetchone()
    if row:
        db.set_vip(row[0], True)
        await update.message.reply_text(f"✅ Пользователь @{username} получил VIP статус.")
    else:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден в БД. Попросите его написать /start боту.")

async def remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /remove_vip @username")
        return
    username = context.args[0].lstrip('@')
    db.cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    row = db.cursor.fetchone()
    if row:
        db.set_vip(row[0], False)
        await update.message.reply_text(f"✅ Пользователь @{username} лишён VIP статуса.")
    else:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban 123456789 причина")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
    db.ban_user(uid, reason)
    await update.message.reply_text(f"✅ Пользователь {uid} забанен. Причина: {reason or 'не указана'}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban 123456789")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return
    db.unban_user(uid)
    await update.message.reply_text(f"✅ Пользователь {uid} разбанен.")

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш ID: {update.effective_user.id}")

# ========== МАГАЗИНЫ / ОБМЕННИКИ ==========
async def add_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /add_shop <название> @username")
        return
    name = args[0]
    username = args[1].lstrip('@')
    if db.add_shop(name, username):
        await update.message.reply_text(f"✅ Магазин «{name}» (@{username}) добавлен.")
    else:
        await update.message.reply_text("❌ Магазин с таким названием уже существует.")

async def del_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /del_shop <название>")
        return
    name = " ".join(context.args)
    if db.delete_shop(name):
        await update.message.reply_text(f"✅ Магазин «{name}» удалён.")
    else:
        await update.message.reply_text("❌ Магазин не найден.")

async def list_shops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    shops = db.get_shops()
    if not shops:
        await update.message.reply_text("Список магазинов пуст.")
    else:
        msg = "📋 **Список магазинов:**\n"
        for name, uname in shops:
            msg += f"• {name} — @{uname}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

async def add_exch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /add_exch <название> @username")
        return
    name = args[0]
    username = args[1].lstrip('@')
    if db.add_exchanger(name, username):
        await update.message.reply_text(f"✅ Обменник «{name}» (@{username}) добавлен.")
    else:
        await update.message.reply_text("❌ Обменник с таким названием уже существует.")

async def del_exch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /del_exch <название>")
        return
    name = " ".join(context.args)
    if db.delete_exchanger(name):
        await update.message.reply_text(f"✅ Обменник «{name}» удалён.")
    else:
        await update.message.reply_text("❌ Обменник не найден.")

async def list_exch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    exch = db.get_exchangers()
    if not exch:
        await update.message.reply_text("Список обменников пуст.")
    else:
        msg = "📋 **Список обменников:**\n"
        for name, uname in exch:
            msg += f"• {name} — @{uname}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

# ========== ОБРАБОТКА КНОПОК (МАГАЗИНЫ/ОБМЕННИКИ) ==========
async def shops_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shops = db.get_shops()
    if not shops:
        await update.message.reply_text("Список магазинов пуст. Админ может добавить через /add_shop")
        return
    keyboard = [[InlineKeyboardButton(name, callback_data=f"shop_{username}")] for name, username in shops]
    await update.message.reply_text("Выберите магазин:", reply_markup=InlineKeyboardMarkup(keyboard))

async def exchangers_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exch = db.get_exchangers()
    if not exch:
        await update.message.reply_text("Список обменников пуст. Админ может добавить через /add_exch")
        return
    keyboard = [[InlineKeyboardButton(name, callback_data=f"exch_{username}")] for name, username in exch]
    await update.message.reply_text("Выберите обменник:", reply_markup=InlineKeyboardMarkup(keyboard))

async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("shop_"):
        username = data[5:]
        await query.edit_message_text(f"📦 Свяжитесь с продавцом: @{username}")
    elif data.startswith("exch_"):
        username = data[5:]
        await query.edit_message_text(f"💱 Свяжитесь с обменником: @{username}")
    elif data in ("game_normal", "game_vip"):
        await game_type_callback(update, context)

# ========== ОСНОВНОЙ ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ ==========
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    db.ensure_user(user_id, username)

    # ЛИЧНЫЕ СООБЩЕНИЯ
    if update.effective_chat.type == "private":
        if text == "👤 Мой профиль" or text == "Мой профиль":
            wins, games, vip, rep = db.get_stats(user_id)
            vip_status = "👑 VIP" if vip else "⭐ Обычный"
            rep_level = db.rep_text(rep)
            await update.message.reply_text(
                f"📊 **Ваш профиль**\n\n"
                f"Статус: {vip_status}\n"
                f"Репутация: {rep_level}\n"
                f"🏆 Побед: {wins}\n"
                f"🎲 Сыграно игр: {games}\n",
                parse_mode="Markdown"
            )
            return
        else:
            await update.message.reply_text("Используйте кнопку ниже.", reply_markup=private_keyboard())
            return

    # ГРУППОВЫЕ СООБЩЕНИЯ
    # Правила
    if text == "📜 Правила" or text == "Правила":
        rules = (
            "📜 **Правила игры**\n\n"
            "**Обычная игра:**\n- Загадайте 5 разных чисел от 1 до 100.\n- Требуется 30+ сообщений в чате.\n\n"
            "**VIP игра:**\n- Загадайте 4 разных числа от 1 до 100.\n- Требуется VIP статус.\n\n"
            "**Как получить VIP?**\n❌ VIP статус НЕ продаётся. Его можно заслужить:\n"
            "• материальная поддержка чата\n• проявлять креативность\n• быть активным участником\n• иметь хорошую репутацию\n\n"
            "**Репутация** – показатель вашего вклада. Уровни: ⚪ Обычный, 🔶 Средний, 🔴 Высокий.\n"
            "Репутацию повышают администраторы.\n\n"
            "По вопросам VIP и репутации к @baby_illusion.\n\n"
            "Админ запускает прокрутки командой /bingo. За раз 1-5 чисел (чем больше, тем реже).\n"
            "Побеждает тот, кто первым соберёт все свои числа."
        )
        await update.message.reply_text(rules, parse_mode="Markdown")
        return

    # VIP статус
    if text == "❓ VIP статус" or text == "VIP статус":
        msg = (
            "👑 **Что такое VIP статус?**\n\n"
            "VIP статус даёт право участвовать в VIP-играх (нужно собрать всего 4 числа).\n\n"
            "❌ VIP статус **не продаётся**. Его можно **заслужить**:\n"
            "• материальная поддержка чата\n"
            "• креативность (идеи, конкурсы)\n"
            "• высокая активность в чате\n"
            "• хорошая репутация\n\n"
            "**Репутация** – три уровня (обычный, средний, высокий).\n\n"
            "📩 Если считаете, что достойны VIP – напишите @baby_illusion."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Моя комбинация
    if text == "🔢 Моя комбинация" or text == "Моя комбинация":
        if not game_active:
            await update.message.reply_text("Сейчас нет активной игры.")
            return
        if user_id in players:
            nums = ", ".join(map(str, players[user_id]["numbers"]))
            found = ", ".join(map(str, players[user_id]["found"])) if players[user_id]["found"] else "пока нет"
            maxn = players[user_id]["max_needed"]
            await update.message.reply_text(f"🔢 **Ваши числа:** {nums}\n✅ **Выпали:** {found}\n🎯 Нужно собрать: {maxn} чисел", parse_mode="Markdown")
        else:
            await update.message.reply_text("Вы ещё не записались. Нажмите «✍️ Записаться».")
        return

    # Список участников
    if text == "📋 Список участников" or text == "Список участников":
        if not game_active:
            await update.message.reply_text("Сейчас нет активной игры.")
            return
        if not players:
            await update.message.reply_text("Список участников пуст.")
            return
        msg = "📋 **Текущие участники игры:**\n\n"
        for uid, data in players.items():
            nums = ", ".join(map(str, data["numbers"]))
            count = len(data["found"])
            maxn = data["max_needed"]
            wins, _, vip, rep = db.get_stats(uid)
            rep_txt = db.rep_text(rep)
            vip_txt = "👑" if vip else ""
            msg += f"👤 @{data['username']} {vip_txt} ({rep_txt}): {nums} | выпало {count}/{maxn} | побед: {wins}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Прогресс
    if text == "📊 Прогресс" or text == "Прогресс":
        if not game_active:
            await update.message.reply_text("Сейчас нет активной игры.")
            return
        if not players:
            await update.message.reply_text("Пока нет зарегистрированных участников.")
            return
        lines = []
        for uid, data in players.items():
            rep = db.get_reputation(uid)
            rep_star = db.rep_text(rep)
            vip_icon = "👑 " if db.is_vip(uid) else "  "
            lines.append(f"{vip_icon}@{data['username']} ({rep_star}): {len(data['found'])}/{data['max_needed']}")
        text = "📊 **Текущий прогресс в игре**\n" + "\n".join(lines)
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    # Магазины
    if text == "🛍️ Магазины" or text == "Магазины":
        await shops_button(update, context)
        return

    # Обменники
    if text == "💱 Обменники" or text == "Обменники":
        await exchangers_button(update, context)
        return

    # Записаться
    if text == "✍️ Записаться" or text == "Записаться":
        if not game_active:
            await update.message.reply_text("Игра ещё не началась. Администратор должен дать /startgame в общем чате.")
            return
        if user_id in players:
            await update.message.reply_text("Вы уже зарегистрированы в текущей игре.")
            return
        if db.is_banned(user_id):
            await update.message.reply_text("❌ Вы в чёрном списке и не можете участвовать.")
            return

        if game_vip_mode:
            if not db.is_vip(user_id):
                await update.message.reply_text("❌ Эта игра только для VIP. Обратитесь к администратору за статусом.")
                return
            await update.message.reply_text("Введите **4 разных числа от 1 до 100** через пробел.\nПример: 7 15 32 68", parse_mode="Markdown")
            return WAITING_VIP_NUMBERS
        else:
            msg_count = context.user_data.get("msg_count", 0)
            if msg_count < MIN_MESSAGES_TO_PLAY:
                await update.message.reply_text(f"❌ Недостаточно сообщений в чате. Нужно {MIN_MESSAGES_TO_PLAY}, у вас {msg_count}.")
                return
            await update.message.reply_text("Введите **5 разных чисел от 1 до 100** через пробел.\nПример: 7 15 32 68 91", parse_mode="Markdown")
            return WAITING_NUMBERS

    # Фаллбэк (если ничего не подошло)
    if game_active:
        await update.message.reply_text("Пожалуйста, используйте кнопки.", reply_markup=game_keyboard())
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки.", reply_markup=permanent_keyboard())

# ========== ДИАЛОГ ВВОДА ЧИСЕЛ ==========
async def receive_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) != 5:
        await update.message.reply_text("❌ Нужно ровно 5 чисел. Попробуйте снова.")
        return WAITING_NUMBERS
    try:
        nums = [int(x) for x in parts]
        if len(set(nums)) != 5 or min(nums) < 1 or max(nums) > 100:
            await update.message.reply_text("❌ Числа должны быть разными, от 1 до 100.")
            return WAITING_NUMBERS
    except ValueError:
        await update.message.reply_text("❌ Введите числа через пробел. Пример: 5 9 3 11 86")
        return WAITING_NUMBERS

    players[user_id] = {
        "numbers": nums,
        "found": set(),
        "username": update.effective_user.username or str(user_id),
        "max_needed": 5
    }
    await update.message.reply_text(
        f"✅ **Вы зарегистрированы в обычной игре!**\nВаши числа: {', '.join(map(str, nums))}\n\nКогда админ начнёт прокрутки (/bingo), вы будете получать уведомления.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def receive_vip_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) != 4:
        await update.message.reply_text("❌ Нужно ровно 4 числа. Попробуйте снова.")
        return WAITING_VIP_NUMBERS
    try:
        nums = [int(x) for x in parts]
        if len(set(nums)) != 4 or min(nums) < 1 or max(nums) > 100:
            await update.message.reply_text("❌ Числа должны быть разными, от 1 до 100.")
            return WAITING_VIP_NUMBERS
    except ValueError:
        await update.message.reply_text("❌ Введите числа через пробел. Пример: 7 15 32 68")
        return WAITING_VIP_NUMBERS

    players[user_id] = {
        "numbers": nums,
        "found": set(),
        "username": update.effective_user.username or str(user_id),
        "max_needed": 4
    }
    await update.message.reply_text(
        f"✅ **Вы зарегистрированы в VIP игре!**\nВаши числа: {', '.join(map(str, nums))}\n\nКогда админ начнёт прокрутки (/bingo), вы будете получать уведомления.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ========== ПРИВЕТСТВИЯ ==========
async def greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" and update.message and update.message.text:
        low = update.message.text.lower()
        for w in TRIGGER_WORDS:
            if w in low:
                await update.message.reply_text(random.choice(REPLY_WORDS))
                break

# ========== СТАРТ ==========
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        user_id = update.effective_user.id
        username = update.effective_user.username or str(user_id)
        db.ensure_user(user_id, username)
        await update.message.reply_text(
            f"👋 Привет, {username}!\n\nЯ бот для игры в Bingo. Используй кнопку ниже, чтобы посмотреть свою статистику.\n\nДля участия в игре переходи в группу и нажимай кнопки там.",
            reply_markup=private_keyboard()
        )
    else:
        await update.message.reply_text(
            "Бот готов к работе. Используйте кнопки ниже.\nАдмин может запустить игру командой /startgame.",
            reply_markup=permanent_keyboard()
        )

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_private))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("stopgame", stopgame))
    app.add_handler(CommandHandler("bingo", bingo))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("add_vip", add_vip))
    app.add_handler(CommandHandler("remove_vip", remove_vip))
    app.add_handler(CommandHandler("set_reputation", set_reputation))
    app.add_handler(CommandHandler("add_shop", add_shop))
    app.add_handler(CommandHandler("del_shop", del_shop))
    app.add_handler(CommandHandler("list_shops", list_shops))
    app.add_handler(CommandHandler("add_exch", add_exch))
    app.add_handler(CommandHandler("del_exch", del_exch))
    app.add_handler(CommandHandler("list_exch", list_exch))
    app.add_handler(CallbackQueryHandler(inline_callback, pattern="^(shop_|exch_|game_)"))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Записаться$"), handle_buttons)],
        states={
            WAITING_NUMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_numbers)],
            WAITING_VIP_NUMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_vip_numbers)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)

    # Обрабатываем все текстовые сообщения (кроме команд) через единый обработчик
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, greeting))

    print("Бот KidOk запущен. Кнопки Правила и VIP статус отвечают в чате группы.")
    app.run_polling()


