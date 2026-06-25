import os
import json
import base64
import anthropic
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
ADMIN_USERNAME = "@Hardy495"
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

MEMORY_FILE = "memory.json"
guest_states = {}
conversation_history = {}
pending_guest = {}

# Храним: message_id уведомления -> guest_id
# Чтобы когда админ делает Reply — знать кому отвечать
notification_to_guest = {}

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notes": [], "objects": {}}

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def get_all_knowledge():
    memory = load_memory()
    text = ""
    if memory["objects"]:
        text += "=== ОБЪЕКТЫ ===\n"
        for name, info in memory["objects"].items():
            text += f"\n--- {name} ---\n{info}\n"
    if memory["notes"]:
        text += "\n=== ЗАМЕТКИ И НЮАНСЫ ===\n"
        for i, note in enumerate(memory["notes"], 1):
            text += f"{i}. {note}\n"
    return text if text else "База знаний пока пуста."

SYSTEM_PROMPT = """Ты вежливый и профессиональный помощник для гостей апартаментов Alekseev Apartments.

Вот вся информация которую ты знаешь:
{knowledge}

Правила:
- Отвечай только на русском языке
- Будь вежлив и дружелюбен
- Используй только информацию из базы знаний
- Не придумывай то чего нет в базе

Если не можешь ответить — верни ровно: [НУЖЕН_ОПЕРАТОР]
"""

def is_admin(user):
    return user.username and f"@{user.username}".lower() == ADMIN_USERNAME.lower()

async def notify_admin_question(context, question, user):
    """Уведомить админа о вопросе гостя и сохранить связь message_id -> guest_id"""
    if not ADMIN_CHAT_ID:
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"❓ *Вопрос от гостя {username}:*\n\n{question}\n\n"
             f"_Нажмите Reply на это сообщение и напишите ответ — он автоматически уйдёт гостю_",
        parse_mode="Markdown"
    )
    # Сохраняем связь: message_id -> guest user_id
    notification_to_guest[msg.message_id] = user.id

async def analyze_photo_with_ai(photo_bytes: bytes, expected_type: str) -> tuple[bool, str]:
    image_data = base64.standard_b64encode(photo_bytes).decode("utf-8")
    if expected_type == "passport":
        prompt = """Внимательно посмотри на это изображение. 
        Это паспорт или документ удостоверяющий личность? 
        Ответь только: ДА если это паспорт/удостоверение личности, или НЕТ если это что-то другое.
        После ДА или НЕТ напиши через | краткое объяснение на русском."""
    else:
        prompt = """Внимательно посмотри на это изображение.
        Это чек об оплате, квитанция или подтверждение платежа?
        Ответь только: ДА если это чек/квитанция/подтверждение оплаты, или НЕТ если это что-то другое.
        После ДА или НЕТ напиши через | краткое объяснение на русском."""

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    result = response.content[0].text.strip()
    is_valid = result.upper().startswith("ДА")
    explanation = result.split("|")[1].strip() if "|" in result else ""
    return is_valid, explanation

async def send_apartment_buttons(context, chat_id, guest_id, guest_name):
    memory = load_memory()
    objects = memory.get("objects", {})
    if not objects:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ База апартаментов пуста! Добавьте объекты через /add"
        )
        return
    pending_guest[str(chat_id)] = guest_id
    buttons = []
    for name in objects.keys():
        buttons.append([InlineKeyboardButton(f"🏠 {name}", callback_data=f"apt_{name}")])
    keyboard = InlineKeyboardMarkup(buttons)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Документы гостя {guest_name} проверены!\n\nВыберите апартамент:",
        reply_markup=keyboard
    )

async def handle_apartment_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("apt_"):
        return
    apt_name = query.data[4:]
    admin_chat_id = str(query.message.chat_id)
    guest_id = pending_guest.get(admin_chat_id)
    if not guest_id:
        await query.edit_message_text("❌ Не удалось найти гостя.")
        return
    memory = load_memory()
    apt_info = memory["objects"].get(apt_name)
    if not apt_info:
        await query.edit_message_text(f"❌ Апартамент '{apt_name}' не найден.")
        return
    await context.bot.send_message(
        chat_id=guest_id,
        text=f"✅ Ваша оплата подтверждена!\n\n"
             f"🏠 *{apt_name}*\n\n{apt_info}\n\n"
             f"Если возникнут вопросы — я всегда готов помочь! 😊",
        parse_mode="Markdown"
    )
    guest_states[guest_id] = "verified"
    conversation_history[guest_id] = []
    await query.edit_message_text(
        f"✅ Информация по *{apt_name}* отправлена гостю!",
        parse_mode="Markdown"
    )
    del pending_guest[admin_chat_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(update.effective_user):
        await update.message.reply_text(
            "Привет! Вы вошли как администратор 👋\n\n"
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/remember [текст] — запомнить информацию\n"
            "/add [название] | [инфо] — добавить апартамент\n"
            "/list — база знаний\n"
            "/delnote [номер] — удалить заметку\n"
            "/delobj [название] — удалить апартамент\n\n"
            "💡 Когда гость задаёт вопрос которого нет в базе — бот пришлёт его сюда. "
            "Нажмите *Reply* на сообщение и напишите ответ — он уйдёт гостю автоматически.",
            parse_mode="Markdown"
        )
        return
    guest_states[user_id] = "waiting_passport"
    conversation_history[user_id] = []
    await update.message.reply_text(
        "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
        "Я помогу вам с заселением и отвечу на все вопросы.\n\n"
        "Для начала нам необходимо верифицировать вас:\n"
        "1️⃣ Фото паспорта (лицевая сторона)\n"
        "2️⃣ Чек об оплате\n\n"
        "Пожалуйста, пришлите фото паспорта 📄"
    )

async def set_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = str(update.effective_chat.id)
    await update.message.reply_text(
        "✅ Уведомления активированы!\n\n"
        "Теперь когда гость задаёт сложный вопрос — бот пришлёт его сюда.\n"
        "Нажмите *Reply* и напишите ответ — он уйдёт гостю автоматически! 👌",
        parse_mode="Markdown"
    )

async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_text("Использование: /remember [текст]")
        return
    note = " ".join(context.args)
    memory = load_memory()
    memory["notes"].append(note)
    save_memory(memory)
    await update.message.reply_text(f"✅ Запомнил:\n\n{note}")

async def add_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_text(
            "Использование:\n/add Название | Информация\n\n"
            "Пример:\n/add Апартамент №1 | Адрес: ул. Ленина 5, кв.10. Код домофона: 1234. "
            "WiFi: MyHome, пароль: 12345678. Заселение с 14:00, выезд до 12:00."
        )
        return
    full_text = " ".join(context.args)
    if "|" not in full_text:
        await update.message.reply_text("Используйте | для разделения названия и информации.")
        return
    name, info = full_text.split("|", 1)
    memory = load_memory()
    memory["objects"][name.strip()] = info.strip()
    save_memory(memory)
    await update.message.reply_text(f"✅ Апартамент '{name.strip()}' добавлен!")

async def list_knowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    memory = load_memory()
    text = "📋 *Вся база знаний:*\n\n"
    if memory["objects"]:
        text += "🏠 *Апартаменты:*\n"
        for name, info in memory["objects"].items():
            text += f"\n*{name}*\n{info}\n"
    else:
        text += "🏠 Апартаменты: пусто\n"
    if memory["notes"]:
        text += "\n📝 *Заметки:*\n"
        for i, note in enumerate(memory["notes"], 1):
            text += f"{i}. {note}\n"
    else:
        text += "\n📝 Заметки: пусто\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_text("Использование: /delnote [номер]")
        return
    try:
        index = int(context.args[0]) - 1
        memory = load_memory()
        if 0 <= index < len(memory["notes"]):
            removed = memory["notes"].pop(index)
            save_memory(memory)
            await update.message.reply_text(f"✅ Удалено:\n{removed}")
        else:
            await update.message.reply_text("Заметка не найдена.")
    except ValueError:
        await update.message.reply_text("Укажите номер цифрой.")

async def delete_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_text("Использование: /delobj Название")
        return
    name = " ".join(context.args)
    memory = load_memory()
    if name in memory["objects"]:
        del memory["objects"][name]
        save_memory(memory)
        await update.message.reply_text(f"✅ Апартамент '{name}' удалён.")
    else:
        await update.message.reply_text(f"Апартамент '{name}' не найден.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    state = guest_states.get(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"

    if state not in ["waiting_passport", "waiting_payment"]:
        await update.message.reply_text("Спасибо за фото! Если есть вопросы — задавайте 😊")
        return

    await update.message.reply_text("🔍 Проверяю документ...")
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    photo_bytes = await photo_file.download_as_bytearray()

    if state == "waiting_passport":
        is_valid, _ = await analyze_photo_with_ai(bytes(photo_bytes), "passport")
        if not is_valid:
            await update.message.reply_text(
                "❌ Это не похоже на паспорт.\n\n"
                "Пожалуйста, пришлите фото *лицевой стороны паспорта* 📄\n\n"
                "Убедитесь что:\n• Фото чёткое\n• Видны все данные\n• Это именно паспорт",
                parse_mode="Markdown"
            )
            return
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📄 *Паспорт от гостя:* {username} (ID: {user_id})\n✅ ИИ подтвердил",
                parse_mode="Markdown"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_states[user_id] = "waiting_payment"
        await update.message.reply_text("✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾")

    elif state == "waiting_payment":
        is_valid, _ = await analyze_photo_with_ai(bytes(photo_bytes), "payment")
        if not is_valid:
            await update.message.reply_text(
                "❌ Это не похоже на чек об оплате.\n\n"
                "Пришлите *чек или подтверждение оплаты* 🧾\n\n"
                "Это может быть:\n• Скриншот из банка\n• Фото бумажного чека\n• Подтверждение перевода",
                parse_mode="Markdown"
            )
            return
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🧾 *Чек от гостя:* {username} (ID: {user_id})\n✅ ИИ подтвердил",
                parse_mode="Markdown"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_states[user_id] = "waiting_admin_confirmation"
        await update.message.reply_text(
            "✅ Чек получен!\n\n"
            "Документы переданы на проверку. "
            "Как только оплата подтверждена — вы получите всю информацию о заселении.\n\n"
            "⏱ Обычно это занимает не более 10 минут."
        )
        if ADMIN_CHAT_ID:
            await send_apartment_buttons(context, ADMIN_CHAT_ID, user_id, username)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    user_text = update.message.text
    state = guest_states.get(user_id)

    # Если это админ отвечает через Reply на вопрос гостя
    if is_admin(user):
        reply_to = update.message.reply_to_message
        if reply_to and reply_to.message_id in notification_to_guest:
            guest_id = notification_to_guest[reply_to.message_id]
            await context.bot.send_message(
                chat_id=guest_id,
                text=f"💬 *Ответ оператора:*\n\n{user_text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ Ответ отправлен гостю!")
            return
        # Обычное сообщение от админа
        await update.message.reply_text(
            "Привет! Команды:\n"
            "/admin — активировать уведомления\n"
            "/remember [текст] — запомнить информацию\n"
            "/add [название] | [инфо] — добавить апартамент\n"
            "/list — база знаний\n"
            "/delnote [номер] — удалить заметку\n"
            "/delobj [название] — удалить апартамент"
        )
        return

    if state is None:
        guest_states[user_id] = "waiting_passport"
        await update.message.reply_text(
            "Здравствуйте! 👋\n\nДля начала пришлите фото паспорта (лицевая сторона) 📄"
        )
        return

    if state == "waiting_passport":
        await update.message.reply_text("Пожалуйста, пришлите фото паспорта 📄")
        return

    if state == "waiting_payment":
        await update.message.reply_text("Пожалуйста, пришлите чек об оплате 🧾")
        return

    if state == "waiting_admin_confirmation":
        await update.message.reply_text(
            "⏱ Ваши документы на проверке.\n"
            "Оператор подтвердит оплату в течение 10 минут."
        )
        return

    # Верифицированный гость — отвечаем через Claude
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": user_text})

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT.format(knowledge=get_all_knowledge()),
        messages=conversation_history[user_id]
    )

    reply = response.content[0].text

    if "[НУЖЕН_ОПЕРАТОР]" in reply:
        await notify_admin_question(context, user_text, user)
        await update.message.reply_text(
            "Спасибо за ваш вопрос! 🙏\n\n"
            "По этому вопросу с вами свяжется оператор в течение 10 минут."
        )
    else:
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", set_admin_id))
app.add_handler(CommandHandler("remember", remember))
app.add_handler(CommandHandler("add", add_object))
app.add_handler(CommandHandler("list", list_knowledge))
app.add_handler(CommandHandler("delnote", delete_note))
app.add_handler(CommandHandler("delobj", delete_object))
app.add_handler(CallbackQueryHandler(handle_apartment_selection))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен!")
app.run_polling()
