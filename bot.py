import os
import json
import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
ADMIN_USERNAME = "@Hardy495"
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

MEMORY_FILE = "memory.json"
guest_states = {}
conversation_history = {}

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

SYSTEM_PROMPT = """Ты вежливый и профессиональный помощник для гостей. Ты помогаешь гостям с вопросами о заселении и проживании.

Вот вся информация которую ты знаешь:
{knowledge}

Правила общения:
- Отвечай только на русском языке
- Будь вежлив и дружелюбен
- Используй всю доступную информацию чтобы помочь гостю
- Не придумывай информацию которой нет в базе знаний
- Если вопрос касается конкретного объекта — дай информацию только по нему

Если ты не можешь ответить на вопрос — верни ровно эту фразу без изменений: [НУЖЕН_ОПЕРАТОР]
"""

def is_admin(user):
    return user.username and f"@{user.username}".lower() == ADMIN_USERNAME.lower()

async def notify_admin(context, message, user):
    if ADMIN_CHAT_ID:
        username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 *Требуется ваше внимание!*\n\nГость: {username}\nВопрос: {message}",
            parse_mode="Markdown"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(update.effective_user):
        await update.message.reply_text(
            "Привет! Вы вошли как администратор 👋\n\n"
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/remember [текст] — запомнить информацию\n"
            "/add [название] | [инфо] — добавить объект\n"
            "/list — вся база знаний\n"
            "/delnote [номер] — удалить заметку\n"
            "/delobj [название] — удалить объект"
        )
        return
    guest_states[user_id] = "waiting_passport"
    conversation_history[user_id] = []
    await update.message.reply_text(
        "Здравствуйте! 👋 Добро пожаловать!\n\n"
        "Я помогу вам с информацией о заселении и отвечу на ваши вопросы.\n\n"
        "Для начала нам необходимо:\n"
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
        "📋 Ваши команды:\n"
        "/remember [текст] — запомнить любую информацию\n"
        "/add [название] | [информация] — добавить объект\n"
        "/list — посмотреть всю базу знаний\n"
        "/delnote [номер] — удалить заметку\n"
        "/delobj [название] — удалить объект"
    )

async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование:\n/remember [любая информация]\n\n"
            "Примеры:\n"
            "/remember Гостям нельзя курить в квартире\n"
            "/remember Парковка бесплатная во дворе всех объектов\n"
            "/remember Если сломался замок — мастер 89001234567"
        )
        return
    note = " ".join(context.args)
    memory = load_memory()
    memory["notes"].append(note)
    save_memory(memory)
    await update.message.reply_text(f"✅ Запомнил:\n\n{note}")

async def add_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование:\n/add Название | Информация\n\n"
            "Пример:\n/add Квартира Ленина 5 | Код домофона: 1234, WiFi: MyHome пароль 12345678, заселение с 14:00"
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
    await update.message.reply_text(f"✅ Объект '{name.strip()}' добавлен!")

async def list_knowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    memory = load_memory()
    text = "📋 *Вся база знаний:*\n\n"
    if memory["objects"]:
        text += "🏠 *Объекты:*\n"
        for name, info in memory["objects"].items():
            text += f"\n*{name}*\n{info}\n"
    else:
        text += "🏠 Объекты: пусто\n"
    if memory["notes"]:
        text += "\n📝 *Заметки:*\n"
        for i, note in enumerate(memory["notes"], 1):
            text += f"{i}. {note}\n"
    else:
        text += "\n📝 Заметки: пусто\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /delnote [номер]\nНомер смотрите в /list")
        return
    try:
        index = int(context.args[0]) - 1
        memory = load_memory()
        if 0 <= index < len(memory["notes"]):
            removed = memory["notes"].pop(index)
            save_memory(memory)
            await update.message.reply_text(f"✅ Удалено:\n{removed}")
        else:
            await update.message.reply_text("Заметка с таким номером не найдена.")
    except ValueError:
        await update.message.reply_text("Укажите номер заметки цифрой.")

async def delete_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /delobj Название объекта")
        return
    name = " ".join(context.args)
    memory = load_memory()
    if name in memory["objects"]:
        del memory["objects"][name]
        save_memory(memory)
        await update.message.reply_text(f"✅ Объект '{name}' удалён.")
    else:
        await update.message.reply_text(f"Объект '{name}' не найден. Проверьте название в /list")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    state = guest_states.get(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"

    if state == "waiting_passport":
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📄 Паспорт от гостя: {username} (ID: {user_id})"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_states[user_id] = "waiting_payment"
        await update.message.reply_text(
            "✅ Паспорт получен, спасибо!\n\n"
            "Теперь пришлите чек об оплате 🧾"
        )
    elif state == "waiting_payment":
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🧾 Чек от гостя: {username} (ID: {user_id})\nПроверьте оплату и подтвердите гостю."
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_states[user_id] = "verified"
        conversation_history[user_id] = []
        await update.message.reply_text(
            "✅ Чек получен!\n\n"
            "Документы переданы на проверку. Как только оплата подтверждена — "
            "вы получите всю информацию о заселении.\n\n"
            "Если есть вопросы — я готов помочь! 😊"
        )
    else:
        await update.message.reply_text("Спасибо за фото! Если есть вопросы — задавайте 😊")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    user_text = update.message.text
    state = guest_states.get(user_id)

    if is_admin(user):
        await update.message.reply_text(
            "Привет! Вы вошли как администратор 👋\n\n"
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/remember [текст] — запомнить информацию\n"
            "/add [название] | [инфо] — добавить объект\n"
            "/list — вся база знаний\n"
            "/delnote [номер] — удалить заметку\n"
            "/delobj [название] — удалить объект"
        )
        return

    if state is None:
        guest_states[user_id] = "waiting_passport"
        await update.message.reply_text(
            "Здравствуйте! 👋\n\n"
            "Для начала пришлите фото паспорта (лицевая сторона) 📄"
        )
        return

    if state == "waiting_passport":
        await update.message.reply_text("Пожалуйста, пришлите фото паспорта (лицевая сторона) 📄")
        return

    if state == "waiting_payment":
        await update.message.reply_text("Пожалуйста, пришлите чек об оплате 🧾")
        return

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
        await notify_admin(context, user_text, user)
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
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен!")
app.run_polling()
