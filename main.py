import os
import random
import sqlite3
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, ContextTypes

# ========== ТОКЕН ==========
TELEGRAM_BOT_TOKEN = "8760736290:AAGCLht6jJlHKA0uJbZsEnbNobhbk2nzI_s"

ADMIN_USERNAMES = ["baby_illusion", "borzata174"]
TRIGGER_WORDS = ["привет", "как ты", "салам"]
REPLY_WORDS = ["Привет 👋", "Салам 🤝", "Здорова 😎"]

WAITING_NUMBERS = 1
WAITING_VIP_NUMBERS = 2

# ========== ЧЕЛЯБИНСКИЕ ПОЗДРАВЛЕНИЯ ==========
CHELYABINSK_WIN_PHRASES = [
    "✅ Чётко, братан! Ты сегодня главный на районе. Так держать, пацан!",
    "💰 Бабки в карман, тачку на ход! Ты реально порвал эту бингу. Поздравляю, авторитет!",
    "🏧 По-честному намутил победу. Респект тебе, бро! Жму руку.",
    "🦾 Челябинский хардкор! Никто не ожидал, а ты выиграл. Ты красавчик!",
    "🍻 Гулять сегодня – твой выход. Победа за тобой, пацан! Уважаю!",
    "🎰 Как в казино на Труда: рискнул – и вот ты с призом. Горжусь, брат.",
    "🚬 Сигару в зубы, пацан! Ты сделал это. Реальный олд-мани.",
    "💎 Твоя победа – как слиток золота. Тяжело, но дорого. Прими поздравления!",
    "👔 Костюм от Brioni, туфли от Berluti – а ты выиграл. Шик, блеск, красота!",
    "🥃 Виски, сигара, победа. Живи как настоящий мафиози!"
]

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_file="bot_data.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._init_achievements()

    def _create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                wins INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                vip INTEGER DEFAULT 0,
                reputation INTEGER DEFAULT 0,
                donations INTEGER DEFAULT 0
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
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT,
                icon TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id INTEGER,
                ach_name TEXT,
                earned_at TEXT,
                PRIMARY KEY (user_id, ach_name)
            )
        """)
        self.conn.commit()

    def _init_achievements(self):
        achievements = [
            ("Первая кровь", "Одержать первую победу", "🩸"),
            ("Массовик", "Одержать 5 побед", "📢"),
            ("Друг чата", "Пригласить 3 друзей", "🤝"),
            ("VIP", "Получить VIP статус", "👑"),
            ("Топ донатер", "Проспонсировать 3 игры", "💰")
        ]
        for name, desc, icon in achievements:
            self.cursor.execute("INSERT OR IGNORE INTO achievements (name, description, icon) VALUES (?, ?, ?)", (name, desc, icon))
        self.conn.commit()

    def get_user_achievements(self, user_id):
        self.cursor.execute("SELECT ach_name FROM user_achievements WHERE user_id = ?", (user_id,))
        rows = self.cursor.fetchall()
        return [row[0] for row in rows]

    def unlock_achievement(self, user_id, ach_name):
        self.cursor.execute("SELECT 1 FROM user_achievements WHERE user_id = ? AND ach_name = ?", (user_id, ach_name))
        if self.cursor.fetchone():
            return False
        self.cursor.execute("INSERT INTO user_achievements (user_id, ach_name, earned_at) VALUES (?, ?, ?)",
                            (user_id, ach_name, datetime.now().isoformat()))
        self.conn.commit()
        return True

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
        if vip:
            return self.unlock_achievement(user_id, "VIP")
        return False

    def add_donation(self, user_id):
        self.cursor.execute("UPDATE users SET donations = donations + 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()
        self.cursor.execute("SELECT donations FROM users WHERE user_id = ?", (user_id,))
        donations = self.cursor.fetchone()[0]
        if donations >= 3:
            return self.unlock_achievement(user_id, "Топ донатер")
        return False

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
        self.cursor.execute("SELECT wins FROM users WHERE user_id = ?", (user_id,))
        wins = self.cursor.fetchone()[0]
        if wins == 1:
            self.unlock_achievement(user_id, "Первая кровь")
        if wins >= 5:
            self.unlock_achievement(user_id, "Массовик")

    def add_game(self, user_id):
        self.cursor.execute("UPDATE users SET games_played = games_played + 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def get_stats(self, user_id):
        self.cursor.execute("SELECT wins, games_played, vip, reputation FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row if row else (0,0,0,0)

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
        return self.cursor.rowcount>0

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
        return self.cursor.rowcount>0

db = Database()

# ========== Глобальные переменные ==========
players = {}
game_active = False
game_vip_mode = False
registration_open = True
bingo_history = []
history_msg_id = None
progress_msg_id = None

# ========== КЛАВИАТУРЫ ==========
def permanent_keyboard():
    btn_shop = KeyboardButton("🛍️ Магазины")
    btn_exch = KeyboardButton("💱 Обменники")
    btn_rules = KeyboardButton("📜 Правила")
    btn_vip = KeyboardButton("❓ VIP статус")
    keyboard = [[btn_shop, btn_exch], [btn_rules, btn_vip]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def game_keyboard():
    btn_bingo = KeyboardButton("🎰 БИНГО")
    btn_shop = KeyboardButton("🛍️ Магазины")
    btn_exch = KeyboardButton("💱 Обменники")
    btn_rules = KeyboardButton("📜 Правила")
    btn_vip = KeyboardButton("❓ VIP статус")
    keyboard = [[btn_bingo, btn_shop], [btn_exch, btn_rules], [btn_vip]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def private_keyboard():
    btn_profile = KeyboardButton("👤 Мой профиль")
    btn_achievements = KeyboardButton("🏅 Мои достижения")
    keyboard = [[btn_profile, btn_achievements]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== Вспомогательные функции ==========
def get_random_count():
    r = random.random() * 100
    if r < 65: return 1
    elif r < 85: return 2
    elif r < 93: return 3
    elif r < 98: return 4
    else: return 5

async def delete_message_after(context, chat_id, message_id, delay=20):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# ========== Админ-команды ==========
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
    global game_active, players, bingo_history, history_msg_id, progress_msg_id, game_vip_mode, registration_open
    game_active = True
    players.clear()
    bingo_history.clear()
    history_msg_id = None
    progress_msg_id = None
    game_vip_mode = (query.data == "game_vip")
    registration_open = True
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
            f"Нажмите кнопку «🎰 БИНГО» и выберите действие.\n"
            f"Ответы бот будет присылать в личные сообщения.\n"
            f"{'Для VIP требуется VIP статус. ' if game_vip_mode else ''}"
        ),
        reply_markup=game_keyboard(),
        parse_mode="Markdown"
    )

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    global game_active, players, bingo_history, history_msg_id, progress_msg_id, registration_open
    game_active = False
    players.clear()
    bingo_history.clear()
    history_msg_id = None
    progress_msg_id = None
    registration_open = False
    await update.message.reply_text(
        "⏹️ Игра остановлена. Данные очищены.",
        reply_markup=permanent_keyboard()
    )

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
            if 'progress_delete_job' in context.bot_data:
                context.bot_data['progress_delete_job'].schedule_removal()
            job = context.job_queue.run_once(lambda _: asyncio.create_task(delete_message_after(context, chat_id, progress_msg_id, 20)), 20)
            context.bot_data['progress_delete_job'] = job
        else:
            msg = await update.message.reply_text(text, parse_mode="Markdown")
            progress_msg_id = msg.message_id
            asyncio.create_task(delete_message_after(context, chat_id, progress_msg_id, 20))
    except Exception:
        msg = await update.message.reply_text(text, parse_mode="Markdown")
        progress_msg_id = msg.message_id
        asyncio.create_task(delete_message_after(context, chat_id, progress_msg_id, 20))

async def bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not game_active:
        await update.message.reply_text("Игра не активна. Используйте /startgame.")
        return
    if not players:
        await update.message.reply_text("Нет участников. Пусть нажмут «🎰 БИНГО» → «Записаться».")
        return

    global registration_open
    if registration_open:
        registration_open = False
        await update.message.reply_text("🚫 Регистрация закрыта! Новые участники больше не принимаются.")

    count = get_random_count()
    numbers = [random.randint(1,100) for _ in range(count)]
    numbers_str = ", ".join(str(n) for n in numbers)

    if count==5:
        msg = f"✨✨✨ **ВЕЗУЧИЙ ПРОКРУТ!** ✨✨✨\n🎲 Выпало целых 5 чисел: {numbers_str} 🎲"
    elif count==4: msg = f"🎲 Выпало 4 числа: {numbers_str}"
    elif count==3: msg = f"🎲 Выпало 3 числа: {numbers_str}"
    elif count==2: msg = f"🎲 Выпало 2 числа: {numbers_str}"
    else: msg = f"🎲 Выпало число: {numbers_str}"
    await update.message.reply_text(msg, parse_mode="Markdown")

    bingo_history.append(f"🎲 {numbers_str}")
    if len(bingo_history)>10: bingo_history.pop(0)

    for num in numbers:
        for uid, data in players.items():
            if num in data["numbers"] and num not in data["found"]:
                data["found"].add(num)
                try:
                    await context.bot.send_message(uid, f"✅ Ваше число {num} выпало! Осталось {data['max_needed'] - len(data['found'])}.")
                except: pass

    winners = [(uid, data["username"]) for uid,data in players.items() if len(data["found"])==data["max_needed"]]

    if winners:
        winner_uid, winner_uname = random.choice(winners)
        db.add_win(winner_uid)
        wins, _, vip, rep = db.get_stats(winner_uid)
        rep_txt = db.rep_text(rep)
        vip_txt = "👑 VIP " if vip else ""
        await update.message.reply_text(
            f"🏆 **Победитель @{winner_uname}!** ({vip_txt}{rep_txt})\n🎉 Всего побед: {wins}\nИгра окончена.",
            parse_mode="Markdown"
        )
        try:
            phrase = random.choice(CHELYABINSK_WIN_PHRASES)
            await context.bot.send_message(
                winner_uid,
                f"🎁 **Твой приз ждёт!**\n\n{phrase}\n\nСвяжись с администратором @baby_illusion для получения выигрыша.",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Не удалось отправить поздравление: {e}")
        for uid in players:
            if uid != winner_uid:
                db.add_game(uid)
        await stopgame(update, context)
        return

    if players:
        max_found = max(len(d["found"]) for d in players.values())
        max_needed = next(iter(players.values()))["max_needed"]
        leaders = []
        for uid,data in players.items():
            if len(data["found"])==max_found:
                rep=db.get_reputation(uid)
                rep_txt=db.rep_text(rep)
                leaders.append(f"@{data['username']} {max_found}/{max_needed} ({rep_txt})")
        if leaders:
            await update.message.reply_text(f"📊 Лучший прогресс: {', '.join(leaders)}")

    await update_progress_table(update, context)

    text = "🎰 **История выпавших чисел:**\n"+"\n".join(bingo_history)
    global history_msg_id
    chat_id = update.effective_chat.id
    try:
        if history_msg_id:
            await context.bot.edit_message_text(text, chat_id=chat_id, message_id=history_msg_id, parse_mode="Markdown")
            if 'history_delete_job' in context.bot_data:
                context.bot_data['history_delete_job'].schedule_removal()
            job = context.job_queue.run_once(lambda _: asyncio.create_task(delete_message_after(context, chat_id, history_msg_id, 20)), 20)
            context.bot_data['history_delete_job'] = job
        else:
            msg = await update.message.reply_text(text, parse_mode="Markdown")
            history_msg_id = msg.message_id
            asyncio.create_task(delete_message_after(context, chat_id, history_msg_id, 20))
    except Exception:
        msg = await update.message.reply_text(text, parse_mode="Markdown")
        history_msg_id = msg.message_id
        asyncio.create_task(delete_message_after(context, chat_id, history_msg_id, 20))

# ========== Админ-управление ==========
async def set_reputation(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args=context.args
    if len(args)<2:
        await update.message.reply_text("Использование: /set_reputation @username уровень (0,1,2)")
        return
    username=args[0].lstrip('@')
    try: level=int(args[1])
    except: await update.message.reply_text("Уровень должен быть числом 0,1,2"); return
    if level not in (0,1,2): await update.message.reply_text("Уровень 0,1 или 2."); return
    cur=db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row=cur.fetchone()
    if not row:
        await update.message.reply_text(f"❌ @{username} не найден. Попросите написать /start.")
        return
    if db.set_reputation(row[0],level):
        await update.message.reply_text(f"✅ Репутация @{username} установлена на {level} ({db.rep_text(level)}).")
    else:
        await update.message.reply_text("Ошибка.")

async def add_vip(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_vip @username")
        return
    username=context.args[0].lstrip('@')
    cur=db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row=cur.fetchone()
    if row:
        got_ach = db.set_vip(row[0], True)
        await update.message.reply_text(f"✅ @{username} получил VIP статус.")
        if got_ach:
            try:
                await context.bot.send_message(row[0], "👑 Вы получили VIP-статус и открыли достижение «VIP»!")
            except: pass
    else:
        await update.message.reply_text(f"❌ @{username} не найден. Пусть напишет /start.")

async def remove_vip(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /remove_vip @username")
        return
    username=context.args[0].lstrip('@')
    cur=db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row=cur.fetchone()
    if row:
        db.set_vip(row[0], False)
        await update.message.reply_text(f"✅ @{username} лишён VIP статуса.")
    else:
        await update.message.reply_text(f"❌ @{username} не найден.")

async def add_donation(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_donation @username")
        return
    username=context.args[0].lstrip('@')
    cur=db.cursor.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row=cur.fetchone()
    if not row:
        await update.message.reply_text(f"❌ @{username} не найден. Пусть напишет /start.")
        return
    uid = row[0]
    got_ach = db.add_donation(uid)
    await update.message.reply_text(f"✅ Донат засчитан пользователю @{username}.")
    if got_ach:
        try:
            await context.bot.send_message(uid, "💰 Спонсорство 3 игр принесло вам достижение «Топ донатер»!")
        except: pass

async def ban(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban 123456789 причина")
        return
    try: uid=int(context.args[0])
    except: await update.message.reply_text("ID должен быть числом."); return
    reason=" ".join(context.args[1:]) if len(context.args)>1 else None
    db.ban_user(uid, reason)
    await update.message.reply_text(f"✅ Пользователь {uid} забанен. Причина: {reason or 'не указана'}")

async def unban(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban 123456789")
        return
    try: uid=int(context.args[0])
    except: await update.message.reply_text("ID должен быть числом."); return
    db.unban_user(uid)
    await update.message.reply_text(f"✅ Пользователь {uid} разбанен.")

async def getid(update, context):
    await update.message.reply_text(f"Ваш ID: {update.effective_user.id}")

# ========== Магазины / Обменники ==========
async def add_shop(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args=context.args
    if len(args)<2:
        await update.message.reply_text("Использование: /add_shop <название> @username")
        return
    name=args[0]
    username=args[1].lstrip('@')
    if db.add_shop(name, username):
        await update.message.reply_text(f"✅ Магазин «{name}» (@{username}) добавлен.")
    else:
        await update.message.reply_text("❌ Магазин с таким названием уже существует.")

async def del_shop(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /del_shop <название>")
        return
    name=" ".join(context.args)
    if db.delete_shop(name):
        await update.message.reply_text(f"✅ Магазин «{name}» удалён.")
    else:
        await update.message.reply_text("❌ Магазин не найден.")

async def list_shops(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    shops=db.get_shops()
    if not shops:
        await update.message.reply_text("Список магазинов пуст.")
    else:
        msg="📋 **Список магазинов:**\n"
        for name,uname in shops: msg+=f"• {name} — @{uname}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

async def add_exch(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    args=context.args
    if len(args)<2:
        await update.message.reply_text("Использование: /add_exch <название> @username")
        return
    name=args[0]
    username=args[1].lstrip('@')
    if db.add_exchanger(name, username):
        await update.message.reply_text(f"✅ Обменник «{name}» (@{username}) добавлен.")
    else:
        await update.message.reply_text("❌ Обменник с таким названием уже существует.")

async def del_exch(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /del_exch <название>")
        return
    name=" ".join(context.args)
    if db.delete_exchanger(name):
        await update.message.reply_text(f"✅ Обменник «{name}» удалён.")
    else:
        await update.message.reply_text("❌ Обменник не найден.")

async def list_exch(update, context):
    if update.effective_user.username.lower() not in [a.lower() for a in ADMIN_USERNAMES]:
        await update.message.reply_text("❌ Только администратор.")
        return
    exch=db.get_exchangers()
    if not exch:
        await update.message.reply_text("Список обменников пуст.")
    else:
        msg="📋 **Список обменников:**\n"
        for name,uname in exch: msg+=f"• {name} — @{uname}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

# ========== Кнопки Магазинов и Обменников (инлайн) ==========
async def shops_button(update, context):
    shops=db.get_shops()
    if not shops:
        await update.message.reply_text("Список магазинов пуст. Админ может добавить через /add_shop")
        return
    keyboard=[[InlineKeyboardButton(name, callback_data=f"shop_{username}")] for name,username in shops]
    await update.message.reply_text("Выберите магазин:", reply_markup=InlineKeyboardMarkup(keyboard))

async def exchangers_button(update, context):
    exch=db.get_exchangers()
    if not exch:
        await update.message.reply_text("Список обменников пуст. Админ может добавить через /add_exch")
        return
    keyboard=[[InlineKeyboardButton(name, callback_data=f"exch_{username}")] for name,username in exch]
    await update.message.reply_text("Выберите обменник:", reply_markup=InlineKeyboardMarkup(keyboard))

async def inline_callback(update, context):
    query=update.callback_query
    await query.answer()
    data=query.data
    if data.startswith("shop_"):
        username=data[5:]
        await query.edit_message_text(f"📦 Свяжитесь с продавцом: @{username}")
    elif data.startswith("exch_"):
        username=data[5:]
        await query.edit_message_text(f"💱 Свяжитесь с обменником: @{username}")
    elif data in ("game_normal","game_vip"):
        await game_type_callback(update, context)
    elif data in ("register", "my_combo", "players_list", "progress"):
        user_id=query.from_user.id
        await query.message.delete()
        if not game_active:
            await query.message.reply_text("Игра не активна.")
            return
        if data=="register":
            await handle_register(query.message, context, user_id)
        elif data=="my_combo":
            await handle_my_combo(query.message, context, user_id)
        elif data=="players_list":
            await handle_players_list(query.message, context, user_id)
        elif data=="progress":
            await handle_progress(query.message, context, user_id)

# ========== Обработчики действий из БИНГО ==========
async def handle_register(message, context, user_id):
    if user_id in players:
        await context.bot.send_message(user_id, "Вы уже зарегистрированы в текущей игре.")
        return
    if not registration_open:
        await context.bot.send_message(user_id, "Регистрация на эту игру уже закрыта. Ждите следующую.")
        return
    if db.is_banned(user_id):
        await context.bot.send_message(user_id, "❌ Вы в чёрном списке и не можете участвовать.")
        return
    if game_vip_mode:
        if not db.is_vip(user_id):
            await context.bot.send_message(user_id, "❌ Эта игра только для VIP.")
            return
        await context.bot.send_message(user_id, "Введите **4 разных числа от 1 до 100** через пробел.\nПример: 7 15 32 68", parse_mode="Markdown")
        return WAITING_VIP_NUMBERS
    else:
        await context.bot.send_message(user_id, "Введите **5 разных чисел от 1 до 100** через пробел.\nПример: 7 15 32 68 91", parse_mode="Markdown")
        return WAITING_NUMBERS

async def handle_my_combo(message, context, user_id):
    if user_id in players:
        nums = ", ".join(map(str, players[user_id]["numbers"]))
        found = ", ".join(map(str, players[user_id]["found"])) if players[user_id]["found"] else "пока нет"
        need = players[user_id]["max_needed"]
        await context.bot.send_message(user_id, f"🔢 **Ваши числа:** {nums}\n✅ **Выпали:** {found}\n🎯 Нужно собрать: {need} чисел", parse_mode="Markdown")
    else:
        await context.bot.send_message(user_id, "Вы ещё не записались. Нажмите «БИНГО» → «Записаться».")

async def handle_players_list(message, context, user_id):
    if not players:
        await context.bot.send_message(user_id, "Список участников пуст.")
        return
    msg = "📋 **Текущие участники игры:**\n\n"
    for uid,data in players.items():
        nums = ", ".join(map(str, data["numbers"]))
        count = len(data["found"])
        need = data["max_needed"]
        wins,_,vip,rep = db.get_stats(uid)
        rep_txt=db.rep_text(rep)
        vip_txt="👑" if vip else ""
        msg += f"👤 @{data['username']} {vip_txt} ({rep_txt}): {nums} | выпало {count}/{need} | побед: {wins}\n"
    await context.bot.send_message(user_id, msg, parse_mode="Markdown")

async def handle_progress(message, context, user_id):
    if not players:
        await context.bot.send_message(user_id, "Пока нет зарегистрированных участников.")
        return
    lines = []
    for uid,data in players.items():
        rep=db.get_reputation(uid)
        rep_star=db.rep_text(rep)
        vip_icon="👑 " if db.is_vip(uid) else "  "
        lines.append(f"{vip_icon}@{data['username']} ({rep_star}): {len(data['found'])}/{data['max_needed']}")
    answer = "📊 **Текущий прогресс в игре**\n" + "\n".join(lines)
    msg = await context.bot.send_message(user_id, answer, parse_mode="Markdown")
    asyncio.create_task(delete_message_after(context, user_id, msg.message_id, 20))

# ========== Основной обработчик сообщений (кнопки) ==========
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    db.ensure_user(user_id, username)

    # Личные сообщения
    if update.effective_chat.type == "private":
        if text == "👤 Мой профиль":
            wins, games, vip, rep = db.get_stats(user_id)
            vip_status = "👑 VIP" if vip else "⭐ Обычный"
            rep_level = db.rep_text(rep)
            percent = round(wins / games * 100, 1) if games > 0 else 0
            await update.message.reply_text(
                f"📊 **Ваш профиль**\n\n"
                f"Статус: {vip_status}\n"
                f"Репутация: {rep_level}\n"
                f"🏆 Побед: {wins}\n"
                f"🎲 Сыграно игр: {games}\n"
                f"📈 Процент побед: {percent}%",
                parse_mode="Markdown"
            )
            return
        elif text == "🏅 Мои достижения":
            achievements = db.get_user_achievements(user_id)
            db.cursor.execute("SELECT name, description, icon FROM achievements ORDER BY id")
            all_ach = db.cursor.fetchall()
            msg = "🏅 **Ваши достижения:**\n\n"
            for name, desc, icon in all_ach:
                if name in achievements:
                    msg += f"{icon} **{name}** – {desc} ✅\n"
                else:
                    msg += f"{icon} {name} – {desc} ❌\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        else:
            await update.message.reply_text("Используйте кнопки ниже.", reply_markup=private_keyboard())
            return

    # Группа – обрабатываем кнопки
    if text == "📜 Правила" or text == "Правила":
        rules = (
            "📜 **Правила игры**\n\n"
            "**Обычная игра:**\n- Загадайте 5 разных чисел от 1 до 100.\n\n"
            "**VIP игра:**\n- Загадайте 4 разных числа от 1 до 100.\n- Требуется VIP статус.\n\n"
            "**Как получить VIP?**\n❌ VIP статус НЕ продаётся. Его можно заслужить:\n"
            "• материальная поддержка чата\n• проявлять креативность\n• быть активным участником\n• иметь хорошую репутацию\n\n"
            "**Репутация** – показатель вашего вклада. Уровни: ⚪ Обычный, 🔶 Средний, 🔴 Высокий.\n"
            "Репутацию повышают администраторы.\n\n"
            "**Достижения (ачивки):**\n"
            "🩸 Первая кровь – первая победа.\n"
            "📢 Массовик – 5 побед.\n"
            "🤝 Друг чата – пригласить 3 друзей (в разработке).\n"
            "👑 VIP – получение VIP статуса.\n"
            "💰 Топ донатер – проспонсировать 3 игры.\n\n"
            "По вопросам VIP и репутации к @baby_illusion.\n\n"
            "Админ запускает прокрутки командой /bingo. За раз 1-5 чисел (чем больше, тем реже).\n"
            "Побеждает тот, кто первым соберёт все свои числа."
        )
        await update.message.reply_text(rules, parse_mode="Markdown")
        return

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
            "Самое главное: все средства от реферальной программы пойдут обратно в чат – на розыгрыши Бинго, конкурсы и подарки для вас! 🎁\n\n"
            "📩 Если считаете, что достойны VIP – напишите @baby_illusion."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    if text == "🛍️ Магазины" or text == "Магазины":
        await shops_button(update, context)
        return

    if text == "💱 Обменники" or text == "Обменники":
        await exchangers_button(update, context)
        return

    if text == "🎰 БИНГО" or text == "БИНГО":
        if not game_active:
            await update.message.reply_text("Игра не активна. Администратор должен дать /startgame.")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Записаться", callback_data="register")],
            [InlineKeyboardButton("🔢 Моя комбинация", callback_data="my_combo")],
            [InlineKeyboardButton("📋 Список участников", callback_data="players_list")],
            [InlineKeyboardButton("📊 Прогресс", callback_data="progress")]
        ])
        await update.message.reply_text("Выберите действие:", reply_markup=keyboard)
        return

# ========== Получение чисел (диалог) ==========
async def receive_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    parts = text.split()
    if len(parts)!=5:
        await update.message.reply_text("❌ Нужно ровно 5 чисел. Попробуйте снова.")
        return WAITING_NUMBERS
    try:
        nums = [int(x) for x in parts]
        if len(set(nums))!=5 or min(nums)<1 or max(nums)>100:
            await update.message.reply_text("❌ Числа должны быть разными, от 1 до 100.")
            return WAITING_NUMBERS
    except:
        await update.message.reply_text("❌ Введите числа через пробел. Пример: 5 9 3 11 86")
        return WAITING_NUMBERS
    players[user_id] = {"numbers": nums, "found": set(), "username": update.effective_user.username or str(user_id), "max_needed": 5}
    await update.message.reply_text(f"✅ **Вы зарегистрированы в обычной игре!**\nВаши числа: {', '.join(map(str, nums))}\n\nКогда админ начнёт прокрутки (/bingo), вы будете получать уведомления.", parse_mode="Markdown")
    return ConversationHandler.END

async def receive_vip_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    parts = text.split()
    if len(parts)!=4:
        await update.message.reply_text("❌ Нужно ровно 4 числа. Попробуйте снова.")
        return WAITING_VIP_NUMBERS
    try:
        nums = [int(x) for x in parts]
        if len(set(nums))!=4 or min(nums)<1 or max(nums)>100:
            await update.message.reply_text("❌ Числа должны быть разными, от 1 до 100.")
            return WAITING_VIP_NUMBERS
    except:
        await update.message.reply_text("❌ Введите числа через пробел. Пример: 7 15 32 68")
        return WAITING_VIP_NUMBERS
    players[user_id] = {"numbers": nums, "found": set(), "username": update.effective_user.username or str(user_id), "max_needed": 4}
    await update.message.reply_text(f"✅ **Вы зарегистрированы в VIP игре!**\nВаши числа: {', '.join(map(str, nums))}\n\nКогда админ начнёт прокрутки (/bingo), вы будете получать уведомления.", parse_mode="Markdown")
    return ConversationHandler.END

# ========== Приветствия и старт ==========
async def greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" and update.message and update.message.text:
        low = update.message.text.lower()
        for w in TRIGGER_WORDS:
            if w in low:
                await update.message.reply_text(random.choice(REPLY_WORDS))
                break

async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        user_id = update.effective_user.id
        username = update.effective_user.username or str(user_id)
        db.ensure_user(user_id, username)
        await update.message.reply_text(
            f"👋 Привет, {username}!\n\nЯ бот для игры в Bingo. Используй кнопки ниже, чтобы посмотреть свою статистику и достижения.\n\nДля участия в игре переходи в группу и нажимай кнопки там.",
            reply_markup=private_keyboard()
        )
    else:
        await update.message.reply_text(
            "Бот готов к работе. Используйте кнопки ниже.\nАдмин может запустить игру командой /startgame.",
            reply_markup=permanent_keyboard()
        )

# ========== Настройка команд в меню ==========
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Показать приветствие"),
        BotCommand("startgame", "(админ) Запустить игру"),
        BotCommand("stopgame", "(админ) Остановить игру"),
        BotCommand("bingo", "(админ) Сгенерировать числа"),
        BotCommand("ban", "(админ) Забанить пользователя"),
        BotCommand("unban", "(админ) Разбанить"),
        BotCommand("getid", "Узнать свой ID"),
        BotCommand("add_vip", "(админ) Выдать VIP статус"),
        BotCommand("remove_vip", "(админ) Снять VIP"),
        BotCommand("set_reputation", "(админ) Установить репутацию (0,1,2)"),
        BotCommand("add_donation", "(админ) Засчитать спонсорство игры"),
        BotCommand("add_shop", "(админ) Добавить магазин"),
        BotCommand("del_shop", "(админ) Удалить магазин"),
        BotCommand("list_shops", "(админ) Список магазинов"),
        BotCommand("add_exch", "(админ) Добавить обменник"),
        BotCommand("del_exch", "(админ) Удалить обменник"),
        BotCommand("list_exch", "(админ) Список обменников"),
    ])

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    async def post_init(application):
        await set_commands(application)
    app.post_init = post_init

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
    app.add_handler(CommandHandler("add_donation", add_donation))
    app.add_handler(CommandHandler("add_shop", add_shop))
    app.add_handler(CommandHandler("del_shop", del_shop))
    app.add_handler(CommandHandler("list_shops", list_shops))
    app.add_handler(CommandHandler("add_exch", add_exch))
    app.add_handler(CommandHandler("del_exch", del_exch))
    app.add_handler(CommandHandler("list_exch", list_exch))

    app.add_handler(CallbackQueryHandler(inline_callback, pattern="^(shop_|exch_|game_|register|my_combo|players_list|progress)"))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Записаться$"), handle_buttons)],
        states={
            WAITING_NUMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_numbers)],
            WAITING_VIP_NUMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_vip_numbers)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, greeting))

    print("Бот KidOk запущен. Без счётчика сообщений. Регистрация закрывается после первого /bingo.")
    app.run_polling()

