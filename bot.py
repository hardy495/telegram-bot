import os
import json
import asyncio
import base64
import anthropic
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
ADMIN_USERNAME = "@Hardy495"
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

def escape_md(text):
    """Экранирует спецсимволы Markdown"""
    if not text:
        return ""
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text

MEMORY_FILE = "memory.json"
ADMIN_FILE = "admin.json"
BALANCES_FILE = "balances.json"

def load_balances_from_file():
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_balances_to_file(balances):
    with open(BALANCES_FILE, "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=2)

# Загружаем балансы из файла при старте
guest_balances = load_balances_from_file()
guest_states = {}
conversation_history = {}
pending_guest = {}
notification_to_guest = {}
time_request_to_guest = {}
extension_request_to_guest = {}
guest_extension_days = {}

# Связь имя гостя -> user_id для автоматической отправки реквизитов
guest_name_to_id = {}

# Единое хранилище документов гостей: user_id -> {has_passport, has_payment}
guest_docs = {}

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

def get_admin_chat_id():
    """Возвращает ADMIN_CHAT_ID из переменной окружения или памяти"""
    return ADMIN_CHAT_ID or os.getenv("ADMIN_CHAT_ID")


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
Если гость спрашивает где взять дополнительное бельё или полотенца — они находятся в шкафу. Если в шкафу нет — можно взять с сушилки.

=== ПАРКОВКА И ВЪЕЗД НА ТЕРРИТОРИЮ ===
Для апартаментов на ул. Октябрьской:
• Запарковаться можно в любом свободном месте во дворе
• Ворота автоматически не открываются при подъезде к ним
• Самые активные ворота — №1 (со стороны ул. Октябрьская между двумя Пятёрочками) — через них быстрее всего заехать и выехать на трафике вместе с другими машинами
• Также можно въехать/выехать через ворота №2, №3 и №4 — но через первые значительно быстрее
• Альтернатива: парковка со стороны Галереи вдоль дороги или со стороны ул. Кирова — там платная городская парковка с 8:00 до 20:00 по будням

Для апартамента на ул. Красная 176:
• Платная парковка на -1 этаже здания — индивидуальное место стоит 1000 руб/сутки
• Бесплатная парковка на ул. Путевая
• Платная парковка непосредственно с ул. Красная 176 при наличии свободных мест — 60 руб/час по будням с 8:00 до 20:00

Если гость спрашивает про парковку на Красной 176 и интересуется индивидуальным местом — верни ровно: [ПАРКОВКА_КРАСНАЯ]
Если гость явно хочет купить/приобрести парковочное место (пишет "хочу купить", "хочу приобрести", "как оплатить", "да хочу") — верни ровно: [КУПИТЬ_ПАРКОВКУ]

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

⚠️ Если не открывается домофон, не срабатывает пароль или рычажок минисейфа не опускается — проверьте что вы у правильного подъезда и в правильном доме/корпусе. На Октябрьской несколько корпусов — легко перепутать. По 159 кв — корпус 3, подъезд 3. По 243 кв — корпус без номера, подъезд 4. По 49 кв — подъезд 1. По 7 кв — корпус 3, подъезд 1.

=== ПРАВИЛА ОБЩЕНИЯ ===
- Отвечай только на русском языке
- Будь вежлив и дружелюбен
- Помогай с любыми вопросами кроме инструкций по заселению
- Не придумывай информацию которой нет в базе

Если гость выражает недовольство, жалобу или претензию (грязно, сломано, не работает, плохо, не нравится, холодно, шумно и т.п.) — обязательно: 1) кратко и искренне извинись от имени команды, 2) если можешь помочь — скажи как, если нет — не задавай уточняющих вопросов, 3) скажи что информация передаётся оператору. Ответ должен быть коротким и чётким. В конце ответа добавь ровно: [ЖАЛОБА]
Если гость спрашивает про ранний заезд — верни ровно: [РАННИЙ_ЗАЕЗД]
Если гость спрашивает про поздний выезд — верни ровно: [ПОЗДНИЙ_ВЫЕЗД]
Если гость хочет продлить проживание — верни ровно: [ПРОДЛЕНИЕ]
Если гость сообщает что УЖЕ выехал или съехал прямо сейчас — верни ровно: [ВЫЕХАЛ]
Если не можешь ответить на вопрос — верни ровно: [НУЖЕН_ОПЕРАТОР]
"""

def is_admin(user):
    return user.username and f"@{user.username}".lower() == ADMIN_USERNAME.lower()

async def notify_admin_question(context, question, user):
    admin_id = get_admin_chat_id()
    if not admin_id:
        print(f"[TG] notify_admin_question: admin_id не найден!", flush=True)
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    try:
        msg = await context.bot.send_message(
            chat_id=admin_id,
            text=f"❓ *Вопрос/сообщение от гостя {username}:*\n\n{question}\n\n"
                 f"_Нажмите Reply и напишите ответ — он уйдёт гостю автоматически_",
            parse_mode="Markdown"
        )
        notification_to_guest[msg.message_id] = user.id
    except Exception as e:
        print(f"[TG] Ошибка notify_admin_question: {e}", flush=True)

async def notify_admin_extension(context, user, days):
    if not get_admin_chat_id():
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    guest_name = f"ФИО: {context.user_data.get('guest_name', 'не указано')}" if hasattr(context, 'user_data') else ""
    msg = await context.bot.send_message(
        chat_id=get_admin_chat_id(),
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
    if not get_admin_chat_id():
        return
    username = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    type_text = "ранний заезд" if request_type == "early" else "поздний выезд"
    msg = await context.bot.send_message(
        chat_id=get_admin_chat_id(),
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

    # Кнопка "Получил" для MAX гостя
    if query.data.startswith("max_received_"):
        max_guest_id = int(query.data.split("_")[2])
        un = f"MAX гость {max_guest_id}"

        memory = load_memory()
        objects = memory.get("objects", {})
        if not objects:
            await query.edit_message_text("⚠️ База апартаментов пуста!")
            return

        buttons = []
        for i, name in enumerate(objects.keys()):
            buttons.append([InlineKeyboardButton(f"🏠 {name}", callback_data=f"maxapt_{max_guest_id}_{i}")])
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(
            f"✅ Оплата получена!\n\nВыберите апартамент для отправки гостю в MAX:",
            reply_markup=keyboard
        )
        return

    # Кнопка "Не получил" для MAX гостя
    if query.data.startswith("max_not_received_"):
        max_guest_id = int(query.data.split("_")[3])
        max_states[max_guest_id] = "waiting_docs"
        max_outbox[max_guest_id] = (
            f"⚠️ Оплата не поступила.\n\n"
            f"Пожалуйста, проверьте правильность перевода и пришлите чек повторно.\n\n"
            f"Реквизиты:\n{PAYMENT_INFO}\n\n"
            f"При переводе ничего не пишите в комментарии к платежу."
        )
        await query.edit_message_text("❌ Гость уведомлён — оплата не поступила.")
        return

    # Кнопка выбора апартамента для MAX гостя
    if query.data.startswith("maxapt_"):
        parts = query.data.split("_")
        max_guest_id = int(parts[1])
        apt_index = int(parts[2])

        memory = load_memory()
        objects = memory.get("objects", {})
        apt_names = list(objects.keys())

        if apt_index >= len(apt_names):
            await query.edit_message_text("❌ Апартамент не найден.")
            return

        apt_name = apt_names[apt_index]
        apt_info = objects[apt_name]

        import re
        clean_info = re.sub(r'<[^>]+>', '', apt_info)

        max_apt[max_guest_id] = apt_name
        max_states[max_guest_id] = "verified"

        # Отправляем через очередь с кнопками
        # Кнопки через Telegram API (inline keyboard для MAX не поддерживается напрямую)
        # Сохраняем сообщение и кнопки через max_outbox
        max_outbox[max_guest_id] = {
            "text": f"✅ Ваша оплата подтверждена!\n\n{clean_info}\n\nЕсли возникнут вопросы — я всегда готов помочь! 😊",
            "with_checkout_buttons": True,
            "apt_name": apt_name
        }

        await query.edit_message_text(f"✅ Информация по {apt_name} отправлена гостю в MAX!")
        return

    # Кнопка "Мы выехали" для MAX гостя
    if query.data.startswith("max_checkout_"):
        max_guest_id = int(query.data.split("_")[2])
        apt_name = max_apt.get(max_guest_id, "апартамент")

        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)

        # Уведомляем администратора
        admin_id = get_admin_chat_id()
        if admin_id:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🚪 *{apt_name} — выехали* (MAX)",
                parse_mode="Markdown"
            )

        max_states[max_guest_id] = "waiting_requisites"
        max_outbox[max_guest_id] = {
            "text": "Спасибо что выбрали Alekseev Apartments! 🙏\n\n"
                    "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                    "Номер телефона / Банк / ФИО получателя\n\n"
                    "Например: +79001234567 / Сбербанк / Иванов Иван Иванович"
        }
        return

    # Кнопка "Продление/Новая бронь" для MAX гостя
    if query.data.startswith("max_extend_"):
        max_guest_id = int(query.data.split("_")[2])
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        max_states[max_guest_id] = "waiting_new_booking_dates_max"
        max_outbox[max_guest_id] = {
            "text": "Рады слышать вас! 🎉\n\n"
                    "Укажите пожалуйста даты — с какой по какую дату вы хотите забронировать?\n\n"
                    "Например: с 01.07 по 05.07"
        }
        return

    elif query.data.startswith("parking_"):
        guest_id = int(query.data.split("_")[1])
        guest_username = f"@{query.from_user.username}" if query.from_user.username else f"{query.from_user.first_name}"

        admin_id = get_admin_chat_id()
        if admin_id:
            msg = await context.bot.send_message(
                chat_id=admin_id,
                text=f"🅿️ *Запрос на покупку парковочного места*\n\n"
                     f"Гость: {guest_username}\n"
                     f"Апартамент: Красная 176\n\n"
                     f"Гость хочет приобрести индивидуальное место (1000 руб/сутки).\n\n"
                     f"Ответьте Reply с реквизитами для оплаты — гость получит автоматически!",
                parse_mode="Markdown"
            )
            # Сохраняем message_id для reply
            notification_to_guest[msg.message_id] = guest_id
        await query.answer("Запрос отправлен администратору!")
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=guest_id,
            text="✅ Запрос на парковочное место отправлен!\n\n"
                 "Администратор свяжется с вами в течение 10 минут. ⏱"
        )
        return


    # Кнопка "Это паспорт" для PDF
    elif query.data.startswith("pdf_passport_"):
        guest_id = int(query.data.split("_")[2])
        guest_docs.setdefault(guest_id, {})["has_passport"] = True
        guest_states[guest_id] = "waiting_docs"
        await context.bot.send_message(
            chat_id=guest_id,
            text="✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾"
        )
        await query.edit_message_text("✅ Паспорт гостя подтверждён!")

    # Кнопка "Это чек" для PDF
    elif query.data.startswith("pdf_check_"):
        guest_id = int(query.data.split("_")[2])
        has_passport = guest_docs.get(guest_id, {}).get("has_passport", False)
        guest_docs.setdefault(guest_id, {})["has_payment"] = True

        if has_passport:
            guest_states[guest_id] = "waiting_admin_confirmation"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Получил", callback_data=f"received_{guest_id}"),
                InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{guest_id}")
            ]])
            await context.bot.send_message(chat_id=get_admin_chat_id(), text="Подтвердите получение оплаты:", reply_markup=keyboard)
            await context.bot.send_message(
                chat_id=guest_id,
                text="✅ Все документы получены!\n\nДокументы переданы на проверку оплаты. ⏱\nОбычно это занимает до 15 минут.\n\nКак только документы будут проверены — вам сюда автоматически придёт вся информация по заселению! 🏠\n\nЕсли есть вопросы — я готов помочь! 😊"
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

        # Проверяем есть ли паспорт от гостя через единый guest_docs
        has_passport = guest_docs.get(guest_id, {}).get("has_passport", False)

        if not has_passport:
            await context.bot.send_message(
                chat_id=guest_id,
                text="✅ Оплата подтверждена!\n\n"
                     "Для завершения оформления пришлите пожалуйста фото паспорта (лицевая сторона) 📄"
            )
            guest_states[guest_id] = "waiting_docs"
            # Сохраняем что оплата подтверждена
            guest_docs.setdefault(guest_id, {})["has_payment"] = True
            await query.edit_message_text("✅ Оплата подтверждена! Ожидаем паспорт от гостя.")
            return

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

        # Подсказка со стрелками на кнопки
        await context.bot.send_message(
            chat_id=guest_id,
            text="━━━━━━━━━━━━━━━━━━━━\n\n"
                 "Как только вы съедете с апартаментов — нажмите кнопку 👇\n"
                 "👉 *🚪 Мы выехали*\n\n"
                 "Если хотите продлить проживание или сделать новую бронь — нажмите 👇\n"
                 "👉 *🔄 Продление/Новая бронь*",
            parse_mode="Markdown"
        )

        # Сохраняем апартамент гостя для контекста
        guest_states[guest_id] = "verified"
        context.bot_data.setdefault("guest_apt", {})[guest_id] = apt_name
        conversation_history[guest_id] = []
        await query.edit_message_text(f"✅ Информация по апартаменту *{apt_name}* отправлена гостю!", parse_mode="Markdown")
        del pending_guest[admin_chat_id]

    # Кнопка "Мы выехали"
    elif query.data.startswith("checkout_"):
        parts = query.data.split("_", 2)
        guest_id = int(parts[1])
        apt_name = parts[2] if len(parts) > 2 else "апартамент"

        # Уведомляем администратора
        if get_admin_chat_id():
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
                text=f"🚪 *{apt_name} — выехали*",
                parse_mode="Markdown"
            )

        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=guest_id,
            text="Спасибо что выбрали *Alekseev Apartments!* 🙏\n\n"
                 "Нам очень важно ваше мнение — пожалуйста дайте обратную связь здесь в чате!\n\n"
                 "Как вам понравилось проживание? 😊",
            parse_mode="Markdown"
        )
        guest_states[guest_id] = "waiting_feedback"

    # Кнопка "Продление/Новая бронь"
    elif query.data.startswith("newbooking_"):
        guest_id = int(query.data.split("_")[1])
        await query.answer()  # просто закрываем спиннер, не убираем кнопки
        await context.bot.send_message(
            chat_id=guest_id,
            text="Рады слышать вас! 🎉\n\n"
                 "Для продления или новой брони укажите пожалуйста:\n\n"
                 "📅 *Даты* — с какой по какую дату?\n"
                 "📞 *Номер телефона* для связи\n\n"
                 "_Например: с 01.07 по 05.07, тел: +79001234567_",
            parse_mode="Markdown"
        )
        guest_states[guest_id] = "waiting_new_booking_dates"


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

async def newbook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /newbook — начать новое бронирование"""
    user_id = update.effective_user.id
    if is_admin(update.effective_user):
        return
    guest_states[user_id] = "asking_name"
    conversation_history[user_id] = []
    guest_docs[user_id] = {}
    await update.message.reply_text(
        "Здравствуйте! 👋 Добро пожаловать в *Alekseev Apartments!*\n\n"
        "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
        "Меня зовут *Алекс* — я ИИ-ассистент Alekseev Apartments.\n"
        "Я помогу вам с заселением:\n\n"
        "✅ Приму оплату и проверю документы\n"
        "🔑 Заселю вас дистанционно через минисейф\n"
        "💬 Отвечу на все вопросы по размещению\n\n"
        "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
        "_Например: Иванов Иван с 01.01 по 02.01_",
        parse_mode="Markdown"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(update.effective_user):
        await update.message.reply_text(
            "Привет! Вы вошли как администратор 👋\n\n"
            "Команды:\n"
            "/admin — активировать уведомления\n"
            "/b ФИО с ДД.ММ по ДД.ММ СУММА — добавить бронь\n"
            "/setcode КВ КОД — сменить пароль минисейфа\n"
            "/add название | инфо — добавить/обновить апартамент\n"
            "/remember текст — запомнить заметку\n\n"
            "💡 На вопросы гостей отвечайте через *Reply*.",
            parse_mode="Markdown"
        )
        return
    guest_states[user_id] = "asking_name"
    conversation_history[user_id] = []
    guest_docs[user_id] = {}  # Сбрасываем документы при новой брони
    await update.message.reply_text(
        "Здравствуйте! 👋 Добро пожаловать в *Alekseev Apartments!*\n\n"
        "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
        "Меня зовут *Алекс* — я ИИ-ассистент Alekseev Apartments.\n"
        "Я помогу вам с заселением:\n\n"
        "✅ Приму оплату и проверю документы\n"
        "🔑 Заселю вас дистанционно через минисейф\n"
        "💬 Отвечу на все вопросы по размещению\n\n"
        "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
        "_Например: Иванов Иван с 01.01 по 02.01_",
        parse_mode="Markdown"
    )

async def set_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = str(update.effective_chat.id)
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
        await update.message.reply_text("Пример: /b Иванов Иван с 01.07 по 05.07 3500")
        return
    from datetime import date as date_cls
    today_str = date_cls.today().strftime("%d.%m.%Y")
    parse_response = claude.messages.create(
        model="claude-sonnet-4-6", max_tokens=150,
        messages=[{"role": "user", "content":
            f"Сегодня {today_str}. Из текста извлеки данные бронирования.\n"
            f"Текст: \"{full_text}\"\n\n"
            f"ИМЯ: (имя)\nЗАЕЗД: (дата ДД.ММ)\nВЫЕЗД: (дата ДД.ММ)\nСУММА: (только число)\n\n"
            f"Если написано сегодня={today_str}. Сумма — последнее число."}]
    )
    raw = parse_response.content[0].text.strip()
    name, date_from, date_to, amount = "", "", "", None
    for line in raw.split("\n"):
        if line.upper().startswith("ИМЯ:"): name = line.split(":", 1)[-1].strip()
        elif line.upper().startswith("ЗАЕЗД:"): date_from = line.split(":", 1)[-1].strip()
        elif line.upper().startswith("ВЫЕЗД:"): date_to = line.split(":", 1)[-1].strip()
        elif line.upper().startswith("СУММА:"):
            try: amount = int(line.split(":", 1)[-1].strip().replace(" ", ""))
            except: pass
    if not name or amount is None:
        await update.message.reply_text("Не удалось распознать.\nПример: /b Иванов Иван с 01.07 по 05.07 3500")
        return
    total = DEPOSIT if amount == 0 else amount + DEPOSIT
    key = f"{name.lower()}_{date_from}"
    guest_balances[key] = {"name": name, "name_lower": name.lower(),
                           "date_from": date_from, "date_to": date_to, "amount": amount}
    save_balances_to_file(guest_balances)

    notified = False

    # Ищем гостя в TELEGRAM который ждёт бронь
    for saved_name, uid in list(guest_name_to_id.items()):
        saved_words = set(saved_name.lower().split())
        new_words = set(name.lower().split())
        if saved_words & new_words and guest_states.get(uid) == "waiting_balance":
            total_msg = DEPOSIT if amount == 0 else amount + DEPOSIT
            if amount == 0:
                tg_msg = (f"✅ Бронь найдена!\n\n"
                          f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                          f"Все инструкции, пароли и адрес придут после подтверждения документов.\n\n"
                          f"Вы уже полностью оплатили бронирование! 🎉\n\n"
                          f"Для оформления нам потребуется:\n\n"
                          f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                          f"💰 Залог: *{DEPOSIT} руб.*\n\n"
                          f"{PAYMENT_INFO}\n\n"
                          f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.")
            else:
                tg_msg = (f"✅ Бронь найдена!\n\n"
                          f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                          f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                          f"Для оформления нам потребуется:\n\n"
                          f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                          f"💰 Чек об оплате по реквизитам:\n\n"
                          f"• Остаток по бронированию: *{amount} руб.*\n"
                          f"• Залог: *{DEPOSIT} руб.*\n"
                          f"• *Итого: {total_msg} руб.*\n\n"
                          f"{PAYMENT_INFO}\n\n"
                          f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.")
            guest_states[uid] = "waiting_docs"
            guest_docs[uid] = {}
            admin_id = get_admin_chat_id()
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 Новый гость (Telegram): ID {uid}\nИмя: {name}\n✅ Бронь найдена | {total_msg} руб."
                )
            try:
                await context.bot.send_message(chat_id=uid, text=tg_msg, parse_mode="Markdown")
                notified = True
                await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total_msg} руб. → отправлено гостю в Telegram!")
                return
            except Exception as e:
                print(f"Ошибка отправки TG гостю: {e}")

    # Ищем гостя в MAX который ждёт эту бронь
    for max_uid, winfo in list(max_waiting.items()):
        wname = winfo.get("name", "").lower()
        if set(name.lower().split()) & set(wname.split()):
            if amount == 0:
                msg = (f"✅ Бронь найдена!\n\n"
                       f"Отличные новости — вы уже полностью оплатили бронирование! 🎉\n\n"
                       f"🔑 Заселение у нас дистанционное — вы заселяетесь самостоятельно через минисейф.\n"
                       f"Все инструкции, пароли и адрес придут после подтверждения документов.\n\n"
                       f"Для оформления нам потребуется:\n\n"
                       f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                       f"💰 Залог: {DEPOSIT} руб.\n\n"
                       f"{PAYMENT_INFO}\n\n"
                       f"⚠️ При переводе ничего не пишите в комментарии к платежу.")
            else:
                msg = (f"✅ Бронь найдена!\n\n"
                       f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                       f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                       f"💰 Чек об оплате по реквизитам:\n"
                       f"• Остаток по бронированию: {amount} руб.\n"
                       f"• Залог: {DEPOSIT} руб.\n"
                       f"• Итого: {total} руб.\n\n"
                       f"{PAYMENT_INFO}\n\n"
                       f"⚠️ При переводе ничего не пишите в комментарии к платежу.")
            max_states[max_uid] = "waiting_docs"
            max_docs[max_uid] = {}
            max_outbox[max_uid] = msg
            del max_waiting[max_uid]
            await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total} руб. → гость уведомлён в MAX!")
            return

    await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total} руб. → сохранено")


async def set_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /setcode КВ НОВЫЙ_КОД — изменить пароль минисейфа"""
    if not is_admin(update.effective_user):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: `/setcode КВ КОД`\n\n"
            "Примеры:\n"
            "`/setcode 182 5050`\n"
            "`/setcode 159 1234`\n"
            "`/setcode 243 0000`\n\n"
            "Доступные квартиры: 182, 159, 243, 86, 2, 49, 7",
            parse_mode="Markdown"
        )
        return

    apt_num = context.args[0].strip()
    new_code = context.args[1].strip()

    if not new_code.isdigit() or len(new_code) != 4:
        await update.message.reply_text("❌ Код должен состоять из 4 цифр.\nПример: `/setcode 182 5050`", parse_mode="Markdown")
        return

    # Ищем апартамент
    memory = load_memory()
    objects = memory.get("objects", {})
    apt_key = f"{apt_num} кв"

    if apt_key not in objects:
        available = ", ".join(objects.keys())
        await update.message.reply_text(f"❌ Апартамент не найден.\n\nДоступные: {available}")
        return

    # Заменяем старый 4-значный код на новый
    import re
    old_info = objects[apt_key]

    # Ищем текущий код минисейфа в тексте
    codes = re.findall(r'\b\d{4}\b', old_info)
    # Исключаем WiFi пароли и другие числа — берём тот что идёт после "Минисейф" или "код"
    minisafe_match = re.search(r'((?:Минисейф|код)[^0-9]*?)(\d{4})', old_info, re.IGNORECASE)

    if minisafe_match:
        old_code = minisafe_match.group(2)
        new_info = old_info.replace(f"<b>{old_code}</b>", f"<b>{new_code}</b>", 1)
        if new_info == old_info:
            new_info = old_info.replace(old_code, new_code, 1)
        memory["objects"][apt_key] = new_info
        save_memory(memory)
        await update.message.reply_text(
            f"✅ Пароль минисейфа *{apt_key}* обновлён!\n\n"
            f"Старый: `{old_code}`\n"
            f"Новый: `{new_code}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Не удалось найти код минисейфа в {apt_key}. Проверьте базу через /list")



async def maxapt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить информацию по апартаменту гостю в MAX: /maxapt user_id название"""
    if not is_admin(update.effective_user):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /maxapt USER_ID название апартамента")
        return
    try:
        guest_id = int(context.args[0])
        apt_name = " ".join(context.args[1:])
        memory = load_memory()
        objects = memory.get("objects", {})
        apt_names = list(objects.keys())

        # Ищем апартамент по номеру или названию
        apt_info = None
        matched_name = apt_name
        for name, info in objects.items():
            if apt_name.lower() in name.lower():
                apt_info = info
                matched_name = name
                break

        if not apt_info:
            # Пробуем как индекс
            try:
                idx = int(apt_name) - 1
                matched_name = apt_names[idx]
                apt_info = objects[matched_name]
            except:
                await update.message.reply_text(f"Апартамент не найден. Список: {', '.join(apt_names)}")
                return

        import re
        clean_info = re.sub(r'<[^>]+>', '', apt_info)

        # Сохраняем апартамент гостя в MAX
        max_apt[guest_id] = matched_name
        max_states[guest_id] = "verified"

        # Отправляем гостю через MAX API
        import asyncio, httpx
        MAX_TOKEN = os.getenv("MAX_TOKEN")
        if MAX_TOKEN:
            async def send():
                async with httpx.AsyncClient() as c:
                    await c.post(
                        "https://botapi.max.ru/messages",
                        headers={"Authorization": f"Bearer {MAX_TOKEN}"},
                        json={"recipient": {"chat_id": guest_id}, "type": "text", "text": f"✅ Ваша оплата подтверждена!\n\n{clean_info}\n\nЕсли возникнут вопросы — я всегда готов помочь! 😊"}
                    )
            asyncio.create_task(send())

        await update.message.reply_text(f"✅ Информация по {matched_name} отправлена гостю в MAX!")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


    if not is_admin(update.effective_user):
        return

    full_text = " ".join(context.args) if context.args else ""
    if not full_text:
        await update.message.reply_text(
            "Пример:\n/b Елена с 01.02 по 05.02 8000"
        )
        return

    # ИИ парсит свободный текст
    from datetime import date as date_cls
    today_str = date_cls.today().strftime("%d.%m.%Y")
    parse_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": f"""Сегодня {today_str}. Из текста извлеки данные бронирования.
Текст: "{full_text}"

Ответь строго в таком формате (каждое на новой строке):
ИМЯ: (имя гостя)
ЗАЕЗД: (дата в формате ДД.ММ или ДД.ММ.ГГГГ)
ВЫЕЗД: (дата в формате ДД.ММ или ДД.ММ.ГГГГ)
СУММА: (только число)

Если написано 'сегодня' — используй {today_str}. Сумма — последнее число в тексте."""
        }]
    )

    try:
        raw = parse_response.content[0].text.strip()
        name = ""
        date_from = ""
        date_to = ""
        amount = None  # None = не найдено, 0 = специально указан ноль

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

        if not name or amount is None:
            await update.message.reply_text(
                "Не удалось распознать имя или сумму.\n"
                "Пример: /b Елена с 01.02 по 05.02 8000"
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
        save_balances_to_file(guest_balances)

        # Ищем гостя в MAX который ждёт эту бронь
        for max_uid, guest_info in list(max_waiting_guests.items()):
            guest_name_lower = guest_info.get("name", "").lower()
            name_words = set(name.lower().split())
            guest_words = set(guest_name_lower.split())
            if name_words & guest_words:
                # Нашли — отправляем гостю в MAX
                total_msg = DEPOSIT if amount == 0 else amount + DEPOSIT
                if amount == 0:
                    msg = (f"✅ Бронь найдена!\n\nВы уже всё оплатили! 🎉\n\n"
                           f"Заселение дистанционное — через минисейф.\n\n"
                           f"Для оформления:\n📄 Фото паспорта\n"
                           f"💰 Залог: {DEPOSIT} руб.\n\n{PAYMENT_INFO}\n\n"
                           f"При переводе ничего не пишите в комментарии.")
                else:
                    msg = (f"✅ Бронь найдена!\n\nЗаселение дистанционное — через минисейф.\n\n"
                           f"Для оформления:\n📄 Фото паспорта\n"
                           f"💰 Остаток: {amount} руб.\n💰 Залог: {DEPOSIT} руб.\n"
                           f"💰 Итого: {total_msg} руб.\n\n{PAYMENT_INFO}\n\n"
                           f"При переводе ничего не пишите в комментарии.")
                max_states[max_uid] = "waiting_docs"
                max_docs[max_uid] = {}
                max_outbox[max_uid] = msg
                del max_waiting_guests[max_uid]
                break

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

            if amount == 0:
                # Гость всё оплатил — нужен только залог и паспорт
                await context.bot.send_message(
                    chat_id=guest_id,
                    text=f"✅ Бронь найдена!\n\n"
                         f"Отличные новости — вы уже полностью оплатили бронирование! 🎉\n\n"
                         f"Все инструкции, пароли и адрес придут после подтверждения.\n\n"
                         f"Для оформления нам потребуется:\n\n"
                         f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                         f"💰 Залог: *{DEPOSIT} руб.*\n\n"
                         f"{PAYMENT_INFO}\n\n"
                         f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    chat_id=guest_id,
                    text=f"✅ Бронь найдена!\n\n"
                         f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                         f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                         f"💰 Чек об оплате по реквизитам:\n\n"
                         f"• Остаток по бронированию: *{amount} руб.*\n"
                         f"• Залог: *{DEPOSIT} руб.*\n"
                         f"• *Итого: {total} руб.*\n\n"
                         f"{PAYMENT_INFO}\n\n"
                         f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                    parse_mode="Markdown"
                )
            await update.message.reply_text(
                f"✅ {name} | {date_from}–{date_to} | "
                f"{'только залог' if amount == 0 else str(total) + ' руб.'} → отправлено гостю"
            )
        else:
            await update.message.reply_text(f"✅ {name} | {date_from}–{date_to} | {total} руб. → сохранено")

    except Exception as e:
        await update.message.reply_text("Не удалось распознать. Пример:\n/b Елена с 01.02 по 05.02 8000")


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

    # Обработка скриншота отзыва
    if state == "waiting_review_screenshot":
        apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "неизвестный апартамент")
        admin_id = get_admin_chat_id()
        if admin_id:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📸 *Скриншот отзыва от гостя*\n\n"
                     f"Апартамент: *{apt_name}*\n"
                     f"Гость: {username}\n\n"
                     f"Отправьте промокод Reply на это сообщение — гость получит его автоматически!",
                parse_mode="Markdown"
            )
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            notification_to_guest[update.message.message_id] = user_id
        guest_states[user_id] = "waiting_promo"
        await update.message.reply_text(
            "✅ Скриншот получен! Спасибо! 🙏\n\n"
            "Мы проверим отзыв и пришлём вам персональный промокод в ближайшее время! 🎁"
        )
        return

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
        # Отправляем PDF напрямую в Claude — он умеет читать PDF
        pdf_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")

        detect_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data
                        }
                    },
                    {"type": "text", "text": "Что в этом документе? Ответь только одним словом: ПАСПОРТ, ЧЕК или ДРУГОЕ"}
                ]
            }]
        )
        doc_type = detect_response.content[0].text.strip().upper()

        has_passport = guest_docs.get(user_id, {}).get("has_passport", False)
        has_payment = guest_docs.get(user_id, {}).get("has_payment", False)

        if "ПАСПОРТ" in doc_type:
            if has_passport:
                await update.message.reply_text("📄 Паспорт уже получен. Пришлите чек об оплате 🧾")
                return
            if get_admin_chat_id():
                await context.bot.send_message(
                    chat_id=get_admin_chat_id(),
                    text=f"📄 Паспорт (PDF) от гостя: {username} (ID: {user_id})\n✅ ИИ подтвердил"
                )
                await context.bot.forward_message(
                    chat_id=get_admin_chat_id(),
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            guest_docs.setdefault(user_id, {})["has_passport"] = True
            if has_payment:
                await _finalize_docs(update, context, user_id, username)
            else:
                await update.message.reply_text("✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾")
                guest_states[user_id] = "waiting_docs"

        elif "ЧЕК" in doc_type:
            if has_payment:
                await update.message.reply_text("🧾 Чек уже получен. Пришлите фото паспорта 📄")
                return

            # Проверяем сумму через Claude
            guest_name = context.user_data.get("guest_name", "").lower()
            date_from = context.user_data.get("date_from", "")
            expected_amount = None
            for key, data in guest_balances.items():
                name_match = data["name_lower"] in guest_name or guest_name in data["name_lower"]
                date_match = not date_from or data["date_from"] in date_from or date_from in data["date_from"]
                if name_match and date_match:
                    expected_amount = DEPOSIT if data["amount"] == 0 else data["amount"] + DEPOSIT
                    break

            if expected_amount:
                amount_check = claude.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=50,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_data
                                }
                            },
                            {"type": "text", "text": f"Найди сумму перевода в этом чеке. Она равна {expected_amount} рублям? Ответь: СОВПАДАЕТ, НЕ СОВПАДАЕТ (и укажи найденную сумму) или НЕИЗВЕСТНО"}
                        ]
                    }]
                )
                amount_result = amount_check.content[0].text.strip()

                if "НЕ СОВПАДАЕТ" in amount_result.upper():
                    if get_admin_chat_id():
                        await context.bot.send_message(
                            chat_id=get_admin_chat_id(),
                            text=f"⚠️ Чек (PDF) от гостя {username}\n\n"
                                 f"Гость: {context.user_data.get('guest_name', '?')}\n"
                                 f"Запрошенная сумма: {expected_amount} руб.\n"
                                 f"Результат: {amount_result}\n\n❌ СУММЫ НЕ СОВПАДАЮТ\n\nЧек 👇"
                        )
                        await context.bot.forward_message(
                            chat_id=get_admin_chat_id(),
                            from_chat_id=update.effective_chat.id,
                            message_id=update.message.message_id
                        )
                        keyboard = InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
                            InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
                        ]])
                        await context.bot.send_message(chat_id=get_admin_chat_id(), text="Подтвердите:", reply_markup=keyboard)
                    guest_states[user_id] = "waiting_admin_confirmation"
                    await update.message.reply_text(
                        "⚠️ Сумма в чеке не совпадает.\n\nЧек передан администратору на проверку. ⏱"
                    )
                    return

            # Чек принят
            if get_admin_chat_id():
                await context.bot.send_message(
                    chat_id=get_admin_chat_id(),
                    text=f"🧾 Чек (PDF) от гостя {username}\n"
                         f"Запрошенная сумма: {expected_amount or '?'} руб.\n✅ Сумма совпадает\n\nЧек 👇"
                )
                await context.bot.forward_message(
                    chat_id=get_admin_chat_id(),
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            guest_docs.setdefault(user_id, {})["has_payment"] = True
            if has_passport:
                await _finalize_docs(update, context, user_id, username)
            else:
                await update.message.reply_text("✅ Чек принят!\n\nТеперь пришлите фото паспорта 📄")
                guest_states[user_id] = "waiting_docs"

        else:
            await update.message.reply_text(
                "❌ Не удалось определить документ.\n\n"
                "Пришлите:\n📄 Паспорт (фото или PDF)\n🧾 Чек (фото или PDF)"
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

    has_passport = guest_docs.get(user_id, {}).get("has_passport", False)
    has_payment = guest_docs.get(user_id, {}).get("has_payment", False)

    if "ПАСПОРТ" in doc_type:
        if has_passport:
            await update.message.reply_text("📄 Паспорт уже получен. Пришлите чек об оплате 🧾")
            return
        if get_admin_chat_id():
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
                text=f"📄 Паспорт (PDF) от гостя: {username} (ID: {user_id})\n✅ ИИ подтвердил"
            )
            await context.bot.forward_message(
                chat_id=get_admin_chat_id(),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_docs.setdefault(user_id, {})["has_passport"] = True
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
                expected_amount = DEPOSIT if data["amount"] == 0 else data["amount"] + DEPOSIT
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
                if get_admin_chat_id():
                    await context.bot.send_message(
                        chat_id=get_admin_chat_id(),
                        text=f"⚠️ Чек (PDF) от гостя {username}\n\n"
                             f"Сумма в чеке: {found} руб.\n"
                             f"Запрошенная сумма: {expected_amount} руб.\n\n"
                             f"❌ СУММЫ НЕ СОВПАДАЮТ\n\nЧек 👇"
                    )
                    await context.bot.forward_message(
                        chat_id=get_admin_chat_id(),
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
                        InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
                    ]])
                    await context.bot.send_message(chat_id=get_admin_chat_id(), text="Подтвердите получение оплаты:", reply_markup=keyboard)
                guest_states[user_id] = "waiting_admin_confirmation"
                await update.message.reply_text(
                    "⚠️ Сумма в чеке не совпадает. Чек передан администратору. ⏱"
                )
            return

        if get_admin_chat_id():
            expected_str = f"{expected_amount} руб." if expected_amount else "не определена"
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
                text=f"🧾 Чек (PDF) от гостя {username}\n\n"
                     f"Запрошенная сумма: {expected_str}\n✅ Сумма совпадает\n\nЧек 👇"
            )
            await context.bot.forward_message(
                chat_id=get_admin_chat_id(),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

        guest_docs.setdefault(user_id, {})["has_payment"] = True
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

    # Обработка скриншота отзыва
    if state == "waiting_review_screenshot":
        apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "неизвестный апартамент")
        admin_id = get_admin_chat_id()
        if admin_id:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📸 *Скриншот отзыва от гостя*\n\n"
                     f"Апартамент: *{apt_name}*\n"
                     f"Гость: {username}\n\n"
                     f"Отправьте промокод Reply на это сообщение — гость получит его автоматически!",
                parse_mode="Markdown"
            )
            fwd = await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            notification_to_guest[fwd.message_id] = user_id
        guest_states[user_id] = "waiting_promo"
        await update.message.reply_text(
            "✅ Скриншот получен! Спасибо! 🙏\n\n"
            "Мы проверим отзыв и пришлём вам персональный промокод в ближайшее время! 🎁"
        )
        return

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
    has_passport = guest_docs.get(user_id, {}).get("has_passport", False)
    has_payment = guest_docs.get(user_id, {}).get("has_payment", False)

    if "ПАСПОРТ" in doc_type:
        if has_passport:
            await update.message.reply_text("📄 Паспорт уже получен. Пришлите чек об оплате 🧾")
            return
        # Паспорт принят
        if get_admin_chat_id():
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
                text=f"📄 Паспорт от гостя: {username} (ID: {user_id})\n✅ ИИ подтвердил"
            )
            await context.bot.forward_message(
                chat_id=get_admin_chat_id(),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        guest_docs.setdefault(user_id, {})["has_passport"] = True
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
                expected_amount = DEPOSIT if data["amount"] == 0 else data["amount"] + DEPOSIT
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
                if get_admin_chat_id():
                    await context.bot.send_message(
                        chat_id=get_admin_chat_id(),
                        text=f"⚠️ Чек от гостя {username}\n\n"
                             f"Гость: {context.user_data.get('guest_name', 'не указано')}\n"
                             f"Сумма в чеке: {found} руб.\n"
                             f"Запрошенная сумма: {expected_amount} руб.\n\n"
                             f"❌ СУММЫ НЕ СОВПАДАЮТ\n\nЧек 👇"
                    )
                    await context.bot.forward_message(
                        chat_id=get_admin_chat_id(),
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
                        InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
                    ]])
                    await context.bot.send_message(chat_id=get_admin_chat_id(), text="Подтвердите получение оплаты:", reply_markup=keyboard)
                guest_states[user_id] = "waiting_admin_confirmation"
                await update.message.reply_text(
                    "⚠️ Сумма в чеке не совпадает с запрошенной.\n\n"
                    "Чек передан администратору на проверку.\n"
                    "Свяжемся с вами в течение 10 минут. ⏱"
                )
            return

        # Чек валидный
        found_amount = reason.split(":")[-1].strip() + " руб." if ":" in reason else "не определена"
        if get_admin_chat_id():
            expected_str = f"{expected_amount} руб." if expected_amount else "не определена"
            amount_status = f"✅ Сумма совпадает: {expected_str}" if expected_amount else "⚠️ Проверьте вручную"
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
                text=f"🧾 Чек от гостя {username}\n\n"
                     f"Гость: {context.user_data.get('guest_name', 'не указано')}\n"
                     f"Запрошенная сумма: {expected_str}\n\n"
                     f"{amount_status}\n\nЧек 👇"
            )
            await context.bot.forward_message(
                chat_id=get_admin_chat_id(),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

        guest_docs.setdefault(user_id, {})["has_payment"] = True
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
        "Документы переданы на проверку оплаты. ⏱\n"
        "Обычно это занимает до 15 минут.\n\n"
        "Как только документы будут проверены — вам сюда автоматически придёт вся информация по заселению! 🏠\n\n"
        "Если есть вопросы — я готов помочь! 😊"
    )
    admin_id = get_admin_chat_id()
    if admin_id:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Получил", callback_data=f"received_{user_id}"),
            InlineKeyboardButton("❌ Не получил", callback_data=f"not_received_{user_id}")
        ]])
        await context.bot.send_message(
            chat_id=admin_id,
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

            # Проверяем reply для MAX гостя (промокод или реквизиты для парковки)
            if reply_to.message_id in max_promo_map:
                max_uid = max_promo_map[reply_to.message_id]
                max_state = max_states.get(max_uid)

                if max_state == "waiting_promo_max":
                    # Промокод
                    max_outbox[max_uid] = {
                        "text": f"🎁 Ваш персональный промокод:\n\n{user_text}\n\n"
                               f"Чтобы забронировать со скидкой — позвоните:\n"
                               f"📞 +7 918 148 00 45\n\n"
                               f"Назовите оператору ваш промокод!\n\n"
                               f"Будем рады видеть вас снова в Alekseev Apartments! 🏠✨"
                    }
                    max_states[max_uid] = "checkout_done_max"
                else:
                    # Ответ оператора (реквизиты, подтверждение продления и т.д.)
                    max_outbox[max_uid] = {"text": f"💬 Ответ оператора:\n\n{user_text}"}

                del max_promo_map[reply_to.message_id]
                await update.message.reply_text("✅ Ответ отправлен гостю в MAX!")
                return

            if reply_to.message_id in notification_to_guest:
                guest_id = notification_to_guest[reply_to.message_id]
                guest_state = guest_states.get(guest_id)

                if guest_state == "waiting_promo":
                    # Это промокод — отправляем специальное сообщение
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text=f"🎁 *Ваш персональный промокод:*\n\n"
                             f"`{user_text}`\n\n"
                             f"Чтобы забронировать со скидкой — позвоните на горячую линию:\n"
                             f"📞 *+7 918 148 00 45*\n\n"
                             f"Назовите оператору ваш промокод и получите скидку!",
                        parse_mode="Markdown"
                    )
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text="Будем рады видеть вас снова в *Alekseev Apartments!* 🏠✨\n\n"
                             "Спасибо что выбрали нас! 🙏",
                        parse_mode="Markdown"
                    )
                    guest_states[guest_id] = "checkout_done"
                else:
                    # Обычный ответ оператора
                    await context.bot.send_message(
                        chat_id=guest_id,
                        text=f"💬 *Ответ оператора:*\n\n{user_text}",
                        parse_mode="Markdown"
                    )
                await update.message.reply_text("✅ Ответ отправлен гостю!")
                return

        await update.message.reply_text(
            "Команды администратора:\n"
            "/admin — активировать уведомления\n"
            "/b ФИО с ДД.ММ по ДД.ММ СУММА — добавить бронь\n"
            "/setcode КВ КОД — сменить пароль минисейфа\n"
            "/add название | инфо — добавить/обновить апартамент\n"
            "/remember текст — запомнить заметку"
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

        # Уведомляем админа только если бронь не найдена
        if not balance_data:
            admin_id = load_admin_chat_id() or ADMIN_CHAT_ID
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 Новый гость: {name}\n"
                         f"Заезд: {date_from or '?'} | Выезд: {date_to or '?'}\n"
                         f"Бронь не найдена в базе.",
                    parse_mode="Markdown"
                )

        if balance_data:
            amount = balance_data["amount"]
            total = amount + DEPOSIT
            guest_states[user_id] = "waiting_docs"
            guest_name_to_id[name.lower()] = user_id

            # Уведомляем администратора что бронь найдена
            username = f"@{user.username}" if user.username else f"{user.first_name}"
            admin_id = get_admin_chat_id()
            print(f"[TG] Бронь найдена, уведомляем admin_id={admin_id}", flush=True)
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 Новый гость (Telegram): {username}\n"
                         f"Имя: {name} | Заезд: {date_from} | Выезд: {date_to}\n"
                         f"✅ Бронь найдена | Сумма: {total} руб."
                )

            await update.message.reply_text(
                f"✅ Бронь найдена!\n\n"
                f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                f"💰 Чек об оплате по реквизитам:\n\n"
                f"• Остаток по бронированию: *{amount} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.*\n"
                f"• *Итого: {total} руб.*\n\n"
                f"{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                parse_mode="Markdown"
            )
        else:
            guest_states[user_id] = "waiting_balance"
            # Уведомляем администратора
            admin_id = get_admin_chat_id()
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 Новый гость ищет бронь!\n\n"
                         f"Имя: {name}\n"
                         f"Заезд: {date_from or '?'} | Выезд: {date_to or '?'}\n\n"
                         f"Бронь не найдена — добавьте:\n"
                         f"`/b {name} с {date_from} по {date_to} СУММА`",
                    parse_mode="Markdown"
                )
            await update.message.reply_text(
                f"🔍 Бронирование на имя {name}"
                f"{f' с {date_from} по {date_to}' if date_from else ''}"
                f" не найдено в нашей системе.\n\n"
                f"Не переживайте — мы уже направили уведомление администратору! ✅\n\n"
                f"Он подгрузит вашу бронь в систему в течение *15 минут*, "
                f"после чего вам автоматически придёт вся информация. ⏱",
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

            # Уведомляем администратора
            username = f"@{user.username}" if user.username else f"{user.first_name}"
            admin_id = get_admin_chat_id()
            print(f"[TG] Уведомление администратору: admin_id={admin_id}", flush=True)
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 Новый гость (Telegram): {username}\n"
                         f"Имя: {name} | Заезд: {date_from} | Выезд: {date_to}\n"
                         f"✅ Бронь найдена | Сумма: {total} руб."
                )
            else:
                print(f"[TG] admin_id не найден! ADMIN_CHAT_ID={os.getenv('ADMIN_CHAT_ID')}", flush=True)

            await update.message.reply_text(
                f"✅ Бронь найдена!\n\n"
                f"🔑 *Заселение у нас дистанционное* — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                f"💰 Чек об оплате по реквизитам:\n\n"
                f"• Остаток по бронированию: *{amount} руб.*\n"
                f"• Залог: *{DEPOSIT} руб.*\n"
                f"• *Итого: {total} руб.*\n\n"
                f"{PAYMENT_INFO}\n\n"
                f"⚠️ При переводе *ничего не пишите* в комментарии к платежу.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🔍 Бронирование на имя {name}"
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
            "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
            "Меня зовут *Алекс* — я ИИ-ассистент Alekseev Apartments.\n"
            "Я помогу вам с заселением:\n\n"
            "✅ Приму оплату и проверю документы\n"
            "🔑 Заселю вас дистанционно через минисейф\n"
            "💬 Отвечу на все вопросы по размещению\n\n"
            "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
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
        if get_admin_chat_id():
            username = f"@{user.username}" if user.username else f"{user.first_name}"
            guest_name = context.user_data.get("guest_name", username)
            await context.bot.send_message(
                chat_id=get_admin_chat_id(),
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

    if state == "waiting_requisites":
        # Пробуем получить апартамент из разных источников
        apt_name = (context.bot_data.get("guest_apt", {}).get(user_id) or
                    context.bot_data.get("guest_apt", {}).get(str(user_id)) or
                    "неизвестный апартамент")
        username = f"@{user.username}" if user.username else f"{user.first_name}"
        print(f"[TG] waiting_requisites: user={user_id}, apt={apt_name}, text={user_text[:30]}", flush=True)

        # ИИ определяет — это реквизиты или нет
        check = claude.messages.create(
            model="claude-sonnet-4-6", max_tokens=10,
            messages=[{"role": "user", "content":
                f"Это реквизиты для перевода денег (содержит номер телефона, банк или ФИО)? "
                f"Текст: \"{user_text}\"\nОтветь только: РЕКВИЗИТЫ или НЕТ"}]
        ).content[0].text.strip().upper()
        print(f"[TG] ИИ check requisites: {check}", flush=True)

        if "РЕКВИЗИТЫ" in check:
            admin_id = get_admin_chat_id()
            if admin_id:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"💳 Реквизиты для возврата залога\n\n"
                         f"Апартамент: {apt_name}\n"
                         f"Гость: {username}\n\n"
                         f"Реквизиты:\n{user_text}"
                )
            await update.message.reply_text(
                "Благодарим вас за реквизиты! ✅\n\n"
                "Залог вернём сегодня до 00:00.\n\n"
                "Будем рады если вы оставите отзыв на площадке где бронировали "
                "(Авито, Островок, Яндекс Путешествия и т.д.).\n\n"
                "🎁 *За скриншот отзыва мы подарим вам промокод:*\n"
                "• *500 руб.* от 1 суток\n"
                "• *1000 руб.* от 2 суток\n\n"
                "Пришлите скриншот сюда! 📸",
                parse_mode="Markdown"
            )
            guest_states[user_id] = "waiting_review_screenshot"
        else:
            await update.message.reply_text(
                "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                "_Номер телефона / Банк / ФИО получателя_\n\n"
                "_Например: +79001234567 / Сбербанк / Иванов Иван Иванович_",
                parse_mode="Markdown"
            )
        return

    if state == "waiting_feedback":
        apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "неизвестный апартамент")
        username = f"@{user.username}" if user.username else f"{user.first_name}"

        # ИИ определяет тональность отзыва
        sentiment = claude.messages.create(
            model="claude-sonnet-4-6", max_tokens=10,
            messages=[{"role": "user", "content":
                f"Это отзыв гостя об отеле: \"{user_text}\"\n"
                f"Ответь только одним словом: ПОЗИТИВНЫЙ или НЕГАТИВНЫЙ"}]
        ).content[0].text.strip().upper()

        # Отправляем отзыв администратору
        admin_id = get_admin_chat_id()
        if admin_id:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"{'⭐' if 'ПОЗИТИВ' in sentiment else '⚠️'} *Отзыв от гостя*\n\n"
                     f"Апартамент: *{apt_name}*\n"
                     f"Гость: {username}\n"
                     f"Тональность: {'😊 Позитивный' if 'ПОЗИТИВ' in sentiment else '😞 Негативный'}\n\n"
                     f"{user_text}",
                parse_mode="Markdown"
            )

        if "ПОЗИТИВ" in sentiment:
            guest_states[user_id] = "waiting_requisites"
            await update.message.reply_text(
                "Спасибо за тёплые слова! 🙏 Нам очень приятно! 😊\n\n"
                "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                "_Номер телефона / Банк / ФИО получателя_\n\n"
                "_Например: +79001234567 / Сбербанк / Иванов Иван Иванович_",
                parse_mode="Markdown"
            )
        else:
            guest_states[user_id] = "waiting_requisites"
            await update.message.reply_text(
                "Нам очень жаль что что-то пошло не так. 😔\n\n"
                "Мы обязательно свяжемся с вами чтобы разобраться в ситуации!\n\n"
                "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                "_Номер телефона / Банк / ФИО получателя_\n\n"
                "_Например: +79001234567 / Сбербанк / Иванов Иван Иванович_",
                parse_mode="Markdown"
            )
        return

    if state == "waiting_review_screenshot":
        # Гость написал текст вместо скриншота
        username = f"@{user.username}" if user.username else f"{user.first_name}"
        await update.message.reply_text(
            "Пожалуйста пришлите *скриншот* вашего отзыва 📸\n\n"
            "Как только получим — пришлём ваш персональный промокод!",
            parse_mode="Markdown"
        )
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
            if get_admin_chat_id():
                await context.bot.send_message(
                    chat_id=get_admin_chat_id(),
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
            if get_admin_chat_id():
                await context.bot.send_message(
                    chat_id=get_admin_chat_id(),
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
            "Рады слышать вас! 😊\n\n"
            "Для новой брони позвоните на горячую линию:\n"
            "📞 *+7 918 148 00 45*\n\n"
            "Дождитесь ответа оператора — он поможет с бронированием!",
            parse_mode="Markdown"
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
    elif "[ВЫЕХАЛ]" in reply:
        apt_name = context.bot_data.get("guest_apt", {}).get(user_id, "апартамент")
        admin_id = get_admin_chat_id()
        if admin_id:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🚪 *{apt_name} — выехали*",
                parse_mode="Markdown"
            )
        guest_states[user_id] = "waiting_feedback"
        await update.message.reply_text(
            "Спасибо что выбрали *Alekseev Apartments!* 🙏\n\n"
            "Нам очень важно ваше мнение — пожалуйста дайте обратную связь здесь в чате!\n\n"
            "Как вам понравилось проживание? 😊",
            parse_mode="Markdown"
        )
    elif "[ПРОДЛЕНИЕ]" in reply:
        # Показываем кнопку продления рядом с инструкцией и номер горячей линии
        extension_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Продление/Новая бронь", callback_data=f"newbooking_{user_id}")]
        ])
        await update.message.reply_text(
            "Для продления проживания у вас два варианта:\n\n"
            "1️⃣ Нажмите кнопку ниже и укажите даты — мы свяжемся с вами\n\n"
            "2️⃣ Позвоните на горячую линию: *+7 918 148 00 45* и дождитесь ответа оператора 📞",
            parse_mode="Markdown",
            reply_markup=extension_keyboard
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
        clean_reply = reply.replace("[НУЖЕН_ОПЕРАТОР]", "").strip()
        if clean_reply:
            await update.message.reply_text(clean_reply)
        await update.message.reply_text(
            "Также передал ваш вопрос оператору — он свяжется с вами в ближайшее время! 😊"
        )
        conversation_history[user_id].append({"role": "assistant", "content": clean_reply or reply})
    elif "[ЖАЛОБА]" in reply:
        # Уведомляем администратора
        await notify_admin_question(context, f"⚠️ ЖАЛОБА/ПРЕТЕНЗИЯ:\n{user_text}", user)
        clean_reply = reply.replace("[ЖАЛОБА]", "").strip()
        # Добавляем в конец что передали оператору
        clean_reply += "\n\nМы уже передали информацию оператору — он свяжется с вами в ближайшее время! 🙏"
        conversation_history[user_id].append({"role": "assistant", "content": clean_reply})
        await update.message.reply_text(clean_reply)
    else:
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("newbook", newbook))
app.add_handler(CommandHandler("admin", set_admin_id))
app.add_handler(CommandHandler("maxapt", maxapt_command))
app.add_handler(CommandHandler("setcode", set_code))
app.add_handler(CommandHandler("b", set_balance))
app.add_handler(CommandHandler("remember", remember))
app.add_handler(CommandHandler("add", add_object))
app.add_handler(CommandHandler("list", list_knowledge))
app.add_handler(CommandHandler("delnote", delete_note))
app.add_handler(CommandHandler("delobj", delete_object))
app.add_handler(CallbackQueryHandler(handle_apartment_selection))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Глобальные переменные для MAX бота
max_states = {}
max_hist = {}
max_docs = {}        # user_id -> {has_passport, has_payment}
max_guest_names = {} # user_id -> {name, date_from, date_to}
max_waiting = {}     # user_id ждёт пока админ внесёт бронь
max_apt = {}         # user_id -> название апартамента
max_outbox = {}      # user_id -> сообщение которое нужно отправить
max_chat_ids = {}    # user_id -> chat_id для отправки
max_promo_map = {}   # message_id в TG -> MAX user_id (для отправки промокода)
tg_admin_tasks = []  # задачи из MAX потока для выполнения в Telegram
_max_loop = None
max_bot_instance = None

async def max_send(uid, text):
    global max_bot_instance
    if not max_bot_instance:
        return
    try:
        cid = max_chat_ids.get(uid, uid)
        await max_bot_instance.send_message(chat_id=cid, text=text)
    except Exception as e:
        print(f"[MAX] send error: {e}", flush=True)

async def tg_admin(text):
    """Отправить уведомление администратору в Telegram"""
    aid = os.getenv("ADMIN_CHAT_ID")
    tok = os.getenv("TELEGRAM_TOKEN")
    if not aid or not tok:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as c:
            await c.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                         json={"chat_id": aid, "text": text})
    except Exception as e:
        print(f"[MAX] TG notify error: {e}", flush=True)

async def tg_admin_photo(caption, photo_url, media_type="image/jpeg"):
    """Скачать файл из MAX и отправить как фото/документ администратору в Telegram"""
    aid = os.getenv("ADMIN_CHAT_ID")
    tok = os.getenv("TELEGRAM_TOKEN")
    if not aid or not tok:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(photo_url)
            file_bytes = resp.content
            if media_type == "application/pdf":
                await c.post(
                    f"https://api.telegram.org/bot{tok}/sendDocument",
                    data={"chat_id": aid, "caption": caption},
                    files={"document": ("document.pdf", file_bytes, "application/pdf")}
                )
            else:
                await c.post(
                    f"https://api.telegram.org/bot{tok}/sendPhoto",
                    data={"chat_id": aid, "caption": caption},
                    files={"photo": ("photo.jpg", file_bytes, "image/jpeg")}
                )
    except Exception as e:
        print(f"[MAX] TG photo error: {e}", flush=True)
        await tg_admin(f"{caption}\n{photo_url}")

async def tg_forward_photo(photo_url, caption):
    """Переслать фото администратору в Telegram"""
    aid = os.getenv("ADMIN_CHAT_ID")
    tok = os.getenv("TELEGRAM_TOKEN")
    if not aid or not tok:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as c:
            await c.post(f"https://api.telegram.org/bot{tok}/sendPhoto",
                         json={"chat_id": aid, "photo": photo_url, "caption": caption})
    except Exception as e:
        print(f"[MAX] TG photo error: {e}", flush=True)

print("Telegram бот запущен!")

import threading

def start_max_bot():
    global _max_loop, max_bot_instance
    import asyncio
    from datetime import date as date_cls

    MAX_TOKEN = os.getenv("MAX_TOKEN")
    if not MAX_TOKEN:
        print("[MAX] MAX_TOKEN не задан — бот не запущен")
        return

    try:
        from maxapi import Bot as MaxBot, Dispatcher as MaxDisp
        from maxapi.types import MessageCreated as MC, BotStarted as BS
    except Exception as e:
        print(f"[MAX] Ошибка импорта: {e}", flush=True)
        return

    mb = MaxBot(MAX_TOKEN)
    max_bot_instance = mb
    md = MaxDisp()

    def uname(s):
        return (getattr(s, 'name', None) or getattr(s, 'username', None) or
                getattr(s, 'first_name', None) or str(getattr(s, 'user_id', '?')))

    async def find_booking(name, dfrom):
        bals = load_balances_from_file()
        if not bals:
            return None
        today = date_cls.today().strftime("%d.%m.%Y")
        btext = "\n".join(f"{i+1}. {d['name']} {d['date_from']}-{d['date_to']}"
                           for i,(k,d) in enumerate(bals.items()))
        keys = list(bals.keys())
        r = claude.messages.create(model="claude-sonnet-4-6", max_tokens=5,
            messages=[{"role":"user","content":f"Сегодня {today}. Гость: имя='{name}' заезд='{dfrom}'\nБрони:\n{btext}\nНайди совпадение. Ответь только номером или 0."}])
        try:
            n = int(r.content[0].text.strip())
            if 1 <= n <= len(keys):
                return bals[keys[n-1]]
        except:
            pass
        return None

    async def parse_name_dates(text):
        today = date_cls.today().strftime("%d.%m.%Y")
        r = claude.messages.create(model="claude-sonnet-4-6", max_tokens=150,
            messages=[{"role":"user","content":f"Сегодня {today}. Извлеки из текста имя и даты.\nТекст: \"{text}\"\n\nИМЯ: (имя)\nЗАЕЗД: (дата ДД.ММ)\nВЫЕЗД: (дата ДД.ММ)\n\nЕсли написано сегодня={today}."}])
        name=dfrom=dto=""
        for ln in r.content[0].text.strip().split("\n"):
            if ln.upper().startswith("ИМЯ:"): name=ln.split(":",1)[-1].strip()
            elif ln.upper().startswith("ЗАЕЗД:"): dfrom=ln.split(":",1)[-1].strip()
            elif ln.upper().startswith("ВЫЕЗД:"): dto=ln.split(":",1)[-1].strip()
        return name, dfrom, dto

    async def analyze_image_max(img_bytes, check_type, media_type="image/jpeg", expected_amount=None):
        import base64
        img_b64 = base64.standard_b64encode(img_bytes).decode()
        if check_type == "passport":
            prompt = "Это паспорт или документ удостоверяющий личность? Ответь ТОЛЬКО одним словом: ДА или НЕТ"
        else:
            if expected_amount:
                prompt = (f"Это банковский чек или квитанция о переводе денег?\n"
                         f"Ожидаемая сумма: {expected_amount} руб.\n"
                         f"Ответь СТРОГО одной строкой без пояснений:\n"
                         f"ЧЕК:ДА:{expected_amount} — если чек и сумма совпадает\n"
                         f"ЧЕК:ДА:СУММА — если чек но другая сумма (укажи цифры)\n"
                         f"НЕ_ЧЕК — если не чек об оплате")
            else:
                prompt = "Это банковский чек о переводе денег? Ответь ТОЛЬКО: ЧЕК:ДА или НЕ_ЧЕК"

        r = claude.messages.create(model="claude-sonnet-4-6", max_tokens=20,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type": media_type,"data":img_b64}},
                {"type":"text","text":prompt}
            ]}])
        result = r.content[0].text.strip().upper().split('\n')[0]
        print(f"[MAX] ИИ ответ ({check_type}): {result}", flush=True)

        if check_type == "passport":
            return result.startswith("ДА"), None

        if "ЧЕК:ДА" in result:
            try:
                parts = result.split(":")
                if len(parts) >= 3:
                    found = int(''.join(filter(str.isdigit, parts[2])))
                    if expected_amount and found != expected_amount:
                        return True, -found
                    return True, found
            except:
                pass
            return True, None
        return False, None

    async def finalize_max_docs(uid, un):
        max_states[uid] = "waiting_admin_confirmation"
        await max_send(uid, "✅ Все документы получены!\n\nДокументы переданы на проверку оплаты. ⏱\nОбычно это занимает до 15 минут.\n\nКак только документы будут проверены — вам сюда автоматически придёт вся информация по заселению! 🏠\n\nЕсли есть вопросы — я готов помочь! 😊")

        # Отправляем кнопки "Получил/Не получил" администратору в Telegram напрямую
        admin_id = get_admin_chat_id()
        tg_tok = os.getenv("TELEGRAM_TOKEN")
        print(f"[MAX] finalize: admin_id={admin_id}, tok={'есть' if tg_tok else 'нет'}", flush=True)
        if admin_id and tg_tok:
            keyboard = {"inline_keyboard": [[
                {"text": "✅ Получил", "callback_data": f"max_received_{uid}"},
                {"text": "❌ Не получил", "callback_data": f"max_not_received_{uid}"}
            ]]}
            try:
                import httpx as _hx
                async with _hx.AsyncClient() as c:
                    resp = await c.post(
                        f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                        json={
                            "chat_id": admin_id,
                            "text": f"✅ Все документы от гостя {un} (MAX) получены!\n\nОплата получена?",
                            "reply_markup": keyboard
                        }
                    )
                    print(f"[MAX] TG кнопки: {resp.status_code} {resp.text[:100]}", flush=True)
            except Exception as e:
                print(f"[MAX] Ошибка TG кнопок: {e}", flush=True)

    @md.bot_started()
    async def ms(event: BS):
        try:
            uid = event.user_id if hasattr(event, 'user_id') else event.message.sender.user_id
            chat_id = event.chat_id if hasattr(event, 'chat_id') else uid
            max_states[uid] = "asking_name"
            max_hist[uid] = []
            max_docs[uid] = {}
            max_chat_ids[uid] = chat_id

            welcome = (
                "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
                "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
                "Меня зовут Алекс — я ИИ-ассистент Alekseev Apartments.\n"
                "Я помогу вам с заселением:\n\n"
                "✅ Приму оплату и проверю документы\n"
                "🔑 Заселю вас дистанционно через минисейф\n"
                "💬 Отвечу на все вопросы по размещению\n\n"
                "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
                "Например: Иванов Иван с 01.01 по 02.01"
            )
            if hasattr(event, 'message') and event.message:
                await event.message.answer(welcome)
            else:
                await mb.send_message(chat_id=chat_id, text=welcome)
        except Exception as e:
            print(f"[MAX] bot_started error: {e}", flush=True)

    @md.message_created()
    async def mm(event: MC):
        uid = event.message.sender.user_id
        # Обновляем chat_id
        chat_id = getattr(event.message, 'recipient', None)
        chat_id = getattr(chat_id, 'chat_id', None) or uid
        max_chat_ids[uid] = chat_id
        un = uname(event.message.sender)
        state = max_states.get(uid)
        body = event.message.body

        # Если гость новый — показываем полное приветствие
        if state is None:
            max_states[uid] = "asking_name"
            max_hist[uid] = []
            max_docs[uid] = {}
            await event.message.answer(
                "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
                "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
                "Меня зовут Алекс — я ИИ-ассистент Alekseev Apartments.\n"
                "Я помогу вам с заселением:\n\n"
                "✅ Приму оплату и проверю документы\n"
                "🔑 Заселю вас дистанционно через минисейф\n"
                "💬 Отвечу на все вопросы по размещению\n\n"
                "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
                "Например: Иванов Иван с 01.01 по 02.01"
            )
            return

        # Обработка фото/документов
        if body and hasattr(body, 'attachments') and body.attachments:
            print(f"[MAX] Фото от {uid}, state={state}, attachments={len(body.attachments)}", flush=True)
            for att in body.attachments:
                att_url = getattr(att, 'url', None) or getattr(getattr(att, 'payload', None), 'url', None)
                print(f"[MAX] att_url={att_url}, state={state}", flush=True)

                if att_url and state == "waiting_review_screenshot_max":
                    apt_name = max_apt.get(uid, "неизвестный апартамент")
                    tg_tok = os.getenv("TELEGRAM_TOKEN")
                    admin_id = get_admin_chat_id()
                    if admin_id and tg_tok:
                        try:
                            import httpx as _hx
                            async with _hx.AsyncClient() as c:
                                r = await c.post(
                                    f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                                    json={
                                        "chat_id": admin_id,
                                        "text": f"📸 Скриншот отзыва (MAX)\n\nАпартамент: {apt_name}\nГость: {un}\n\nОтправьте промокод Reply на это сообщение — гость получит его автоматически!"
                                    }
                                )
                                msg_data = r.json()
                                if msg_data.get("ok"):
                                    msg_id = msg_data["result"]["message_id"]
                                    max_promo_map[msg_id] = uid
                            # Также отправляем само фото
                            async with _hx.AsyncClient() as c:
                                await c.post(
                                    f"https://api.telegram.org/bot{tg_tok}/sendPhoto",
                                    json={"chat_id": admin_id, "photo": att_url}
                                )
                        except Exception as e:
                            print(f"[MAX] Ошибка отправки скриншота: {e}", flush=True)
                    max_states[uid] = "waiting_promo_max"
                    await event.message.answer(
                        "✅ Скриншот получен! Спасибо! 🙏\n\n"
                        "Мы проверим отзыв и пришлём вам персональный промокод в ближайшее время! 🎁"
                    )
                    return

                if att_url and state in ["waiting_docs", "verified"]:
                    try:
                        import httpx as _hx, base64
                        async with _hx.AsyncClient() as hc:
                            img_resp = await hc.get(att_url)
                            img_bytes = img_resp.content
                        print(f"[MAX] Скачано {len(img_bytes)} байт", flush=True)

                        # Определяем формат по magic bytes
                        if img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
                            media_type = "image/webp"
                        elif img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                            media_type = "image/png"
                        elif img_bytes[:3] == b'\xff\xd8\xff':
                            media_type = "image/jpeg"
                        elif img_bytes[:4] == b'%PDF':
                            media_type = "application/pdf"
                        else:
                            media_type = "image/jpeg"
                        print(f"[MAX] media_type={media_type}", flush=True)

                        has_passport = max_docs.get(uid, {}).get("has_passport", False)
                        has_payment = max_docs.get(uid, {}).get("has_payment", False)
                        print(f"[MAX] has_passport={has_passport}, has_payment={has_payment}", flush=True)

                        await event.message.answer("🔍 Проверяю документ...")

                        # Получаем ожидаемую сумму из нескольких источников
                        guest_info = max_guest_names.get(uid, {})
                        guest_name_lower = guest_info.get("name", "").lower()
                        expected_amount = None
                        bals = load_balances_from_file()
                        # Ищем по имени гостя
                        if guest_name_lower:
                            for k, d in bals.items():
                                if d["name_lower"] in guest_name_lower or guest_name_lower in d["name_lower"]:
                                    expected_amount = DEPOSIT if d["amount"] == 0 else d["amount"] + DEPOSIT
                                    break
                        # Если не нашли по имени — берём последнюю добавленную бронь
                        if not expected_amount and bals:
                            last = list(bals.values())[-1]
                            expected_amount = DEPOSIT if last["amount"] == 0 else last["amount"] + DEPOSIT
                        print(f"[MAX] expected_amount={expected_amount}", flush=True)

                        if media_type == "application/pdf":
                            pdf_data = base64.standard_b64encode(img_bytes).decode()
                            r = claude.messages.create(model="claude-sonnet-4-6", max_tokens=30,
                                messages=[{"role":"user","content":[
                                    {"type":"document","source":{"type":"base64","media_type":"application/pdf","data":pdf_data}},
                                    {"type":"text","text":f"Что в документе? Если чек — укажи сумму. Ожидаемая: {expected_amount} руб. Ответь: ПАСПОРТ или ЧЕК:СУММА или ДРУГОЕ"}
                                ]}])
                            doc_result = r.content[0].text.strip().upper()
                            print(f"[MAX] PDF: {doc_result}", flush=True)
                            is_passport = "ПАСПОРТ" in doc_result
                            is_check = "ЧЕК" in doc_result
                            found_amount = None
                            if is_check and ":" in doc_result:
                                try:
                                    found_amount = int(''.join(filter(str.isdigit, doc_result.split("ЧЕК:")[-1])))
                                except:
                                    pass
                        else:
                            is_passport, _ = await analyze_image_max(img_bytes, "passport", media_type)
                            if not is_passport:
                                is_check, found_amount = await analyze_image_max(img_bytes, "payment", media_type, expected_amount)
                            else:
                                is_check, found_amount = False, None

                        print(f"[MAX] is_passport={is_passport}, is_check={is_check}, found_amount={found_amount}", flush=True)

                        if is_passport and not has_passport:
                            await tg_admin_photo(f"📄 Паспорт от гостя {un} (MAX) ✅", att_url, media_type)
                            max_docs.setdefault(uid, {})["has_passport"] = True
                            print(f"[MAX] Паспорт принят, has_payment={max_docs[uid].get('has_payment')}", flush=True)
                            if max_docs[uid].get("has_payment"):
                                print(f"[MAX] Вызываем finalize_max_docs", flush=True)
                                await finalize_max_docs(uid, un)
                            else:
                                await event.message.answer("✅ Паспорт принят!\n\nТеперь пришлите чек об оплате 🧾")
                        elif is_check and not has_payment:
                            # Проверяем сумму
                            if found_amount and found_amount < 0:
                                real_amount = abs(found_amount)
                                await tg_admin(
                                    f"⚠️ Чек от гостя {un} (MAX)\n"
                                    f"Сумма в чеке: {real_amount} руб.\n"
                                    f"Запрошенная: {expected_amount} руб.\n❌ СУММЫ НЕ СОВПАДАЮТ\n{att_url}"
                                )
                                await event.message.answer("⚠️ Сумма в чеке не совпадает.\n\nЧек передан администратору на проверку. ⏱")
                                max_docs.setdefault(uid, {})["has_payment"] = True
                                if max_docs[uid].get("has_passport"):
                                    await finalize_max_docs(uid, un)
                            else:
                                amount_str = f"{expected_amount} руб. ✅" if expected_amount else "не определена"
                                await tg_admin_photo(f"🧾 Чек от гостя {un} (MAX)\nСумма: {amount_str}", att_url, media_type)
                                max_docs.setdefault(uid, {})["has_payment"] = True
                                if max_docs[uid].get("has_passport"):
                                    await finalize_max_docs(uid, un)
                                else:
                                    await event.message.answer("✅ Чек принят!\n\nТеперь пришлите фото паспорта 📄")
                        elif is_passport and has_passport:
                            await event.message.answer("📄 Паспорт уже получен. Пришлите чек 🧾")
                        elif is_check and has_payment:
                            await event.message.answer("🧾 Чек уже получен. Пришлите паспорт 📄")
                        else:
                            # Документ не распознан — просим прислать нужный
                            if not has_passport and not has_payment:
                                await event.message.answer(
                                    "❌ Не удалось определить документ.\n\n"
                                    "Нам нужны:\n"
                                    "📄 Фото паспорта (лицевая сторона)\n"
                                    "🧾 Чек об оплате (скриншот из банка)\n\n"
                                    "Пожалуйста пришлите один из этих документов!"
                                )
                            elif not has_passport:
                                await event.message.answer(
                                    "❌ Это не похоже на паспорт.\n\n"
                                    "Пришлите пожалуйста фото *лицевой стороны паспорта* 📄"
                                )
                            elif not has_payment:
                                await event.message.answer(
                                    "❌ Это не похоже на чек об оплате.\n\n"
                                    "Пришлите пожалуйста скриншот перевода из банка 🧾"
                                )
                    except Exception as e:
                        import traceback
                        print(f"[MAX] Фото ошибка: {e}\n{traceback.format_exc()}", flush=True)
                        await tg_admin_photo(f"📎 Файл от гостя {un} (MAX)", att_url)
                        await event.message.answer("Документ получен! Передан на проверку. ⏱")
                elif att_url and state in ["asking_name", "waiting_balance"]:
                    await event.message.answer("Пожалуйста сначала напишите имя и даты бронирования.")
                elif att_url:
                    await event.message.answer("Спасибо за файл! Если есть вопросы — задавайте 😊")
            return

        text = body.text if body else ""
        if not text:
            return

        # Команда /newbook — новое бронирование
        if text.strip().lower() in ["/newbook", "/start"]:
            max_states[uid] = "asking_name"
            max_hist[uid] = []
            max_docs[uid] = {}
            await event.message.answer(
                "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
                "Благодарим вас за то что выбрали нас — мы рады каждому гостю! 🏠✨\n\n"
                "Меня зовут Алекс — я ИИ-ассистент Alekseev Apartments.\n"
                "Я помогу вам с заселением:\n\n"
                "✅ Приму оплату и проверю документы\n"
                "🔑 Заселю вас дистанционно через минисейф\n"
                "💬 Отвечу на все вопросы по размещению\n\n"
                "Напишите пожалуйста имя на которое оформлена бронь и даты заезда/выезда:\n\n"
                "Например: Иванов Иван с 01.01 по 02.01"
            )
            return

        # Проверяем очередь исходящих сообщений от Telegram администратора
        if uid in max_outbox:
            pending_msg = max_outbox.pop(uid)
            await event.message.answer(pending_msg)
            return

        # state=asking_name обрабатывается ниже вместе с waiting_balance

        if state in ["asking_name", "waiting_balance"]:
            name, dfrom, dto = await parse_name_dates(text)
            if not name:
                await event.message.answer("Напишите имя и даты:\nНапример: Иванов Иван с 01.01 по 02.01")
                return
            max_guest_names[uid] = {"name": name, "date_from": dfrom, "date_to": dto}
            bd = await find_booking(name, dfrom)
            if not bd:
                await tg_admin(
                    f"🆕 Новый гость (MAX): {un}\nИмя: {name} | {dfrom}-{dto}\n"
                    f"Бронь не найдена.\nДобавьте: /b {name} с {dfrom} по {dto} СУММА"
                )
                max_states[uid] = "waiting_balance"
                max_waiting[uid] = {"name": name, "date_from": dfrom, "date_to": dto}
                await event.message.answer(
                    f"🔍 Бронирование на имя {name}"
                    f"{f' с {dfrom} по {dto}' if dfrom else ''}"
                    f" не найдено в нашей системе.\n\n"
                    f"Не переживайте — мы уже направили уведомление администратору! ✅\n\n"
                    f"Он подгрузит вашу бронь в систему в течение 15 минут, "
                    f"после чего вам автоматически придёт вся информация. ⏱"
                )
                return
            amt = bd["amount"]
            total = DEPOSIT if amt == 0 else amt + DEPOSIT
            max_states[uid] = "waiting_docs"
            max_docs[uid] = {}
            await tg_admin(f"🆕 Новый гость (MAX): {un}\n{name} | {dfrom}\n✅ Бронь найдена")
            if amt == 0:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"Отличные новости — вы уже полностью оплатили бронирование! 🎉\n\n"
                    f"🔑 Заселение у нас дистанционное — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения документов.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                    f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                    f"💰 Залог: {DEPOSIT} руб.\n\n"
                    f"{PAYMENT_INFO}\n\n"
                    f"⚠️ При переводе ничего не пишите в комментарии к платежу."
                )
            else:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"🔑 Заселение у нас дистанционное — вы заселяетесь самостоятельно через минисейф.\n"
                    f"Все инструкции, пароли и адрес придут после подтверждения оплаты.\n\n"
                    f"Для оформления нам потребуется:\n\n"
                    f"📄 Фото паспорта на чьё имя оформлена бронь (лицевая сторона)\n\n"
                    f"💰 Чек об оплате по реквизитам:\n\n"
                    f"• Остаток по бронированию: {amt} руб.\n"
                    f"• Залог: {DEPOSIT} руб.\n"
                    f"• Итого: {total} руб.\n\n"
                    f"{PAYMENT_INFO}\n\n"
                    f"⚠️ При переводе ничего не пишите в комментарии к платежу."
                )
            return

        if state == "waiting_docs":
            await event.message.answer("Пришлите:\n📄 Фото паспорта\n🧾 Чек об оплате\n\nМожно в любом порядке!")
            return

        if state == "waiting_new_booking_dates_max":
            apt_name = max_apt.get(uid, "неизвестный апартамент")
            tg_tok = os.getenv("TELEGRAM_TOKEN")
            admin_id = get_admin_chat_id()
            if admin_id and tg_tok:
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as c:
                        r = await c.post(
                            f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                            json={
                                "chat_id": admin_id,
                                "text": f"🔄 Запрос на продление/новую бронь (MAX)\n\n"
                                        f"Гость: {un}\nАпартамент: {apt_name}\n\n"
                                        f"Даты: {text}\n\n"
                                        f"Ответьте Reply — гость получит автоматически!"
                            }
                        )
                        msg_data = r.json()
                        if msg_data.get("ok"):
                            max_promo_map[msg_data["result"]["message_id"]] = uid
                except Exception as e:
                    print(f"[MAX] Ошибка продления: {e}", flush=True)
            max_states[uid] = "verified"
            await event.message.answer(
                "✅ Запрос на продление отправлен администратору!\n\n"
                "Ожидайте ответа — вам придёт сообщение в ближайшее время.\n\n"
                "Также можете позвонить: 📞 +7 918 148 00 45 (10:00–22:00)\n\n"
                "Если есть другие вопросы — задавайте, я готов помочь! 😊"
            )
            return

        if state == "waiting_early_time_max":
            apt_name = max_apt.get(uid, "апартамент")
            tg_tok = os.getenv("TELEGRAM_TOKEN")
            admin_id = get_admin_chat_id()
            if admin_id and tg_tok:
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as c:
                        r = await c.post(
                            f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                            json={
                                "chat_id": admin_id,
                                "text": f"🕐 Ранний заезд (MAX)\n\n"
                                        f"Гость: {un}\nАпартамент: {apt_name}\n"
                                        f"Хочет заехать: {text}\n\n"
                                        f"Ответьте Reply — гость получит автоматически!"
                            }
                        )
                        msg_data = r.json()
                        if msg_data.get("ok"):
                            max_promo_map[msg_data["result"]["message_id"]] = uid
                except Exception as e:
                    print(f"[MAX] Ошибка раннего заезда: {e}", flush=True)
            max_states[uid] = "verified"
            await event.message.answer(
                "✅ Запрос на ранний заезд отправлен!\n\n"
                "Оператор свяжется с вами в ближайшее время и подтвердит. ⏱\n\n"
                "Если есть другие вопросы — готов помочь! 😊"
            )
            return

        if state == "waiting_late_time_max":
            apt_name = max_apt.get(uid, "апартамент")
            tg_tok = os.getenv("TELEGRAM_TOKEN")
            admin_id = get_admin_chat_id()
            if admin_id and tg_tok:
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as c:
                        r = await c.post(
                            f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                            json={
                                "chat_id": admin_id,
                                "text": f"🕐 Поздний выезд (MAX)\n\n"
                                        f"Гость: {un}\nАпартамент: {apt_name}\n"
                                        f"Хочет выехать до: {text}\n\n"
                                        f"Ответьте Reply — гость получит автоматически!"
                            }
                        )
                        msg_data = r.json()
                        if msg_data.get("ok"):
                            max_promo_map[msg_data["result"]["message_id"]] = uid
                except Exception as e:
                    print(f"[MAX] Ошибка позднего выезда: {e}", flush=True)
            max_states[uid] = "verified"
            await event.message.answer(
                "✅ Запрос на поздний выезд отправлен!\n\n"
                "Оператор свяжется с вами в ближайшее время и подтвердит. ⏱\n\n"
                "Если есть другие вопросы — готов помочь! 😊"
            )
            return

        if state == "waiting_admin_confirmation":
            await event.message.answer("⏱ Документы на проверке.\nОбычно до 15 минут. Как только проверим — придёт вся информация по заселению! 🏠")
            return

        # Обработка текстовых команд выезда и продления через ИИ
        # Обработка текстовых команд выезда и продления через ИИ
        if state == "verified" and text:
            text_lower = text.lower().strip()

            # Проверяем явные маркеры без лишнего вызова ИИ
            checkout_words = ["выехали", "выехал", "выехала", "съехали", "съехал", "покинули", "уже уехали", "мы уехали", "положили ключи"]
            extend_words = ["продлить", "хочу продлить", "продление", "хотим продлить", "можно продлить", "новую бронь", "забронировать ещё"]

            if any(w in text_lower for w in checkout_words):
                intent = "ВЫЕЗД"
            elif any(w in text_lower for w in extend_words):
                intent = "ПРОДЛЕНИЕ"
            else:
                intent = "ДРУГОЕ"

            print(f"[MAX] Намерение: {intent}", flush=True)

            if "ВЫЕЗД" in intent:
                apt_name = max_apt.get(uid, "апартамент")
                await tg_admin(f"🚪 *{apt_name} — выехали* (MAX)\nГость: {un}")
                max_states[uid] = "waiting_feedback"
                await event.message.answer(
                    "Спасибо что выбрали Alekseev Apartments! 🙏\n\n"
                    "Нам очень важно ваше мнение — пожалуйста дайте обратную связь здесь в чате!\n\n"
                    "Как вам понравилось проживание? 😊"
                )
                return

            if "ПРОДЛЕНИЕ" in intent:
                apt_name = max_apt.get(uid, "апартамент")
                await tg_admin(f"🔄 Запрос на продление/новую бронь (MAX)\nАпартамент: {apt_name}\nГость: {un}\nСообщение: {text}")
                max_states[uid] = "waiting_new_booking_dates_max"
                await event.message.answer(
                    "Отлично! Для продления или новой брони укажите пожалуйста даты:\n\n"
                    "С какой по какую дату?\n\n"
                    "Например: с 01.07 по 05.07\n\n"
                    "Или позвоните на горячую линию: 📞 +7 918 148 00 45"
                )
                return
            # ДРУГОЕ — пускаем в Claude ниже

        if state == "waiting_requisites":
            apt_name = max_apt.get(uid, "неизвестный апартамент")
            await tg_admin(f"💳 Реквизиты (MAX)\nАпартамент: {apt_name}\nГость: {un}\n\nРеквизиты:\n{text}")
            await event.message.answer(
                "Благодарим за реквизиты! ✅\n\n"
                "Залог вернём сегодня до 00:00.\n\n"
                "Будем рады если вы оставите отзыв на площадке где бронировали "
                "(Авито, Островок, Яндекс Путешествия и т.д.).\n\n"
                "🎁 За скриншот отзыва мы подарим промокод:\n"
                "• 500 руб. от 1 суток\n"
                "• 1000 руб. от 2 суток\n\n"
                "Пришлите скриншот сюда! 📸"
            )
            max_states[uid] = "waiting_review_screenshot_max"
            return

        if state == "waiting_feedback":
            apt_name = max_apt.get(uid, "неизвестный апартамент")

            # ИИ определяет тональность
            sentiment = claude.messages.create(
                model="claude-sonnet-4-6", max_tokens=10,
                messages=[{"role":"user","content":
                    f"Это отзыв гостя: \"{text}\"\nОтветь только: ПОЗИТИВНЫЙ или НЕГАТИВНЫЙ"}]
            ).content[0].text.strip().upper()

            await tg_admin(
                f"{'⭐' if 'ПОЗИТИВ' in sentiment else '⚠️'} Отзыв (MAX)\n"
                f"Апартамент: {apt_name}\nГость: {un}\n"
                f"Тональность: {'😊 Позитивный' if 'ПОЗИТИВ' in sentiment else '😞 Негативный'}\n\n{text}"
            )

            if "ПОЗИТИВ" in sentiment:
                max_states[uid] = "waiting_requisites"
                await event.message.answer(
                    "Спасибо за тёплые слова! 🙏 Нам очень приятно! 😊\n\n"
                    "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                    "Номер телефона / Банк / ФИО получателя\n\n"
                    "Например: +79001234567 / Сбербанк / Иванов Иван Иванович"
                )
            else:
                max_states[uid] = "waiting_requisites"
                await event.message.answer(
                    "Нам очень жаль что что-то пошло не так. 😔\n\n"
                    "Мы обязательно свяжемся с вами!\n\n"
                    "Для возврата залога пришлите пожалуйста ваши реквизиты:\n\n"
                    "Номер телефона / Банк / ФИО получателя\n\n"
                    "Например: +79001234567 / Сбербанк / Иванов Иван Иванович"
                )
            return

        if state == "checkout_done_max":
            await event.message.answer("Рады слышать вас! 😊\n\nДля новой брони:\n📞 +7 918 148 00 45")
            return

        if state == "waiting_review_screenshot_max":
            await event.message.answer("Пришлите пожалуйста скриншот вашего отзыва 📸")
            return

        if state == "waiting_requisites":
            await tg_admin(f"💳 Реквизиты (MAX)\nАпартамент: {max_apt.get(uid, '?')}\nГость: {un}\n\n{text}")
            await event.message.answer("Благодарим за реквизиты! ✅\n\nЗалог вернём сегодня до 00:00.\n\nОставьте пожалуйста обратную связь! 😊")
            max_states[uid] = "waiting_feedback"
            return

        if state == "waiting_feedback":
            await tg_admin(f"⭐ Отзыв (MAX)\nАпартамент: {max_apt.get(uid, '?')}\nГость: {un}\n\n{text}")
            await event.message.answer("Спасибо за отзыв! 🙏\n\nБудем рады видеть вас снова! 🏠")
            max_states[uid] = "checkout_done"
            return

        if state == "checkout_done":
            await event.message.answer("Рады слышать вас! 😊\n\nДля новой брони:\n📞 +7 918 148 00 45")
            return

        # Claude отвечает
        if uid not in max_hist: max_hist[uid] = []
        max_hist[uid].append({"role":"user","content":text})
        if len(max_hist[uid]) > 20: max_hist[uid] = max_hist[uid][-20:]

        apt_ctx = ""
        apt_name = max_apt.get(uid)
        if apt_name:
            mem = load_memory()
            apt_info = mem.get("objects", {}).get(apt_name, "")
            if apt_info:
                import re as re_m
                apt_ctx = f"\n\n=== АПАРТАМЕНТ ГОСТЯ: {apt_name} ===\n{re_m.sub(r'<[^>]+>', '', apt_info)}"

        rep = claude.messages.create(model="claude-sonnet-4-6", max_tokens=1000,
            system=SYSTEM_PROMPT.format(knowledge=get_all_knowledge() + apt_ctx),
            messages=max_hist[uid])
        reply = rep.content[0].text

        if "[НУЖЕН_ОПЕРАТОР]" in reply:
            await tg_admin(f"❓ Вопрос (MAX) от {un}:\n\n{text}")
            clean_reply = reply.replace("[НУЖЕН_ОПЕРАТОР]", "").strip()
            if clean_reply:
                max_hist[uid].append({"role":"assistant","content":clean_reply})
                await event.message.answer(clean_reply)
            await event.message.answer("Также передал ваш вопрос оператору — свяжемся в ближайшее время! 😊")
        elif "[ЖАЛОБА]" in reply:
            await tg_admin(f"⚠️ ЖАЛОБА/ПРЕТЕНЗИЯ (MAX) от {un}:\n\n{text}")
            clean_reply = reply.replace("[ЖАЛОБА]", "").strip()
            max_hist[uid].append({"role":"assistant","content":clean_reply})
            await event.message.answer(clean_reply)
        elif "[ПРОДЛЕНИЕ]" in reply:
            await tg_admin(f"🔄 Продление (MAX) от {un}:\n{text}")
            await event.message.answer("Для продления:\n\n1️⃣ Напишите даты — мы уточним\n2️⃣ Или: 📞 +7 918 148 00 45")
        elif "[РАННИЙ_ЗАЕЗД]" in reply:
            await tg_admin(f"🕐 Ранний заезд (MAX) от {un}:\n{text}")
            early_text = "Ранний заезд: 400 руб/час до 14:00.\n\nСо скольки хотите заехать?"
            max_hist[uid].append({"role":"assistant","content":early_text})
            max_states[uid] = "waiting_early_time_max"
            await event.message.answer(early_text)
        elif "[ПОЗДНИЙ_ВЫЕЗД]" in reply:
            await tg_admin(f"🕐 Поздний выезд (MAX) от {un}:\n{text}")
            late_text = "Поздний выезд: 400 руб/час после 12:00.\n\nДо скольки хотите выехать?"
            max_hist[uid].append({"role":"assistant","content":late_text})
            max_states[uid] = "waiting_late_time_max"
            await event.message.answer(late_text)
        elif "[КУПИТЬ_ПАРКОВКУ]" in reply:
            tg_tok = os.getenv("TELEGRAM_TOKEN")
            admin_id = get_admin_chat_id()
            if admin_id and tg_tok:
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as c:
                        r = await c.post(
                            f"https://api.telegram.org/bot{tg_tok}/sendMessage",
                            json={"chat_id": admin_id,
                                  "text": f"🅿️ Запрос на парковочное место (MAX)\n\nГость: {un}\nАпартамент: 182 кв\n\nОтветьте Reply с реквизитами!"}
                        )
                        msg_data = r.json()
                        if msg_data.get("ok"):
                            max_promo_map[msg_data["result"]["message_id"]] = uid
                except Exception as e:
                    print(f"[MAX] Ошибка парковки: {e}", flush=True)
            buy_text = "✅ Запрос отправлен администратору!\n\nРеквизиты для оплаты пришлём вам в ближайшее время. ⏱"
            max_hist[uid].append({"role":"assistant","content":buy_text})
            await event.message.answer(buy_text)
        elif "[ПАРКОВКА_КРАСНАЯ]" in reply:
            parking_text = (
                "🚗 Варианты парковки:\n\n"
                "• Индивидуальное место -1 этаж — 1000 руб/сутки\n"
                "• Бесплатно — ул. Путевая\n"
                "• Платная с ул. Красная 176 — 60 руб/час 8-20 будни\n\n"
                "Если хотите приобрести индивидуальное место — напишите нам!"
            )
            max_hist[uid].append({"role":"assistant","content":parking_text})
            await event.message.answer(parking_text)
        else:
            max_hist[uid].append({"role":"assistant","content":reply})
            await event.message.answer(reply)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _max_loop = loop
    print("[MAX] MAX бот запущен!", flush=True)

    async def check_outbox():
        """Периодически проверяем очередь сообщений и отправляем"""
        while True:
            await asyncio.sleep(2)
            if max_outbox:
                for uid, msg_data in list(max_outbox.items()):
                    try:
                        cid = max_chat_ids.get(uid, uid)
                        if isinstance(msg_data, dict):
                            text = msg_data.get("text", "")
                            await mb.send_message(chat_id=cid, text=text)
                            if msg_data.get("with_checkout_buttons"):
                                # Гость заселён — ставим verified
                                max_states[uid] = "verified"
                                await asyncio.sleep(0.5)
                                await mb.send_message(
                                    chat_id=cid,
                                    text="━━━━━━━━━━━━━━━━━━━━\n\n"
                                         "🔑 Когда будете выезжать — положите ключи в минисейф и напишите нам сюда что вы выехали\n\n"
                                         "🔄 Хотите продлить проживание или сделать новую бронь? Тоже пишите — поможем!\n\n"
                                         "Мы всегда на связи! 😊"
                                )
                        else:
                            await mb.send_message(chat_id=cid, text=msg_data)
                        del max_outbox[uid]
                        print(f"[MAX] Сообщение отправлено гостю {cid}", flush=True)
                    except Exception as e:
                        print(f"[MAX] Ошибка очереди: {e}", flush=True)
                        del max_outbox[uid]

    async def run_all():
        await asyncio.gather(
            md.start_polling(mb),
            check_outbox()
        )

    try:
        loop.run_until_complete(run_all())
    except Exception as e:
        print(f"[MAX] Ошибка polling: {e}", flush=True)

max_thread = threading.Thread(target=start_max_bot, daemon=True)
max_thread.start()

app.run_polling()
