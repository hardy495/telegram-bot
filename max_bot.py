import os
import json
import asyncio
import anthropic
from dotenv import load_dotenv
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, BotStarted

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MAX_TOKEN = os.getenv("MAX_TOKEN")

MEMORY_FILE = "memory.json"

guest_states_max = {}
conversation_history_max = {}
guest_docs_max = {}
guest_balances_max = {}
guest_name_to_id_max = {}

DEPOSIT = 2000

PAYMENT_INFO = """+79181180045
СБЕРБАНК, Т-БАНК
Получатель: Антон Анатольевич А."""

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notes": [], "objects": {}}

def load_balances():
    """Загружаем балансы из общего файла если есть"""
    if os.path.exists("balances.json"):
        with open("balances.json", "r", encoding="utf-8") as f:
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
        str(getattr(sender, 'user_id', 'гость'))
    )

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

    # Начало — запрашиваем имя
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
        # Парсим имя и даты через ИИ
        parse_response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Из текста извлеки имя и даты бронирования.
Текст: "{text}"

Ответь строго в формате:
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
                "Пожалуйста, напишите имя на которое оформлена бронь и даты:\n\n"
                "Например: Иванов Иван с 01.01 по 02.01"
            )
            return

        guest_name_to_id_max[name.lower()] = user_id

        # Загружаем балансы из общего файла (который заполняет Telegram бот)
        shared_balances = load_balances()
        all_balances = {**guest_balances_max, **shared_balances}

        # Ищем бронь через ИИ
        balance_data = None
        if all_balances:
            bookings_text = ""
            booking_keys = []
            for i, (key, data) in enumerate(all_balances.items()):
                bookings_text += f"{i+1}. Имя: {data['name']}, заезд: {data['date_from']}, выезд: {data['date_to']}\n"
                booking_keys.append(key)

            match_response = claude.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=10,
                messages=[{
                    "role": "user",
                    "content": f"Гость: имя='{name}', заезд='{date_from}'\nБрони:\n{bookings_text}\nНайди совпадение. Ответь только номером или 0."
                }]
            )
            try:
                match_num = int(match_response.content[0].text.strip())
                if 1 <= match_num <= len(booking_keys):
                    balance_data = all_balances[booking_keys[match_num - 1]]
            except:
                pass

        if balance_data:
            amount = balance_data["amount"]
            total = DEPOSIT if amount == 0 else amount + DEPOSIT
            guest_states_max[user_id] = "waiting_docs"

            if amount == 0:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"Вы уже полностью оплатили бронирование! 🎉\n\n"
                    f"Заселение дистанционное — через минисейф. Инструкции придут после подтверждения.\n\n"
                    f"Для оформления:\n"
                    f"📄 Фото паспорта (лицевая сторона)\n"
                    f"💰 Залог: {DEPOSIT} руб.\n\n"
                    f"{PAYMENT_INFO}\n\n"
                    f"При переводе ничего не пишите в комментарии."
                )
            else:
                await event.message.answer(
                    f"✅ Бронь найдена!\n\n"
                    f"Заселение дистанционное — через минисейф. Инструкции придут после подтверждения оплаты.\n\n"
                    f"Для оформления:\n"
                    f"📄 Фото паспорта (лицевая сторона)\n"
                    f"💰 Оплата по реквизитам:\n"
                    f"• Остаток: {amount} руб.\n"
                    f"• Залог: {DEPOSIT} руб.\n"
                    f"• Итого: {total} руб.\n\n"
                    f"{PAYMENT_INFO}\n\n"
                    f"При переводе ничего не пишите в комментарии."
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
            "Пожалуйста пришлите:\n"
            "📄 Фото паспорта\n"
            "🧾 Чек об оплате\n\n"
            "Можно в любом порядке!"
        )
        return

    if state == "waiting_admin_confirmation":
        await event.message.answer(
            "⏱ Документы на проверке.\n"
            "Свяжемся в течение 10 минут!"
        )
        return

    # Верифицированный гость — отвечаем через Claude
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
            "Для продления проживания:\n\n"
            "Позвоните на горячую линию:\n"
            "📞 +7 918 148 00 45\n\n"
            "Дождитесь ответа оператора!"
        )
    elif "[НУЖЕН_ОПЕРАТОР]" in reply:
        await event.message.answer(
            "Спасибо за вопрос! 🙏\n\n"
            "По этому вопросу с вами свяжется оператор в течение 10 минут.\n\n"
            "Или позвоните: 📞 +7 918 148 00 45"
        )
    elif "[РАННИЙ_ЗАЕЗД]" in reply:
        await event.message.answer(
            "Ранний заезд возможен за доплату 400 руб/час до 14:00.\n\n"
            "Для согласования позвоните:\n"
            "📞 +7 918 148 00 45"
        )
    elif "[ПОЗДНИЙ_ВЫЕЗД]" in reply:
        await event.message.answer(
            "Поздний выезд возможен за доплату 400 руб/час после 12:00.\n\n"
            "Для согласования позвоните:\n"
            "📞 +7 918 148 00 45"
        )
    else:
        conversation_history_max[user_id].append({"role": "assistant", "content": reply})
        await event.message.answer(reply)


async def main():
    print("MAX бот запущен!", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
