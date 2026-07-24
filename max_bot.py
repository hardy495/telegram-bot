import os
import json
import base64
import asyncio
import anthropic
import httpx
from dotenv import load_dotenv
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, BotStarted

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MAX_TOKEN = os.getenv("MAX_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

MEMORY_FILE = "memory.json"
ADMIN_FILE = "admin.json"
BALANCES_FILE = "balances.json"

guest_states_max = {}
conversation_history_max = {}
guest_docs_max = {}
guest_name_to_id_max = {}
pending_guest_max = {}

DEPOSIT = 2000

PAYMENT_INFO = """+79181180045
СБЕРБАНК, Т-БАНК
Получатель: Антон Анатольевич А."""

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notes": [], "objects": {}}

def load_admin_chat_id():
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            return json.load(f).get("admin_chat_id")
    return None

def load_balances():
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_all_knowledge():
    memory = load_memory()
    text = ""
    if memory["objects"]:
        text += "=== АПАРТАМЕНТЫ ===\n"
        for name, info in memory["objects"].items():
            import re
            clean = re.sub(r'<[^>]+>', '', info)
            text += f"\n--- {name} ---\n{clean}\n"
    if memory["notes"]:
        text += "\n=== ЗАМЕТКИ ===\n"
        for i, note in enumerate(memory["notes"], 1):
            text += f"{i}. {note}\n"
    return text if text else "База знаний пока пуста."

async def send_to_telegram_admin(text, parse_mode=None):
    """Отправить сообщение администратору в Telegram"""
    admin_chat_id = load_admin_chat_id()
    if not admin_chat_id or not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": admin_chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

async def forward_photo_to_telegram(file_url, caption):
    """Переслать фото администратору в Telegram"""
    admin_chat_id = load_admin_chat_id()
    if not admin_chat_id or not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {"chat_id": admin_chat_id, "photo": file_url, "caption": caption}
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

SYSTEM_PROMPT = """Ты вежливый и профессиональный помощник для гостей апартаментов Alekseev Apartments.

=== СТРОГИЙ ЗАПРЕТ ===
Ты НИКОГДА не сообщаешь гостю адрес, код домофона, пароль минисейфа, пароль WiFi, номер квартиры.
Если спрашивают — отвечай: "Эта информация будет отправлена после подтверждения оплаты. ⏱"

=== ИНФОРМАЦИЯ ===
{knowledge}

=== ПРАВИЛА ===
- Заселение с 14:00, выезд до 12:00
- Ранний заезд/поздний выезд: 400 руб/час, нужно уточнять
- Залог 2000 руб возвращается в день выезда
- Во всех апартаментах: утюг, гладильная доска, полотенца, постельное бельё, фен, гель для душа

=== ПАРКОВКА ===
Октябрьская: двор, первые ворота между Пятёрочками, платная у Галереи/Кирова 8-20 будни.
Красная 176: -1 этаж 1000 руб/сутки, бесплатно ул.Путевая, платная 60 руб/час 8-20 будни.
Гаражная 107: шлагбаум на трафике, рекомендуем у Пятёрочки.
Коммунаров 270: вокруг дома или платная 60 руб/час 8-20 будни, вход с ул.Одесской.

=== МИНИСЕЙФ ===
Рядом со входом. Опустить чёрный рычажок вниз и потянуть дверцу на себя.
Если не работает — проверьте подъезд и корпус.

- Отвечай на русском
- Если не знаешь ответа — [НУЖЕН_ОПЕРАТОР]
- Если хочет продлить — [ПРОДЛЕНИЕ]
- Если ранний заезд — [РАННИЙ_ЗАЕЗД]
- Если поздний выезд — [ПОЗДНИЙ_ВЫЕЗД]
"""

bot = Bot(MAX_TOKEN)
dp = Dispatcher()

def get_username(sender):
    return (
        getattr(sender, 'name', None) or
        getattr(sender, 'username', None) or
        getattr(sender, 'first_name', None) or
        f"MAX_{getattr(sender, 'user_id', 'гость')}"
    )

async def find_booking(name, date_from):
    """Ищем бронь через ИИ"""
    balances = load_balances()
    if not balances:
        return None

    bookings_text = ""
    booking_keys = []
    for i, (key, data) in enumerate(balances.items()):
        bookings_text += f"{i+1}. Имя: {data['name']}, заезд: {data['date_from']}, выезд: {data['date_to']}\n"
        booking_keys.append(key)

    match_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=10,
        messages=[{
            "role": "user",
            "content": f"Гость: имя='{name}', заезд='{date_from}'\nБрони:\n{bookings_text}\nНайди совпадение по имени и датам. Ответь только номером или 0."
        }]
    )
    try:
        match_num = int(match_response.content[0].text.strip())
        if 1 <= match_num <= len(booking_keys):
            return balances[booking_keys[match_num - 1]]
    except:
        pass
    return None


@dp.bot_started()
async def on_start(event: BotStarted):
    user_id = event.message.sender.user_id
    guest_states_max[user_id] = "asking_name"
    conversation_history_max[user_id] = []
    guest_docs_max[user_id] = {}

    await event.message.answer(
        "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
        "Для того чтобы найти ваше бронирование в системе, пришлите пожалуйста "
        "вашу фамилию и имя на которое оформлена бронь и даты заезда/выезда:\n\n"
        "Например: Иванов Иван с 01.01 по 02.01"
    )


@dp.message_created()
async def on_message(event: MessageCreated):
    user_id = event.message.sender.user_id
    username = get_username(event.message.sender)
    text = event.message.body.text if event.message.body else ""

    if not text:
        return

    state = guest_states_max.get(user_id)

    if state is None:
        guest_states_max[user_id] = "asking_name"
        conversation_history_max[user_id] = []
        guest_docs_max[user_id] = {}
        await event.message.answer(
            "Здравствуйте! 👋 Добро пожаловать в Alekseev Apartments!\n\n"
            "Для того чтобы найти ваше бронирование в системе, пришлите пожалуйста "
            "вашу фамилию и имя на которое оформлена бронь и даты заезда/выезда:\n\n"
            "Например: Иванов Иван с 01.01 по 02.01"
        )
        return

    if state in ["asking_name", "waiting_balance"]:
        parse_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Из текста извлеки имя и даты.
Текст: "{text}"
ИМЯ: (имя)
ЗАЕЗД: (дата или пусто)
ВЫЕЗД: (дата или пусто)"""
            }]
        )
        raw = parse_response.content[0].text.strip()
        name, date_from, date_to = "", "", ""
        for line in raw.split("\n"):
            if line.upper().startswith("ИМЯ:"):
                name = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ЗАЕЗД:"):
                date_from = line.split(":", 1)[-1].strip()
            elif line.upper().startswith("ВЫЕЗД:"):
                date_to = line.split(":", 1)[-1].strip()

        if not name:
            await event.message.answer(
                "Пожалуйста, напишите имя и даты:\n\nНапример: Иванов Иван с 01.01 по 02.01"
            )
            return

        guest_name_to_id_max[name.lower()] = user_id
        balance_data = await find_booking(name, date_from)

        # Уведомляем Telegram администратора
        if not balance_data:
            await send_to_telegram_admin(
                f"🆕 Новый гость (MAX): {username}\nИмя: {name}\nЗаезд: {date_from} | Выезд: {date_to}\nБронь не найдена в базе."
            )

        if balance_data:
            amount = balance_data["amount"]
            total = DEPOSIT if amount == 0 else amount + DEPOSIT
            guest_states_max[user_id] = "waiting_docs"
            guest_docs_max[user_id] = {}

            await send_to_telegram_admin(
                f"🆕 Новый гость (MAX): {username}\nИмя: {name} | Заезд: {date_from}\n✅ Бронь найдена"
            )

            if amount == 0:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"Вы уже полностью оплатили бронирование! 🎉\n\n"
                    f"Заселение дистанционное — через минисейф. Инструкции придут после подтверждения.\n\n"
                    f"Для оформления:\n📄 Фото паспорта (лицевая сторона)\n"
                    f"💰 Залог: {DEPOSIT} руб.\n\n{PAYMENT_INFO}\n\nПри переводе ничего не пишите в комментарии."
                )
            else:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"Заселение дистанционное — через минисейф. Инструкции придут после подтверждения оплаты.\n\n"
                    f"Для оформления:\n📄 Фото паспорта (лицевая сторона)\n"
                    f"💰 Оплата:\n• Остаток: {amount} руб.\n• Залог: {DEPOSIT} руб.\n• Итого: {total} руб.\n\n"
                    f"{PAYMENT_INFO}\n\nПри переводе ничего не пишите в комментарии."
                )
        else:
            guest_states_max[user_id] = "waiting_balance"
            await event.message.answer(
                f"Бронирование на имя {name} не найдено.\n\n"
                f"Проверьте правильность имени и дат и напишите снова.\n\n"
                f"Например: Иванов Иван с 01.01 по 02.01"
            )
        return

    if state == "waiting_docs":
        await event.message.answer(
            "Пожалуйста пришлите:\n📄 Фото паспорта\n🧾 Чек об оплате\n\nМожно в любом порядке!"
        )
        return

    if state == "waiting_admin_confirmation":
        await event.message.answer("⏱ Документы на проверке.\nСвяжемся в течение 10 минут!")
        return

    if state == "waiting_requisites":
        await send_to_telegram_admin(
            f"💳 Реквизиты для возврата залога (MAX)\n\nГость: {username}\n\nРеквизиты:\n{text}"
        )
        await event.message.answer(
            "Благодарим вас за реквизиты! ✅\n\nЗалог вернём сегодня до 00:00.\n\nОставьте пожалуйста обратную связь здесь в чате! 😊"
        )
        guest_states_max[user_id] = "waiting_feedback"
        return

    if state == "waiting_feedback":
        await send_to_telegram_admin(
            f"⭐ Обратная связь (MAX)\n\nГость: {username}\n\n{text}"
        )
        await event.message.answer(
            "Спасибо за обратную связь! 🙏\n\nБудем рады видеть вас снова в Alekseev Apartments! 🏠"
        )
        guest_states_max[user_id] = "checkout_done"
        return

    if state == "checkout_done":
        await event.message.answer(
            "Рады слышать вас! 😊\n\nДля новой брони позвоните:\n📞 +7 918 148 00 45"
        )
        return

    # Верифицированный гость — Claude
    if user_id not in conversation_history_max:
        conversation_history_max[user_id] = []

    conversation_history_max[user_id].append({"role": "user", "content": text})
    if len(conversation_history_max[user_id]) > 20:
        conversation_history_max[user_id] = conversation_history_max[user_id][-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT.format(knowledge=get_all_knowledge()),
        messages=conversation_history_max[user_id]
    )
    reply = response.content[0].text

    if "[ПРОДЛЕНИЕ]" in reply:
        await event.message.answer(
            "Для продления проживания:\n\nПозвоните на горячую линию:\n📞 +7 918 148 00 45\n\nДождитесь ответа оператора!"
        )
    elif "[НУЖЕН_ОПЕРАТОР]" in reply:
        await send_to_telegram_admin(f"❓ Вопрос от гостя {username} (MAX):\n\n{text}")
        await event.message.answer(
            "Спасибо за вопрос! 🙏\n\nОператор свяжется с вами в течение 10 минут.\n\nИли позвоните: 📞 +7 918 148 00 45"
        )
    elif "[РАННИЙ_ЗАЕЗД]" in reply:
        await send_to_telegram_admin(f"🕐 Запрос раннего заезда (MAX)\nГость: {username}\nЗапрос: {text}")
        await event.message.answer(
            "Ранний заезд: 400 руб/час до 14:00.\n\nУточняю возможность у администратора — отвечу в течение 10 минут! ⏱"
        )
    elif "[ПОЗДНИЙ_ВЫЕЗД]" in reply:
        await send_to_telegram_admin(f"🕐 Запрос позднего выезда (MAX)\nГость: {username}\nЗапрос: {text}")
        await event.message.answer(
            "Поздний выезд: 400 руб/час после 12:00.\n\nУточняю возможность у администратора — отвечу в течение 10 минут! ⏱"
        )
    else:
        conversation_history_max[user_id].append({"role": "assistant", "content": reply})
        await event.message.answer(reply)


async def main():
    print("MAX бот запущен!", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
