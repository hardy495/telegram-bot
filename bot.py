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

# Храним брони: ключ -> {name, date_from, date_to, amount}
# Ключ: "имя_дата_заезда" для уникальности
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

=== СТРОГИЙ ЗАПРЕТ ===
Ты НИКОГДА не сообщаешь гостю:
- Адрес апартамента
- Код домофона или калитки
- Пароль от минисейфа
- Пароль WiFi
- Номер квартиры или этажа
- Любые инструкции по заселению и коды доступа

Эта информация передаётся ТОЛЬКО администратором после подтверждения оплаты.
Если гость спрашивает адрес, код, пароль или как попасть — отвечай:
"Эта информация будет отправлена вам администратором после подтверждения оплаты. ⏱"

=== ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ ===
{knowledge}

=== ПРАВИЛА КОМПАНИИ ===
- Заселение дистанционное — гость заселяется самостоятельно через минисейф
- Пароль от минисейфа и домофона придёт после подтверждения оплаты
- Стандартное время заезда: с 14:00
- Стандартное время выезда: до 12:00
- Ранний заезд (до 14:00): доплата 400 рублей за каждый час. Возможность зависит от занятости — нужно уточнять.
- Поздний выезд (после 12:00): доплата 400 рублей за каждый час. Возможность зависит от занятости — нужно уточнять.
- Залог 2000 рублей возвращается в день выезда до конца дня при отсутствии повреждений.

=== ОСНАЩЕНИЕ ВСЕХ АПАРТАМЕНТОВ ===
Во всех апартаментах есть: утюг, гладильная доска, полотенца, постельное бельё, фен, гель для душа.

=== ПАРКОВКА И ВЪЕЗД НА ТЕРРИТОРИЮ ===
Для апартаментов на ул. Октябрьской:
• Запарковаться можно в любом свободном месте во дворе
• Въезд во двор возможен через любые ворота — основной трафик через первые ворота
• Первые ворота находятся со стороны ул. Октябрьская между двумя магазинами Пятёрочка
• Альтернатива: парковка со стороны Галереи вдоль дороги или со стороны ул. Кирова — там платная городская парковка с 8:00 до 20:00 по будням

Для апартамента на ул. Красная 176:
• Платная парковка на -1 этаже здания — индивидуальное место стоит 1000 руб/сутки
• Бесплатная парковка на ул. Путевая
• Платная парковка непосредственно с ул. Красная 176 при наличии свободных мест — 60 руб/час по будням с 8:00 до 20:00

Если гость спрашивает про парковку на Красной 176 и интересуется индивидуальным местом — верни ровно: [ПАРКОВКА_КРАСНАЯ]

Для апартамента на ул. Гаражная 107:
• Можно заехать под шлагбаум на трафике и запарковаться в любом свободном месте во дворе
• Чтобы выехать — достаточно подъехать поближе к шлагбауму, он откроется автоматически
• Рекомендуем парковаться возле Пятёрочки или вдоль дорог — там самая удобная парковка

Для апартамента на ул. Коммунаров 270:
• Запарковаться можно в любом месте вокруг дома или вдоль дороги
• Городская платная парковка — 60 руб/час с 8:00 до 20:00 по будням
• Двор в этом доме без машин — во дворе автомобили не паркуются
• Вход во двор — с ул. Одесской через калитку
• Важно: вам нужен именно 2-й подъезд дома Коммунаров 270 к1, а не Коммунаров 270! Дома выглядят как одно здание, но 2-й подъезд находится в самом конце дома

=== КАК ПОЛЬЗОВАТЬСЯ МИНИСЕЙФОМ ===
Минисейф находится рядом с входом в квартиру.
Как открыть:
1. На минисейфе есть чёрный рычажок — опустите его вниз
2. Одновременно потяните дверцу минисейфа на себя (открывается сверху вниз)
3. Внутри лежат ключи — берите и открывайте квартиру

⚠️ Если не срабатывает пароль от домофона или минисейфа, и рычажок не опускается вниз — скорее всего вы зашли не в тот подъезд или корпус. Проверьте номер подъезда и корпуса. Это особенно легко перепутать в наших апартаментах на Октябрьской где несколько корпусов.

=== ПРАВИЛА ОБЩЕНИЯ ===
- Отвечай только на русском языке
- Будь вежлив и дружелюбен
- Помогай с любыми вопросами кроме инструкций по заселению
- Не придумывай информацию которой нет в базе

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

        # Извлекаем найденную сумму всегда
        found_amount = "неизвестна"
        for line in result.split("\n"):
            if "СУММА:" in line.upper():
                found_amount = line.split(":")[-1].strip()

        # Проверяем совпадение суммы
        if expected_amount and "СОВПАДАЕТ: НЕТ" in result.upper():
            return False, f"wrong_amount:{found_amount}"

        return True, f"ok:{found_amount}"

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
    for i, name in enumerate(objects.keys()):
        # Используем индекс вместо названия чтобы не превышать лимит 64 байта
        buttons.append([InlineKeyboardButton(f"🏠 {name}", callback_data=f"apt_{i}")])
    keyboard = InlineKeyboardMarkup(buttons)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Оплата от гостя {guest_name} подтверждена!\n\nВыберите апартамент:",
        reply_markup=keyboard
    )

async def handle_apartment_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Кнопка "Купить парк/место"
    if query.data.startswith("parking_"):
        guest_id = int(query.data.split("_")[1])
        username_obj = query.from_user
        guest_username = f"@{username_obj.username}" if username_obj.username else f"{username_obj.first_name}"

        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🅿️ *Запрос на покупку парковочного места*\n\n"
                     f"Гость: {guest_username}\n"
                     f"Апартамент: Красная 176\n\n"
                     f"Гость хочет приобрести индивидуальное парковочное место (1000 руб/сутки).",
                parse_mode="Markdown"
            )
        await query.answer("Запрос отправлен администратору!")
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=guest_id,
            text="✅ Запрос на парковочное место отправлен!\n\n"
                 "Администратор свяжется с вами в течение 10 минут. ⏱"
        )


    # Кнопка "Это паспорт" для PDF
    elif query.data.startswith("pdf_passport_"):
        guest_id = int(query.data.split("_")[2])
        context.bot_data.setdefault("pdf_docs", {}).setdefault(guest_id, {})["has_passport"] = True
        guest_states[guest_id] = "waiting_docs"
        await context.bot.send_message(
            chat_id=guest_id,
            text="✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾"
        )
        await query.edit_message_text("✅ Паспорт гостя подтверждён!")

    # Кнопка "Это чек" для PDF
    elif query.data.startswith("pdf_check_"):
        guest_id = int(query.data.split("_")[2])
        pdf_docs = context.bot_data.setdefault("pdf_docs", {}).setdefault(guest_id, {})
        has_passport = pdf_docs.get("has_passport", False)
        pdf_docs["has_payment"] = True

        if has_passport:
            guest_states[guest_id] = "waiting_admin_confirmation"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Получил", callback_data=f"received_{guest_id}"),
                InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{guest_id}")
            ]])
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Подтвердите получение оплаты:", reply_markup=keyboard)
            await context.bot.send_message(
                chat_id=guest_id,
                text="✅ Все документы получены!\n\nПередано на проверку оплаты. ⏱\nОбычно до 10 минут.\n\nЕсли есть вопросы — готов помочь! 😊"
            )
        else:
            guest_states[guest_id] = "waiting_docs"
            await context.bot.send_message(
                chat_id=guest_id,
                text="✅ Чек принят!\n\nТеперь пришлите фото паспорта 📄"
            )
        await query.edit_message_text("✅ Чек гостя подтверждён!")

    # Кнопка "Получил"
    elif query.data.startswith("received_"):
        guest_id = int(query.data.split("_")[1])
        admin_chat_id = str(query.message.chat_id)
        pending_guest[admin_chat_id] = guest_id

        memory = load_memory()
        objects = memory.get("objects", {})
        if not objects:
            await query.edit_message_text("⚠️ База апартаментов пуста!")
            return

        buttons = []
        for i, name in enumerate(objects.keys()):
            buttons.append([InlineKeyboardButton(f"🏠 {name}", callback_data=f"apt_{i}")])
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(
            "✅ Оплата получена!\n\nВыберите апартамент для отправки гостю:",
            reply_markup=keyboard
        )

    # Кнопка "Не получил"
    elif query.data.startswith("not_received_"):
        guest_id = int(query.data.split("_")[2])
        await context.bot.send_message(
            chat_id=guest_id,
            text=f"⚠️ Оплата не поступила.\n\n"
                 f"Пожалуйста, проверьте правильность перевода и пришлите чек повторно.\n\n"
                 f"Реквизиты для оплаты:\n{PAYMENT_INFO}\n\n"
                 f"При переводе ничего не пишите в комментарии к платежу."
        )
        guest_states[guest_id] = "waiting_payment"
        await query.edit_message_text("❌ Гость уведомлён — оплата не поступила.")

    # Выбор апартамента по индексу
    elif query.data.startswith("apt_"):
        try:
            apt_index = int(query.data[4:])
        except:
            await query.edit_message_text("❌ Ошибка выбора апартамента.")
            return

        admin_chat_id = str(query.message.chat_id)
        guest_id = pending_guest.get(admin_chat_id)
        if not guest_id:
            await query.edit_message_text("❌ Не удалось найти гостя. Попробуйте снова.")
            return

        memory = load_memory()
        objects = memory.get("objects", {})
        apt_names = list(objects.keys())

        if apt_index >= len(apt_names):
            await query.edit_message_text("❌ Апартамент не найден.")
            return

        apt_name = apt_names[apt_index]
        apt_info = objects[apt_name]

        # Кнопки "Мы выехали" и "Новая бронь"
        checkout_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚪 Мы выехали", callback_data=f"checkout_{guest_id}_{apt_name[:20]}"),
                InlineKeyboardButton("🔄 Продление/Новая бронь", callback_data=f"newbooking_{guest_id}")
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=guest_id,
                text=f"✅ Ваша оплата подтверждена!\n\n{apt_info}\n\nЕсли возникнут вопросы — я всегда готов помочь! 😊",
                parse_mode="HTML",
                reply_markup=checkout_keyboard
            )
        except Exception:
            import re
            clean_info = re.sub(r'<[^>]+>', '', apt_info)
            await context.bot.send_message(
                chat_id=guest_id,
                text=f"✅ Ваша оплата подтверждена!\n\n{clean_info}\n\nЕсли возникнут вопросы — я всегда готов помочь! 😊",
                reply_markup=checkout_keyboard
            )

        # Сохраняем апартамент гостя для контекста
        guest_states[guest_id] = "verified"
        context.bot_data.setdefault("guest_apt", {})[guest_id] = apt_name
        conversation_history[guest_id] = []
        await query.edit_message_text(f"✅ Информация по апартаменту отправлена гостю!")
        del pending_guest[admin_chat_id]

    # Кнопка "Мы выехали"
    elif query.data.startswith("checkout_"):
        parts = query.data.split("_", 2)
        guest_id = int(parts[1])
        apt_name = parts[2] if len(parts) > 2 else "апартамент"

        # Уведомляем администратора — убираем дублирование "кв"
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚪 *{apt_name} — выехали*",
                parse_mode="Markdown"
            )

        # Просим гостя оставить обратную связь и реквизиты для залога
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=guest_id,
            text="Спасибо что выбрали *Alekseev Apartments!* 🙏\n\n"
                 "Пожалуйста, дайте нам обратную связь здесь в чате — "
                 "ваше мнение очень важно для нас! 😊\n\n"
                 "А также для возврата залога пришлите ваши реквизиты в формате:\n\n"
                 "_Номер телефона / Банк / ФИО получателя_\n\n"
                 "_Например: +79001234567 / Сбербанк / Иванов Иван Иванович_",
            parse_mode="Markdown"
        )
        guest_states[guest_id] = "waiting_review_and_requisites"

    # Кнопка "Продление/Новая бронь"
    elif query.data.startswith("newbooking_"):
        guest_id = int(query.data.split("_")[1])
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=guest_id,
            text="Рады слышать вас! 🎉\n\n"
                 "Укажите пожалуйста даты — с какой по какую дату вы хотите забронировать?\n\n"
                 "_Например: с 01.07 по 05.07_",
            parse_mode="Markdown"
        )
        guest_states[guest_id] = "waiting_new_booking_dates"


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
        "Для того чтобы найти ваше бронирование в системе, пришлите пожалуйста "
        "вашу *фамилию и имя* на которое оформлена бронь и *даты* заезда/выезда:\n\n"
        "_Например: Иванов Иван с 01.01 по 02.01_",
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
    if not is_admin(update.effective_user):
        return

    full_text = " ".join(context.args) if context.args else ""
    if not full_text:
        await update.message.reply_text(
            "Пример:\n/balance Елена с 01.02 по 05.02 8000"
        )
        return

    # ИИ парсит свободный текст
    parse_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": f"""Из текста извлеки данные бронирования.
Текст: "{full_text}"

Ответь строго в таком формате (каждое на новой строке):
ИМЯ: (имя гостя)
ЗАЕЗД: (дата заезда)
ВЫЕЗД: (дата выезда)
СУММА: (только число)

Если дата или имя не указаны — оставь поле пустым. Сумма — последнее число в тексте."""
        }]
    )

    try:
        raw = parse_response.content[0].text.strip()
        name = ""
        date_from = ""
        date_to = ""
        amount = 0

        for line in raw.split("\n"):
            line = line.strip()
            if line.upper().startswith("ИМЯ:"):
                name = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ЗАЕЗД:"):
                date_from = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ВЫЕЗД:"):
                date_to = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("СУММА:"):
                try:
                    amount = int(line.split(":", 1)[-1].strip().replace(" ", ""))
                except:
                    pass

        if not name or not amount:
            await update.message.reply_text(
                "Не удалось распознать имя или сумму.\n"
                "Пример: /balance Елена с 01.02 по 05.02 8000"
            )
            return

        total = amount + DEPOSIT
        key = f"{name.lower()}_{date_from}"
        guest_balances[key] = {
            "name": name,
            "name_lower": name.lower(),
            "date_from": date_from,
            "date_to": date_to,
            "amount": amount
        }

        # Ищем гостя в активных сессиях
        guest_id = None
        for saved_name, uid in guest_name_to_id.items():
            saved_words = set(saved_name.lower().split())
            new_words = set(name.lower().split())
            if saved_words & new_words:
                guest_id = uid
                break

        if guest_id:
            guest_states[guest_id] = "waiting_docs"
            await context.bot.send_message(
                chat_id=guest_id,
                text=f"✅ Бронь найдена!\n\n"
                     f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф. "
                     f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                     f"Для оформления нам потребуется:\n\n"
                     f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                     f"💰 Чек об оплате по реквизитам:\n\n"
                     f"• Остаток по бронированию: *{amount} руб.*\n"
                     f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня)_\n"
                     f"• *Итого: {total} руб.*\n\n"
                     f"{PAYMENT_INFO}\n\n"
                     f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total} руб. → отправлено гостю")
        else:
            await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total} руб. → сохранено")

    except Exception as e:
        await update.message.reply_text("Не удалось распознать. Пример:\n/balance Елена с 01.02 по 05.02 8000")


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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документов — PDF и других файлов"""
    user_id = update.effective_user.id
    user = update.effective_user
    state = guest_states.get(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"

    if state not in ["waiting_docs", "waiting_payment"]:
        await update.message.reply_text("Спасибо за документ! Если есть вопросы — задавайте 😊")
        return

    doc = update.message.document
    if not doc:
        return

    # Принимаем PDF и изображения в виде документов
    allowed_types = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
    if doc.mime_type not in allowed_types:
        await update.message.reply_text(
            "Пожалуйста пришлите документ в формате PDF, JPG или PNG 📄"
        )
        return

    await update.message.reply_text("🔍 Проверяю документ, подождите...")

    # Скачиваем файл
    doc_file = await context.bot.get_file(doc.file_id)
    file_bytes = await doc_file.download_as_bytearray()

    # Конвертируем PDF в изображение для анализа через ИИ
    if doc.mime_type == "application/pdf":
        try:
            import pypdf
            from PIL import Image
            import io

            # Читаем PDF
            reader = pypdf.PdfReader(io.BytesIO(bytes(file_bytes)))
            page = reader.pages[0]

            # Рендерим страницу в изображение
            from pypdf.generic import RectangleObject
            import struct

            # Извлекаем изображения из PDF если есть
            images_in_pdf = []
            if "/Resources" in page and "/XObject" in page["/Resources"]:
                xobjects = page["/Resources"]["/XObject"].get_object()
                for obj in xobjects:
                    xobj = xobjects[obj].get_object()
                    if xobj.get("/Subtype") == "/Image":
                        data = xobj.get_data()
                        img = Image.open(io.BytesIO(data))
                        images_in_pdf.append(img)

            if images_in_pdf:
                img_byte_arr = io.BytesIO()
                images_in_pdf[0].convert("RGB").save(img_byte_arr, format='JPEG', quality=85)
                file_bytes = bytearray(img_byte_arr.getvalue())
            else:
                raise Exception("Нет изображений в PDF")

        except Exception:
            # Fallback — пересылаем администратору с кнопками
            if ADMIN_CHAT_ID:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"📄 *PDF от гостя:* {username} (ID: {user_id})\nПроверьте вручную 👇",
                    parse_mode="Markdown"
                )
                await context.bot.forward_message(
                    chat_id=ADMIN_CHAT_ID,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📄 Это паспорт", callback_data=f"pdf_passport_{user_id}"),
                    InlineKeyboardButton("🧾 Это чек", callback_data=f"pdf_check_{user_id}")
                ]])
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text="Что прислал гость?",
                    reply_markup=keyboard
                )
            await update.message.reply_text(
                "✅ Документ получен! Проверяем... ⏱\n\nЕсли есть вопросы — готов помочь! 😊"
            )
            return

    # Передаём в тот же обработчик что и фото
    # Создаём временный объект с байтами для анализа
    update.message._doc_bytes = bytes(file_bytes)

    # ИИ определяет что пришло
    detect_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")}},
                {"type": "text", "text": "Что на изображении? Ответь только одним словом: ПАСПОРТ, ЧЕК или ДРУГОЕ"}
            ]
        }]
    )
    doc_type = detect_response.content[0].text.strip().upper()

    has_passport = context.user_data.get("has_passport", False)
    has_payment = context.user_data.get("has_payment", False)

    if "ПАСПОРТ" in doc_type:
        if has_passport:
            await update.message.reply_text("📄 Паспорт уже получен. Пришлите чек об оплате 🧾")
            return
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📄 *Паспорт (PDF) от гостя:* {username} (ID: {user_id})\n✅ ИИ подтвердил",
                parse_mode="Markdown"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        context.user_data["has_passport"] = True
        if has_payment:
            await _finalize_docs(update, context, user_id, username)
        else:
            await update.message.reply_text("✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾")
            guest_states[user_id] = "waiting_docs"

    elif "ЧЕК" in doc_type:
        if has_payment:
            await update.message.reply_text("🧾 Чек уже получен. Пришлите фото паспорта 📄")
            return

        guest_name = context.user_data.get("guest_name", "").lower()
        date_from = context.user_data.get("date_from", "")
        expected_amount = None
        for key, data in guest_balances.items():
            name_match = data["name_lower"] in guest_name or guest_name in data["name_lower"]
            date_match = not date_from or data["date_from"] in date_from or date_from in data["date_from"]
            if name_match and date_match:
                expected_amount = data["amount"] + DEPOSIT
                break

        is_valid, reason = await analyze_photo_with_ai(bytes(file_bytes), "payment", expected_amount)

        if not is_valid:
            if reason == "not_a_check":
                await update.message.reply_text(
                    "❌ Это не похоже на чек об оплате.\n\n"
                    "Пришлите *чек или подтверждение оплаты* 🧾",
                    parse_mode="Markdown"
                )
            elif reason.startswith("wrong_amount"):
                found = reason.split(":")[-1].strip()
                if ADMIN_CHAT_ID:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"⚠️ Чек (PDF) от гостя {username}\n\n"
                             f"Сумма в чеке: {found} руб.\n"
                             f"Запрошенная сумма: {expected_amount} руб.\n\n"
                             f"❌ СУММЫ НЕ СОВПАДАЮТ\n\nЧек 👇"
                    )
                    await context.bot.forward_message(
                        chat_id=ADMIN_CHAT_ID,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
                        InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
                    ]])
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Подтвердите получение оплаты:", reply_markup=keyboard)
                guest_states[user_id] = "waiting_admin_confirmation"
                await update.message.reply_text(
                    "⚠️ Сумма в чеке не совпадает. Чек передан администратору. ⏱"
                )
            return

        if ADMIN_CHAT_ID:
            expected_str = f"{expected_amount} руб." if expected_amount else "не определена"
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🧾 Чек (PDF) от гостя {username}\n\n"
                     f"Запрошенная сумма: {expected_str}\n✅ Сумма совпадает\n\nЧек 👇"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

        context.user_data["has_payment"] = True
        if has_passport:
            await _finalize_docs(update, context, user_id, username)
        else:
            await update.message.reply_text("✅ Чек принят!\n\nТеперь пришлите фото паспорта 📄")
            guest_states[user_id] = "waiting_docs"

    else:
        await update.message.reply_text(
            "❌ Не удалось определить документ.\n\n"
            "Пожалуйста пришлите:\n"
            "📄 Паспорт (фото или PDF)\n"
            "🧾 Чек об оплате (фото или PDF)"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    state = guest_states.get(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"

    # Принимаем фото только если гость в процессе верификации
    if state not in ["waiting_passport", "waiting_payment", "waiting_docs"]:
        await update.message.reply_text("Спасибо за фото! Если есть вопросы — задавайте 😊")
        return

    await update.message.reply_text("🔍 Проверяю документ, подождите...")
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    photo_bytes = await photo_file.download_as_bytearray()

    # ИИ определяет что пришло — паспорт или чек
    detect_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(photo_bytes).decode("utf-8")}},
                {"type": "text", "text": "Что на фото? Ответь только одним словом: ПАСПОРТ, ЧЕК или ДРУГОЕ"}
            ]
        }]
    )
    doc_type = detect_response.content[0].text.strip().upper()

    # Определяем что уже получено от гостя
    has_passport = context.user_data.get("has_passport", False)
    has_payment = context.user_data.get("has_payment", False)

    if "ПАСПОРТ" in doc_type:
        if has_passport:
            await update.message.reply_text("📄 Паспорт уже получен. Пришлите чек об оплате 🧾")
            return
        # Паспорт принят
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
        context.user_data["has_passport"] = True
        if has_payment:
            # Оба документа получены
            await _finalize_docs(update, context, user_id, username)
        else:
            await update.message.reply_text("✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾")
            guest_states[user_id] = "waiting_docs"

    elif "ЧЕК" in doc_type:
        if has_payment:
            await update.message.reply_text("🧾 Чек уже получен. Пришлите фото паспорта 📄")
            return

        # Проверяем сумму чека
        guest_name = context.user_data.get("guest_name", "").lower()
        date_from = context.user_data.get("date_from", "")
        expected_amount = None
        for key, data in guest_balances.items():
            name_match = data["name_lower"] in guest_name or guest_name in data["name_lower"]
            date_match = not date_from or data["date_from"] in date_from or date_from in data["date_from"]
            if name_match and date_match:
                expected_amount = data["amount"] + DEPOSIT
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
                found = reason.split(":")[-1].strip()
                if ADMIN_CHAT_ID:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"⚠️ Чек от гостя {username}\n\n"
                             f"Гость: {context.user_data.get('guest_name', 'не указано')}\n"
                             f"Сумма в чеке: {found} руб.\n"
                             f"Запрошенная сумма: {expected_amount} руб.\n\n"
                             f"❌ СУММЫ НЕ СОВПАДАЮТ\n\nЧек 👇"
                    )
                    await context.bot.forward_message(
                        chat_id=ADMIN_CHAT_ID,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
                        InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
                    ]])
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Подтвердите получение оплаты:", reply_markup=keyboard)
                guest_states[user_id] = "waiting_admin_confirmation"
                await update.message.reply_text(
                    "⚠️ Сумма в чеке не совпадает с запрошенной.\n\n"
                    "Чек передан администратору на проверку.\n"
                    "Свяжемся с вами в течение 10 минут. ⏱"
                )
            return

        # Чек валидный
        found_amount = reason.split(":")[-1].strip() + " руб." if ":" in reason else "не определена"
        if ADMIN_CHAT_ID:
            expected_str = f"{expected_amount} руб." if expected_amount else "не определена"
            amount_status = f"✅ Сумма совпадает: {expected_str}" if expected_amount else "⚠️ Проверьте вручную"
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🧾 Чек от гостя {username}\n\n"
                     f"Гость: {context.user_data.get('guest_name', 'не указано')}\n"
                     f"Запрошенная сумма: {expected_str}\n\n"
                     f"{amount_status}\n\nЧек 👇"
            )
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

        context.user_data["has_payment"] = True
        if has_passport:
            await _finalize_docs(update, context, user_id, username)
        else:
            await update.message.reply_text("✅ Чек принят!\n\nТеперь пришлите фото паспорта 📄")
            guest_states[user_id] = "waiting_docs"

    else:
        await update.message.reply_text(
            "❌ Не удалось определить документ.\n\n"
            "Пожалуйста, пришлите:\n"
            "📄 Фото паспорта (лицевая сторона)\n"
            "🧾 Чек об оплате"
        )


async def _finalize_docs(update, context, user_id, username):
    """Оба документа получены — отправляем кнопки апартаментов администратору"""
    guest_states[user_id] = "waiting_admin_confirmation"
    await update.message.reply_text(
        "✅ Все документы получены!\n\n"
        "Документы переданы на проверку оплаты.\n"
        "⏱ Обычно это занимает не более 10 минут.\n\n"
        "Пока ждёте — если есть вопросы, я готов помочь! 😊"
    )
    if ADMIN_CHAT_ID:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
            InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
        ]])
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"✅ Все документы от гостя {username} получены!\nПодтвердите получение оплаты:",
            reply_markup=keyboard
        )

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

    # Гость — вводит ФИО и даты
    if state == "asking_name":
        raw = user_text.strip()
        context.user_data["raw_booking"] = raw

        # Используем ИИ чтобы распознать ФИО и даты из произвольного текста
        parse_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""Из текста извлеки ФИО и даты бронирования.
Текст: "{raw}"

Ответь строго в формате JSON без лишнего текста:
{{"name": "ФИО", "date_from": "дата заезда", "date_to": "дата выезда"}}

Если даты не указаны — верни пустую строку для дат.
Даты записывай как есть из текста."""
            }]
        )

        try:
            import json as json_module
            parsed = json_module.loads(parse_response.content[0].text.strip())
            name = parsed.get("name", "").strip()
            date_from = parsed.get("date_from", "").strip()
            date_to = parsed.get("date_to", "").strip()
        except:
            name = raw
            date_from = ""
            date_to = ""

        if not name:
            await update.message.reply_text(
                "Не удалось распознать ФИО. Пожалуйста, напишите в формате:\n\n"
                "_Иванов Иван Иванович, с 27.06 по 30.06_",
                parse_mode="Markdown"
            )
            return

        context.user_data["guest_name"] = name
        context.user_data["date_from"] = date_from
        context.user_data["date_to"] = date_to
        guest_name_to_id[name.lower()] = user_id

        # Ищем бронь через ИИ — умное сравнение
        balance_data = None
        if guest_balances:
            # Формируем список броней для ИИ
            bookings_text = ""
            booking_keys = []
            for i, (key, data) in enumerate(guest_balances.items()):
                bookings_text += f"{i+1}. Имя: {data['name']}, заезд: {data['date_from']}, выезд: {data['date_to']}\n"
                booking_keys.append(key)

            match_response = claude.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=50,
                messages=[{
                    "role": "user",
                    "content": f"""Гость написал: "{raw}"
Из этого текста извлечено: имя="{name}", заезд="{date_from}", выезд="{date_to}"

Список броней в базе:
{bookings_text}

Найди наиболее подходящую бронь. Учитывай что:
- Имя может быть написано по-разному (только фамилия, только имя, с опечатками)
- Даты могут быть в разных форматах
- Ищи по совпадению хотя бы части имени И дат

Ответь ТОЛЬКО номером подходящей брони (1, 2, 3...) или 0 если ничего не подходит."""
                }]
            )

            try:
                match_num = int(match_response.content[0].text.strip())
                if 1 <= match_num <= len(booking_keys):
                    matched_key = booking_keys[match_num - 1]
                    balance_data = guest_balances[matched_key]
            except:
                balance_data = None

        # Уведомляем админа только если бронь не найдена — просто сообщаем без подсказок
        if not balance_data and ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🆕 Новый гость: *{name}*\n"
                     f"Заезд: {date_from or '?'} | Выезд: {date_to or '?'}\n"
                     f"Бронь не найдена в базе.",
                parse_mode="Markdown"
            )

        if balance_data:
            amount = balance_data["amount"]
            total = amount + DEPOSIT
            guest_states[user_id] = "waiting_docs"
            await update.message.reply_text(
                f"✅ Бронь найдена!\n\n"
                f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф. "
                f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                f"Для оформления нам потребуется:\n\n"
                f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                f"💰 Чек об оплате по реквизитам:\n\n"
                f"• Остаток по бронированию: *{amount} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня)_\n"
                f"• *Итого: {total} руб.*\n\n"
                f"{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                parse_mode="Markdown"
            )
        else:
            guest_states[user_id] = "waiting_balance"
            await update.message.reply_text(
                f"🔍 Бронирование на имя *{name}*"
                f"{f' с {date_from} по {date_to}' if date_from else ''}"
                f" не найдено в нашей системе.\n\n"
                f"Пожалуйста, проверьте правильность ФИО и дат.\n"
                f"Или подождите — уточним у администратора и свяжемся в течение 10 минут. ⏱",
                parse_mode="Markdown"
            )
        return

    if state == "waiting_balance":
        # Гость написал снова — пробуем найти бронь ещё раз с новыми данными
        raw = user_text.strip()

        parse_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Из текста извлеки имя и даты бронирования.
Текст: "{raw}"

Ответь строго в формате (каждое на новой строке):
ИМЯ: (имя гостя)
ЗАЕЗД: (дата заезда)
ВЫЕЗД: (дата выезда)

Если дата не указана — оставь поле пустым."""
            }]
        )

        name = ""
        date_from = ""
        date_to = ""
        for line in parse_response.content[0].text.strip().split("\n"):
            if line.upper().startswith("ИМЯ:"):
                name = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ЗАЕЗД:"):
                date_from = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ВЫЕЗД:"):
                date_to = line.split(":", 1)[-1].strip()

        if not name:
            await update.message.reply_text(
                "Пожалуйста, напишите имя и даты бронирования.\n\n"
                "_Например: Иванов Иван с 01.07 по 05.07_",
                parse_mode="Markdown"
            )
            return

        # Ищем бронь через ИИ
        balance_data = None
        if guest_balances:
            bookings_text = ""
            booking_keys = []
            for i, (key, data) in enumerate(guest_balances.items()):
                bookings_text += f"{i+1}. Имя: {data['name']}, заезд: {data['date_from']}, выезд: {data['date_to']}\n"
                booking_keys.append(key)

            match_response = claude.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=10,
                messages=[{
                    "role": "user",
                    "content": f"""Гость: имя="{name}", заезд="{date_from}", выезд="{date_to}"
Брони: {bookings_text}
Найди совпадение по имени и датам. Ответь только номером (1,2...) или 0."""
                }]
            )
            try:
                match_num = int(match_response.content[0].text.strip())
                if 1 <= match_num <= len(booking_keys):
                    balance_data = guest_balances[booking_keys[match_num - 1]]
            except:
                balance_data = None

        if balance_data:
            amount = balance_data["amount"]
            total = amount + DEPOSIT
            guest_states[user_id] = "waiting_docs"
            context.user_data["guest_name"] = name
            context.user_data["date_from"] = date_from
            context.user_data["date_to"] = date_to
            guest_name_to_id[name.lower()] = user_id
            await update.message.reply_text(
                f"✅ Бронь найдена!\n\n"
                f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф. "
                f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                f"Для оформления нам потребуется:\n\n"
                f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                f"💰 Чек об оплате по реквизитам:\n\n"
                f"• Остаток по бронированию: *{amount} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.* _(возвращается в день выезда до конца дня)_\n"
                f"• *Итого: {total} руб.*\n\n"
                f"{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🔍 Бронирование на имя *{name}*"
                f"{f' с {date_from} по {date_to}' if date_from else ''}"
                f" не найдено.\n\n"
                f"Пожалуйста, проверьте правильность написания имени и дат и напишите снова.\n\n"
                f"_Например: Иванов Иван с 01.07 по 05.07_",
                parse_mode="Markdown"
            )
        return

    if state == "waiting_docs":
        await update.message.reply_text(
            "Пожалуйста пришлите:\n"
            "📄 Фото паспорта (лицевая сторона)\n"
            "🧾 Чек об оплате\n\n"
            "Можно в любом порядке!"
        )
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
            "Для того чтобы найти ваше бронирование в системе, пришлите пожалуйста "
            "вашу *фамилию и имя* на которое оформлена бронь и *даты* заезда/выезда:\n\n"
            "_Например: Иванов Иван с 01.01 по 02.01_",
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

    if state == "waiting_new_booking_dates":
        # Пересылаем даты администратору
        if ADMIN_CHAT_ID:
            username = f"@{user.username}" if user.username else f"{user.first_name}"
            guest_name = context.user_data.get("guest_name", username)
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🔄 *Запрос на продление/новую бронь*\n\n"
                     f"Гость: {username}\n"
                     f"ФИО: {guest_name}\n"
                     f"Даты: {user_text}",
                parse_mode="Markdown"
            )
        await update.message.reply_text(
            "Спасибо! 😊\n\n"
            "В ближайшее время с вами свяжется оператор по вопросу бронирования. ⏱"
        )
        guest_states[user_id] = "verified"
        return

    if state == "waiting_review_and_requisites":
        # ИИ определяет — реквизиты или обратная связь
        check_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"Это реквизиты для перевода денег (номер телефона/банк/ФИО)? Текст: \"{user_text}\"\nОтветь только: РЕКВИЗИТЫ или ОТЗЫВ"
            }]
        )
        is_requisites = "РЕКВИЗИТЫ" in check_response.content[0].text.upper()
        apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "неизвестный апартамент")
        username = f"@{user.username}" if user.username else f"{user.first_name}"

        if is_requisites:
            if ADMIN_CHAT_ID:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"💳 *Реквизиты для возврата залога*\n\n"
                         f"Апартамент: *{apt_name}*\n"
                         f"Гость: {username}\n\n"
                         f"Реквизиты:\n{user_text}",
                    parse_mode="Markdown"
                )
            await update.message.reply_text(
                "Благодарим вас за реквизиты! 🙏\n\n"
                "Залог вернём вам сегодня до 00:00. ✅\n\n"
                "Будем рады видеть вас снова в *Alekseev Apartments!* 🏠",
                parse_mode="Markdown"
            )
            guest_states[user_id] = "checkout_done"
        else:
            if ADMIN_CHAT_ID:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"⭐ *Обратная связь от гостя*\n\n"
                         f"Апартамент: *{apt_name}*\n"
                         f"Гость: {username}\n\n"
                         f"{user_text}",
                    parse_mode="Markdown"
                )
            await update.message.reply_text(
                "Спасибо за обратную связь! 🙏\n\n"
                "Для возврата залога пришлите пожалуйста реквизиты:\n\n"
                "_Номер телефона / Банк / ФИО получателя_\n\n"
                "_Например: +79001234567 / Сбербанк / Иванов Иван Иванович_",
                parse_mode="Markdown"
            )
        return

    if state == "checkout_done":
        await update.message.reply_text(
            "Спасибо что были с нами! 😊\n"
            "Если захотите забронировать снова — напишите нам!"
        )
        return


        days = user_text.strip()
        guest_states[user_id] = "verified"
        await notify_admin_extension(context, user, days)
        await update.message.reply_text(
            f"Отлично! Запрос на продление на *{days} сут.* отправлен администратору.\n\n"
            f"Ответим в течение 10 минут — если продление возможно, пришлём реквизиты для оплаты. ⏱",
            parse_mode="Markdown"
        )
        return

    # Верифицированный гость — отвечаем через Claude
    # Включаем информацию об апартаменте гостя в контекст
    apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "")
    apt_context = ""
    if apt_name:
        memory = load_memory()
        apt_info = memory.get("objects", {}).get(apt_name, "")
        if apt_info:
            import re
            clean_info = re.sub(r'<[^>]+>', '', apt_info)
            apt_context = f"\n\n=== АПАРТАМЕНТ ГОСТЯ: {apt_name} ===\n{clean_info}"

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": user_text})
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT.format(knowledge=get_all_knowledge() + apt_context),
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
    elif "[ПАРКОВКА_КРАСНАЯ]" in reply:
        parking_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🅿️ Купить парк/место", callback_data=f"parking_{user_id}")]
        ])
        await update.message.reply_text(
            "🚗 *Варианты парковки для Красная 176:*\n\n"
            "• **Индивидуальное место на -1 этаже** — *1000 руб/сутки*\n"
            "• **Бесплатно** — ул. Путевая\n"
            "• **Платная с ул. Красная 176** — 60 руб/час по будням с 8:00 до 20:00",
            parse_mode="Markdown",
            reply_markup=parking_keyboard
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
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен!")
app.run_polling()
