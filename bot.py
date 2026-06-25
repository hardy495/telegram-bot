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
ADMIN_FILE = "admin.json"
guest_states = {}
conversation_history = {}
pending_guest = {}
notification_to_guest = {}
time_request_to_guest = {}
extension_request_to_guest = {}
guest_extension_days = {}

# Связь имя гостя -> user_id для автоматической отправки реквизитов
guest_name_to_id = {}

# Храним суммы остатков: имя гостя -> сумма остатка
guest_balances = {}

DEPOSIT = 2000

PAYMENT_INFO = """+79181180045
СБЕРБАНК, Т-БАНК
Получатель: Антон Анатольевич А."""

def load_admin_chat_id():
    """Загрузить ADMIN_CHAT_ID из файла"""
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            data = json.load(f)
            return data.get("admin_chat_id")
    return None

def save_admin_chat_id(chat_id):
    """Сохранить ADMIN_CHAT_ID в файл"""
    with open(ADMIN_FILE, "w") as f:
        json.dump({"admin_chat_id": chat_id}, f)

ADMIN_CHAT_ID = load_admin_chat_id()

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
        text += "=== АПАРТАМЕНТЫ ===\n"
        for name, info in memory["objects"].items():
            text += f"\n--- {name} ---\n{info}\n"
    if memory["notes"]:
        text += "\n=== ЗАМЕТКИ ===\n"
        for i, note in enumerate(memory["notes"], 1):
            text += f"{i}. {note}\n"
    return text if text else "База знаний пока пуста."

SYSTEM_PROMPT = """Ты вежливый и профессиональный помощник для гостей апартаментов Alekseev Apartments.

Вот информация которую ты знаешь:
{knowledge}

=== ПРАВИЛА КОМПАНИИ ===
- Заселение дистанционное — гость заселяется самостоятельно через минисейф
- Пароль от минисейфа, домофона и другая информация придёт после подтверждения оплаты
- Стандартное время заезда: с 14:00
- Стандартное время выезда: до 12:00
- Ранний заезд (до 14:00): доплата 400 рублей за каждый час. Возможность зависит от занятости — нужно уточнять.
- Поздний выезд (после 12:00): доплата 400 рублей за каждый час. Возможность зависит от занятости — нужно уточнять.
- Залог 2000 рублей возвращается в день выезда до конца дня при отсутствии повреждений.

=== ОСНАЩЕНИЕ ВСЕХ АПАРТАМЕНТОВ ===
Во всех наших апартаментах есть:
- Утюг и гладильная доска
- Полотенца (для каждого гостя)
- Постельное бельё (чистое, заправлено)
- Фен
- Гель для душа

Если гость спрашивает об этих вещах — уверенно отвечай что всё это есть в апартаменте.


- Отвечай только на русском языке
- Будь вежлив и дружелюбен
- Используй только информацию из базы знаний и правил компании
- Не придумывай то чего нет в базе

Если гость спрашивает про ранний заезд — верни ровно: [РАННИЙ_ЗАЕЗД]
Если гость спрашивает про поздний выезд — верни ровно: [ПОЗДНИЙ_ВЫЕЗД]
Если гость хочет продлить проживание — верни ровно: [ПРОДЛЕНИЕ]
Если не можешь ответить на вопрос — верни ровно: [НУЖЕН_ОПЕРАТОР]
"""

def is_admin(user):
    return user.username and f"@{user.username}".lower() == ADMIN_USERNAME.lower()

async def notify_admin_question(context, question, user):
    if not ADMIN_CHAT_ID:
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"❓ *Вопрос от гостя {username}:*\n\n{question}\n\n"
             f"_Нажмите Reply и напишите ответ — он уйдёт гостю автоматически_",
        parse_mode="Markdown"
    )
    notification_to_guest[msg.message_id] = user.id

async def notify_admin_extension(context, user, days):
    if not ADMIN_CHAT_ID:
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    guest_name = f"ФИО: {context.user_data.get('guest_name', 'не указано')}" if hasattr(context, 'user_data') else ""
    msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🔄 *Запрос на продление*\n\n"
             f"Гость: {username}\n"
             f"{guest_name}\n"
             f"Хочет продлить на: *{days} сут.*\n\n"
             f"Возможно ли продление?\n"
             f"*Ответьте Reply: ДА сумма* (например: ДА 3000)\n"
             f"или *НЕТ*",
        parse_mode="Markdown"
    )
    extension_request_to_guest[msg.message_id] = {
        "guest_id": user.id,
        "days": days
    }

async def notify_admin_time_request(context, user, request_type, time_str, hours, amount):
    if not ADMIN_CHAT_ID:
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    type_text = "ранний заезд" if request_type == "early" else "поздний выезд"
    msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🕐 *Запрос на {type_text}*\n\n"
             f"Гость: {username}\n"
             f"Время: {time_str}\n"
             f"Часов: {hours}\n"
             f"Сумма доплаты: {amount} руб.\n\n"
             f"*Ответьте Reply: ДА или НЕТ*",
        parse_mode="Markdown"
    )
    time_request_to_guest[msg.message_id] = {
        "guest_id": user.id,
        "hours": hours,
        "amount": amount,
        "type": request_type,
        "time": time_str
    }

async def analyze_photo_with_ai(photo_bytes: bytes, expected_type: str, expected_amount: int = None) -> tuple[bool, str]:
    """
    Анализирует фото через Claude Vision.
    Возвращает (is_valid, message)
    """
    image_data = base64.standard_b64encode(photo_bytes).decode("utf-8")

    if expected_type == "passport":
        prompt = "Это паспорт или удостоверение личности? Ответь только ДА или НЕТ."
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        is_valid = response.content[0].text.strip().upper().startswith("ДА")
        return is_valid, ""

    else:
        # Проверяем чек и сумму
        if expected_amount:
            prompt = f"""Внимательно посмотри на этот чек или подтверждение платежа.

1. Это чек об оплате, квитанция или подтверждение платежа? 
2. Если да — найди сумму перевода в документе.
3. Сравни с ожидаемой суммой: {expected_amount} рублей.

Ответь строго в формате:
ЧЕК: ДА или НЕТ
СУММА: (напиши найденную сумму цифрами, или НЕИЗВЕСТНО если не видно)
СОВПАДАЕТ: ДА или НЕТ или НЕИЗВЕСТНО"""
        else:
            prompt = """Это чек об оплате, квитанция или подтверждение платежа? 
Ответь строго в формате:
ЧЕК: ДА или НЕТ
СУММА: (напиши найденную сумму цифрами, или НЕИЗВЕСТНО если не видно)
СОВПАДАЕТ: НЕИЗВЕСТНО"""

        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        result = response.content[0].text.strip()

        is_check = "ЧЕК: ДА" in result.upper()
        if not is_check:
            return False, "not_a_check"

        # Проверяем совпадение суммы
        if expected_amount and "СОВПАДАЕТ: НЕТ" in result.upper():
            # Извлекаем найденную сумму
            found_amount = "неизвестна"
            for line in result.split("\n"):
                if "СУММА:" in line.upper():
                    found_amount = line.split(":")[-1].strip()
            return False, f"wrong_amount:{found_amount}"

        return True, "ok"

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
        text=f"✅ Оплата от гостя {guest_name} подтверждена!\n\nВыберите апартамент для отправки информации о заселении:",
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

async def ask_guest_time(update, request_type):
    if request_type == "early":
        await update.message.reply_text(
            "🕐 *Ранний заезд*\n\n"
            "Стандартное время заезда — с 14:00.\n"
            "Ранний заезд возможен за доплату *400 рублей за каждый час* до 14:00.\n\n"
            "Укажите, пожалуйста, со скольки вы хотели бы заехать?\n"
            "_(например: с 11:00)_",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🕐 *Поздний выезд*\n\n"
            "Стандартное время выезда — до 12:00.\n"
            "Поздний выезд возможен за доплату *400 рублей за каждый час* после 12:00.\n\n"
            "Укажите, пожалуйста, до скольки вы хотели бы выехать?\n"
            "_(например: до 15:00)_",
            parse_mode="Markdown"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(update.effective_user):
        await update.message.reply_text(
            "Привет! Вы вошли как администратор 👋\n\n"
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/balance ФИО сумма — установить остаток по бронированию\n"
            "/remember текст — запомнить информацию\n"
            "/add название | инфо — добавить апартамент\n"
            "/list — база знаний\n"
            "/delnote номер — удалить заметку\n"
            "/delobj название — удалить апартамент\n\n"
            "💡 На вопросы гостей отвечайте через *Reply*.",
            parse_mode="Markdown"
        )
        return
    guest_states[user_id] = "asking_name"
    conversation_history[user_id] = []
    await update.message.reply_text(
        "Здравствуйте! 👋 Добро пожаловать в *Alekseev Apartments!*\n\n"
        "Рады вас приветствовать! 🏠\n\n"
        "Прежде чем начать оформление, важная информация:\n\n"
        "🔑 *Заселение у нас дистанционное* — встреча с администратором не требуется. "
        "Вы будете заселяться самостоятельно:\n"
        "• Ключи находятся в *минисейфе* — пароль от него вы получите после подтверждения оплаты\n"
        "• Пароль от *домофона* также придёт после подтверждения оплаты\n"
        "• Подробные инструкции и адрес вы получите сразу после оформления\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Для оформления нам одновременно потребуется:\n\n"
        "📄 *Фото паспорта* (лицевая сторона)\n"
        "💰 *Оплата:* остаток по бронированию + залог *2000 руб.*\n"
        "_(залог возвращается в день выезда до конца дня при отсутствии повреждений)_\n\n"
        "Для начала напишите *ФИО* на кого оформлена бронь 👇\n\n"
        "💬 _Если в процессе заселения или проживания возникнут любые вопросы — я всегда на связи и помогу разобраться!_",
        parse_mode="Markdown"
    )

async def set_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = str(update.effective_chat.id)
    save_admin_chat_id(ADMIN_CHAT_ID)
    await update.message.reply_text(
        "✅ Уведомления активированы!\n\n"
        "Когда гость задаёт вопрос — бот пришлёт уведомление.\n"
        "Нажмите *Reply* и напишите ответ — он уйдёт гостю! 👌",
        parse_mode="Markdown"
    )

async def set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить остаток по бронированию для гостя"""
    if not is_admin(update.effective_user):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование:\n/balance ФИО сумма\n\n"
            "Пример:\n/balance Иванов Иван Иванович 3500\n\n"
            "ФИО может быть несколько слов, последнее число — сумма остатка."
        )
        return
    try:
        amount = int(context.args[-1])
        name = " ".join(context.args[:-1]).strip()
        name_lower = name.lower()
        guest_balances[name_lower] = amount
        total = amount + DEPOSIT

        await update.message.reply_text(
            f"✅ Остаток установлен:\n\n"
            f"Гость: {name}\n"
            f"Остаток: {amount} руб.\n"
            f"Залог: {DEPOSIT} руб.\n"
            f"Итого: {total} руб.\n\n"
            f"Ищу гостя и отправляю ему реквизиты..."
        )

        # Ищем гостя по имени в словаре
        guest_id = None
        for saved_name, uid in guest_name_to_id.items():
            if name_lower in saved_name or saved_name in name_lower:
                guest_id = uid
                break

        if guest_id:
            await context.bot.send_message(
                chat_id=guest_id,
                text=f"💰 *Информация об оплате готова!*\n\n"
                     f"Для завершения оформления:\n\n"
                     f"• Остаток по бронированию: *{amount} руб.*\n"
                     f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня при отсутствии повреждений)_\n"
                     f"• *Итого: {total} руб.*\n\n"
                     f"Реквизиты для оплаты:\n{PAYMENT_INFO}\n\n"
                     f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.\n"
                     f"После оплаты пришлите чек в этот чат 🧾",
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"✅ Реквизиты автоматически отправлены гостю!")
        else:
            await update.message.reply_text(
                "⚠️ Гость ещё не написал боту или имя не совпало.\n"
                "Сумма сохранена — гость получит реквизиты автоматически когда напишет своё ФИО."
            )

    except ValueError:
        await update.message.reply_text("Последним аргументом укажите сумму цифрами.\nПример: /balance Иванов Иван 3500")

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
            "Пример:\n/add Апартамент №1 | Адрес: ул. Ленина 5, кв.10. Код домофона: 1234. Минисейф: код 5678. WiFi: MyHome, пароль: 12345678. Заселение с 14:00, выезд до 12:00."
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
    if guest_balances:
        text += "\n💰 *Остатки по бронированию:*\n"
        for name, amount in guest_balances.items():
            text += f"• {name}: {amount} руб.\n"
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

    await update.message.reply_text("🔍 Проверяю документ, подождите...")
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    photo_bytes = await photo_file.download_as_bytearray()

    if state == "waiting_passport":
        is_valid, _ = await analyze_photo_with_ai(bytes(photo_bytes), "passport")
        if not is_valid:
            await update.message.reply_text(
                "❌ Это не похоже на паспорт.\n\n"
                "Пожалуйста, пришлите фото *лицевой стороны паспорта* 📄\n\n"
                "Убедитесь что:\n• Фото чёткое и хорошо освещено\n• Видны все данные\n• Это именно паспорт",
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

        # Ищем сумму по имени гостя
        guest_name = context.user_data.get("guest_name", "").lower()
        balance = None
        for name_key, amount in guest_balances.items():
            if name_key in guest_name or guest_name in name_key:
                balance = amount
                break

        if balance is not None:
            total = balance + DEPOSIT
            await update.message.reply_text(
                "✅ Паспорт принят, спасибо!\n\n"
                f"💰 *Для завершения оформления необходимо оплатить:*\n\n"
                f"• Остаток по бронированию: *{balance} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня при отсутствии повреждений)_\n"
                f"• *Итого: {total} руб.*\n\n"
                f"Реквизиты для оплаты:\n{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.\n"
                f"После оплаты пришлите чек в этот чат 🧾",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "✅ Паспорт принят, спасибо!\n\n"
                "Сейчас уточню сумму остатка по вашей брони у администратора и сообщу вам в течение 10 минут. ⏱"
            )
            if ADMIN_CHAT_ID:
                msg = await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"⚠️ *Не найдена сумма для гостя!*\n\n"
                         f"Гость: {username}\n"
                         f"ФИО: {context.user_data.get('guest_name', 'не указано')}\n"
                         f"Ночей: {context.user_data.get('nights', 'не указано')}\n\n"
                         f"Установите сумму командой:\n"
                         f"`/balance {context.user_data.get('guest_name', 'ФИО')} СУММА`",
                    parse_mode="Markdown"
                )

    elif state == "waiting_payment":
        # Получаем ожидаемую сумму
        guest_name = context.user_data.get("guest_name", "").lower()
        expected_amount = None
        for name_key, amount in guest_balances.items():
            if name_key in guest_name or guest_name in name_key:
                expected_amount = amount + DEPOSIT
                break

        is_valid, reason = await analyze_photo_with_ai(bytes(photo_bytes), "payment", expected_amount)

        if not is_valid:
            if reason == "not_a_check":
                await update.message.reply_text(
                    "❌ Это не похоже на чек об оплате.\n\n"
                    "Пришлите *чек или подтверждение оплаты* 🧾\n\n"
                    "Это может быть:\n• Скриншот из банка\n• Фото бумажного чека\n• Подтверждение перевода",
                    parse_mode="Markdown"
                )
            elif reason.startswith("wrong_amount"):
                found = reason.split(":")[-1]
                # Пересылаем чек администратору с пометкой
                if ADMIN_CHAT_ID:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"⚠️ *Несовпадение суммы в чеке!*\n\n"
                             f"Гость: {username} (ID: {user_id})\n"
                             f"ФИО: {context.user_data.get('guest_name', 'не указано')}\n"
                             f"Сумма в чеке: *{found} руб.*\n"
                             f"Ожидаемая сумма: *{expected_amount} руб.*\n\n"
                             f"Чек гостя 👇",
                        parse_mode="Markdown"
                    )
                    await context.bot.forward_message(
                        chat_id=ADMIN_CHAT_ID,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                # Гостю сообщаем что документы на проверке
                await update.message.reply_text(
                    "⚠️ *Сумма в чеке не совпадает с указанной.*\n\n"
                    "Чек передан администратору на проверку.\n"
                    "Мы свяжемся с вами в течение 10 минут. ⏱",
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
            "Документы переданы на проверку оплаты.\n"
            "⏱ Обычно это занимает не более 10 минут.\n\n"
            "Пока ждёте — если есть вопросы, я готов помочь! 😊"
        )
        if ADMIN_CHAT_ID:
            await send_apartment_buttons(context, ADMIN_CHAT_ID, user_id, username)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    user_text = update.message.text
    state = guest_states.get(user_id)

    # Если админ отвечает через Reply
    if is_admin(user):
        reply_to = update.message.reply_to_message
        if reply_to:
            if reply_to.message_id in extension_request_to_guest:
                data = extension_request_to_guest[reply_to.message_id]
                guest_id = data["guest_id"]
                days = data["days"]
                answer = user_text.strip().upper()

                if answer.startswith("НЕТ"):
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text=f"😔 К сожалению, продление на {days} сут. в данный момент невозможно — "
                             f"апартамент уже забронирован.\n\n"
                             f"Если есть другие вопросы — готов помочь! 😊"
                    )
                    await update.message.reply_text("✅ Гость уведомлён об отказе.")
                elif answer.startswith("ДА"):
                    # Извлекаем сумму из ответа "ДА 3000"
                    parts = user_text.strip().split()
                    if len(parts) >= 2 and parts[-1].isdigit():
                        amount = int(parts[-1])
                        await context.bot.send_message(
                            chat_id=guest_id,
                            text=f"✅ *Продление согласовано!*\n\n"
                                 f"Количество суток: *{days} сут.*\n"
                                 f"Сумма за продление: *{amount} руб.*\n\n"
                                 f"Для оплаты переведите сумму:\n\n"
                                 f"{PAYMENT_INFO}\n\n"
                                 f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.\n"
                                 f"После оплаты пришлите чек в этот чат 🧾",
                            parse_mode="Markdown"
                        )
                        await update.message.reply_text("✅ Гость уведомлён и получил реквизиты для продления!")
                    else:
                        await update.message.reply_text(
                            "Укажите сумму после ДА.\nПример: *ДА 3000*",
                            parse_mode="Markdown"
                        )
                else:
                    await update.message.reply_text(
                        "Пожалуйста ответьте *ДА сумма* или *НЕТ*\nПример: ДА 3000",
                        parse_mode="Markdown"
                    )
                return

            if reply_to.message_id in time_request_to_guest:
                data = time_request_to_guest[reply_to.message_id]
                guest_id = data["guest_id"]
                answer = user_text.strip().upper()
                if answer == "ДА":
                    type_text = "Ранний заезд" if data["type"] == "early" else "Поздний выезд"
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text=f"✅ *{type_text} согласован!*\n\n"
                             f"Время: {data['time']}\n"
                             f"Количество часов: {data['hours']}\n"
                             f"Сумма доплаты: *{data['amount']} рублей*\n\n"
                             f"Для оплаты доплаты переведите сумму:\n\n"
                             f"{PAYMENT_INFO}\n\n"
                             f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.\n"
                             f"После оплаты пришлите чек в этот чат 🧾",
                        parse_mode="Markdown"
                    )
                    await update.message.reply_text("✅ Гость уведомлён и получил реквизиты!")
                elif answer == "НЕТ":
                    type_text = "ранний заезд" if data["type"] == "early" else "поздний выезд"
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text=f"😔 К сожалению, {type_text} на {data['time']} "
                             f"в данный момент невозможен — апартамент занят.\n\n"
                             f"Стандартное время {'заезда с 14:00' if data['type'] == 'early' else 'выезда до 12:00'}.\n\n"
                             f"Если есть другие вопросы — готов помочь! 😊"
                    )
                    await update.message.reply_text("✅ Гость уведомлён об отказе.")
                else:
                    await update.message.reply_text("Пожалуйста ответьте *ДА* или *НЕТ*", parse_mode="Markdown")
                return

            if reply_to.message_id in notification_to_guest:
                guest_id = notification_to_guest[reply_to.message_id]
                await context.bot.send_message(
                    chat_id=guest_id,
                    text=f"💬 *Ответ оператора:*\n\n{user_text}",
                    parse_mode="Markdown"
                )
                await update.message.reply_text("✅ Ответ отправлен гостю!")
                return

        await update.message.reply_text(
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/balance ФИО сумма — установить остаток по брони\n"
            "/remember текст — запомнить информацию\n"
            "/add название | инфо — добавить апартамент\n"
            "/list — база знаний\n"
            "/delnote номер — удалить заметку\n"
            "/delobj название — удалить апартамент"
        )
        return

    # Гость — спрашиваем ФИО
    if state == "asking_name":
        context.user_data["guest_name"] = user_text.strip()
        guest_name_to_id[user_text.strip().lower()] = user_id
        guest_states[user_id] = "waiting_passport"

        # Ищем сумму по имени гостя
        guest_name = user_text.strip().lower()
        balance = None
        for name_key, amount in guest_balances.items():
            if name_key in guest_name or guest_name in name_key:
                balance = amount
                break

        # Уведомляем админа о новом госте
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🆕 *Новый гость оформляется*\n\n"
                     f"ФИО: {user_text.strip()}\n"
                     f"ID: {user_id}\n\n"
                     f"{'✅ Сумма найдена: ' + str(balance) + ' руб.' if balance else '⚠️ Сумма не установлена! Используйте:'}\n"
                     f"{'' if balance else f'`/balance {user_text.strip()} СУММА`'}",
                parse_mode="Markdown"
            )

        if balance:
            total = balance + DEPOSIT
            await update.message.reply_text(
                f"Спасибо, {user_text.strip()}! 😊\n\n"
                "Для завершения оформления нам одновременно потребуется:\n\n"
                "📄 *1. Фото паспорта* (лицевая сторона)\n\n"
                f"💰 *2. Оплата:*\n"
                f"• Остаток по бронированию: *{balance} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня при отсутствии повреждений)_\n"
                f"• *Итого: {total} руб.*\n\n"
                f"Реквизиты для оплаты:\n{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.\n"
                
                f"Пожалуйста, пришлите фото паспорта и чек об оплате 📄🧾",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"Спасибо, {user_text.strip()}! 😊\n\n"
                "Для завершения оформления нам одновременно потребуется:\n\n"
                "📄 *1. Фото паспорта* (лицевая сторона)\n\n"
                "💰 *2. Оплата:* уточняем сумму у администратора — сообщим в течение 10 минут.\n\n"
                "Пока пришлите фото паспорта 📄",
                parse_mode="Markdown"
            )
        return

    if state == "waiting_passport":
        await update.message.reply_text("Пожалуйста, пришлите фото паспорта 📄")
        return

    if state == "waiting_payment":
        await update.message.reply_text("Пожалуйста, пришлите чек об оплате 🧾")
        return

    # Гость может задавать вопросы на любом этапе после ФИО
    if state in [None]:
        guest_states[user_id] = "asking_name"
        conversation_history[user_id] = []
        await update.message.reply_text(
            "Здравствуйте! 👋 Добро пожаловать в *Alekseev Apartments!*\n\n"
            "Рады вас приветствовать! 🏠\n\n"
            "Прежде чем начать оформление, важная информация:\n\n"
            "🔑 *Заселение у нас дистанционное* — встреча с администратором не требуется. "
            "Вы будете заселяться самостоятельно:\n"
            "• Ключи находятся в *минисейфе* — пароль от него вы получите после подтверждения оплаты\n"
            "• Пароль от *домофона* также придёт после подтверждения оплаты\n"
            "• Подробные инструкции и адрес вы получите сразу после оформления\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Для оформления нам одновременно потребуется:\n\n"
            "📄 *Фото паспорта* (лицевая сторона)\n"
            "💰 *Оплата:* остаток по бронированию + залог *2000 руб.*\n"
        "Для начала напишите *ФИО* на кого оформлена бронь 👇\n\n"
        "💬 _Если в процессе заселения или проживания возникнут любые вопросы — я всегда на связи и помогу разобраться!_",
            "Для начала напишите *ФИО* на кого оформлена бронь 👇",
            parse_mode="Markdown"
        )
        return

    # Проверяем запрос на время
    if guest_states.get(user_id) == "waiting_time_early":
        time_str = user_text.strip()
        try:
            hour = int(time_str.replace(":", "").replace("с ", "").replace(" ", "")[:2])
            hours = 14 - hour
            if hours <= 0:
                await update.message.reply_text("Укажите время до 14:00. _(например: с 11:00)_", parse_mode="Markdown")
                return
            amount = hours * 400
            await notify_admin_time_request(context, user, "early", time_str, hours, amount)
            await update.message.reply_text(
                f"Вы хотите заехать в *{time_str}*.\n\n"
                f"Часов раннего заезда: *{hours} ч.*\n"
                f"Сумма доплаты: *{amount} рублей*\n\n"
                f"Уточняю возможность у администратора — отвечу в течение 10 минут! ⏱",
                parse_mode="Markdown"
            )
        except:
            await notify_admin_time_request(context, user, "early", time_str, 0, 0)
            await update.message.reply_text(f"Запрос на ранний заезд ({time_str}) передан администратору. Ответим в течение 10 минут! ⏱")
        guest_states[user_id] = "verified"
        return

    if guest_states.get(user_id) == "waiting_time_late":
        time_str = user_text.strip()
        try:
            hour = int(time_str.replace(":", "").replace("до ", "").replace(" ", "")[:2])
            hours = hour - 12
            if hours <= 0:
                await update.message.reply_text("Укажите время после 12:00. _(например: до 15:00)_", parse_mode="Markdown")
                return
            amount = hours * 400
            await notify_admin_time_request(context, user, "late", time_str, hours, amount)
            await update.message.reply_text(
                f"Вы хотите выехать в *{time_str}*.\n\n"
                f"Часов позднего выезда: *{hours} ч.*\n"
                f"Сумма доплаты: *{amount} рублей*\n\n"
                f"Уточняю возможность у администратора — отвечу в течение 10 минут! ⏱",
                parse_mode="Markdown"
            )
        except:
            await notify_admin_time_request(context, user, "late", time_str, 0, 0)
            await update.message.reply_text(f"Запрос на поздний выезд ({time_str}) передан администратору. Ответим в течение 10 минут! ⏱")
        guest_states[user_id] = "verified"
        return

    if guest_states.get(user_id) == "waiting_extension_days":
        days = user_text.strip()
        guest_states[user_id] = "verified"
        await notify_admin_extension(context, user, days)
        await update.message.reply_text(
            f"Отлично! Запрос на продление на *{days} сут.* отправлен администратору.\n\n"
            f"Ответим в течение 10 минут — если продление возможно, пришлём реквизиты для оплаты. ⏱",
            parse_mode="Markdown"
        )
        return


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

    if "[РАННИЙ_ЗАЕЗД]" in reply:
        guest_states[user_id] = "waiting_time_early"
        await ask_guest_time(update, "early")
    elif "[ПОЗДНИЙ_ВЫЕЗД]" in reply:
        guest_states[user_id] = "waiting_time_late"
        await ask_guest_time(update, "late")
    elif "[ПРОДЛЕНИЕ]" in reply:
        guest_states[user_id] = "waiting_extension_days"
        await update.message.reply_text(
            "🔄 *Продление проживания*\n\n"
            "На сколько суток вы хотели бы продлить?\n"
            "_(например: 1 или 2)_",
            parse_mode="Markdown"
        )
    elif "[НУЖЕН_ОПЕРАТОР]" in reply:
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
app.add_handler(CommandHandler("balance", set_balance))
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
