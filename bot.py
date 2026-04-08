import asyncio
import io
import os
import logging
from typing import Any, Awaitable, Callable, Dict, List, Union

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, TelegramObject
from aiogram.filters import CommandStart, StateFilter
from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from PIL import Image
from dotenv import load_dotenv

import google.generativeai as genai

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")

if not BOT_TOKEN or not GEMINI_TOKEN:
    raise ValueError("BOT_TOKEN or GEMINI_TOKEN is missing in .env file.")

# Настроим логирование
logging.basicConfig(level=logging.INFO)

# Инициализируем бота и диспетчер
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

class UserStates(StatesGroup):
    choosing_subject = State()
    choosing_english_type = State()
    active = State()

# Клавиатуры
def get_subject_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🇬🇧 Английский"), KeyboardButton(text="🔢 Математика"))
    return builder.as_markup(resize_keyboard=True)

def get_english_type_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📝 IELTS"), KeyboardButton(text="🎯 General"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

# Настройка Gemini
genai.configure(api_key=GEMINI_TOKEN)

SYSTEM_PROMPT_MATH = """You are an expert tutor in Mathematics. Your task is to analyze the image or text provided by the student, identify all tasks, and verify the correctness of the solutions.

Check every step of the calculation. If there is an error, point out exactly which line is wrong, explain why, and provide the correct step-by-step solution.

CRITICAL Formatting rules for your response:
1. Be concise but clear.
2. Use HTML tags for bold text: <b>text</b>. 
3. In the "✅ Правильное решение" section, ALWAYS wrap ONLY the corrected or fixed words/phrases in <b>bold tags</b>.
4. Use line breaks and dashes (-) for lists to make the "Анализ ошибок" section easy to read.
5. DO NOT use any Markdown formatting.

Respond in Russian language, but keep technical terms clear. 
Structure your response EXACTLY like this (including emojis):

📝 <b>Найденные задачи:</b>
[Краткий перечень]

🔍 <b>Анализ ошибок:</b>
- [Что не так] — [Почему это ошибка]

✅ <b>Правильное решение:</b>
[Текст решения, где <b>исправленные</b> места выделены жирным]

💡 <b>Совет:</b>
[Короткое правило]
"""

SYSTEM_PROMPT_ENGLISH_GENERAL = """You are an expert English Language tutor. Your task is to analyze the image or text provided by the student, identify all tasks, and verify the correctness of the solutions.

Check grammar, spelling, punctuation, and sentence structure. Explain the grammar rule that was violated.

CRITICAL Formatting rules for your response:
1. Be concise but clear.
2. Use HTML tags for bold text: <b>text</b>. 
3. In the "✅ Correct solution" section, ALWAYS wrap ONLY the corrected or fixed words/phrases in <b>bold tags</b>.
4. Use line breaks and dashes (-) for lists to make the "Error analysis" section easy to read.
5. DO NOT use any Markdown formatting.

Respond ONLY in English. 
Structure your response EXACTLY like this (including emojis):

📝 <b>Found tasks:</b>
[Short list]

🔍 <b>Error analysis:</b>
- [What is wrong] — [Why it is an error]

✅ <b>Correct solution:</b>
[Text of the exercise, where <b>corrected</b> places are highlighted in bold]

💡 <b>Tip:</b>
[Short rule]
"""

SYSTEM_PROMPT_IELTS = """You are an IELTS expert tutor. Your task is to analyze the student's essay or English task and provide feedback in a specific format.

Follow these rules for corrections:
1. Identify errors in Intro, Body 1, Body 2, and Conclusion sections.
2. For each correction, show: [original phrase] - [corrected phrase].
3. Provide an overall score at the end (e.g., 5.5, 6.0, 7.0).

Respond ONLY in English. Structure your response EXACTLY like this:

Intro:
- [error] - [correction]

Body 1:
- [error] - [correction]

Body 2:
- [error] - [correction]

Conclusion:
- [error] - [correction]

<b>Score: [Score]</b>

Example of correction style:
moving an another places - moving to other places 
In this essay I intend - In this essay, I intend
"""

# Автоматический выбор доступной модели
AVAILABLE_MODEL = "models/gemini-flash-latest" # Значение по умолчанию
try:
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    logging.info(f"Available models: {available_models}")
    
    # Ищем лучшую из доступных (убираем 2.0-flash, так как на ней limit:0)
    for preferred in [
        "models/gemini-2.5-flash",
        "models/gemini-flash-latest",
        "models/gemini-3-flash-preview", 
        "models/gemini-2.5-pro"
    ]:
        if preferred in available_models:
            AVAILABLE_MODEL = preferred
            break
    logging.info(f"Selected model: {AVAILABLE_MODEL}")
except Exception as e:
    logging.error(f"Failed to fetch model list: {e}")

# Мы будем использовать динамический выбор модели при генерации, 
# но для инициализации оставим базовую.
base_model = genai.GenerativeModel(
    model_name=AVAILABLE_MODEL,
    system_instruction=SYSTEM_PROMPT_MATH,
)

class MediaGroupMiddleware(BaseMiddleware):
    def __init__(self, latency: Union[int, float] = 0.5):
        self.latency = latency
        self.album_data: dict[str, List[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.media_group_id:
            data['album'] = None
            return await handler(event, data)

        try:
            self.album_data[event.media_group_id].append(event)
            return
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)
            data["album"] = self.album_data[event.media_group_id]
            result = await handler(event, data)
            del self.album_data[event.media_group_id]
            return result

# Регистрируем Middleware
dp.message.middleware(MediaGroupMiddleware())

# В HTML нам экранирование не нужно, мы будем отправлять как есть или просто менять скобки


async def process_photo_message(message: Message, bot: Bot) -> Image.Image:
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type in ["image/jpeg", "image/png"]:
        file_id = message.document.file_id
    else:
        return None

    file_info = await bot.get_file(file_id)
    file_bytes_io = await bot.download_file(file_info.file_path)
    img = Image.open(file_bytes_io)
    img.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    return img

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(UserStates.choosing_subject)
    await message.answer(
        "👋 Привет! Я твой персональный AI-учитель.\n\n"
        "Пожалуйста, выбери предмет, который мы будем проверять:",
        reply_markup=get_subject_kb(),
        parse_mode="HTML"
    )

@dp.message(UserStates.choosing_subject, F.text == "🇬🇧 Английский")
async def process_english(message: Message, state: FSMContext):
    await state.set_state(UserStates.choosing_english_type)
    await message.answer(
        "Вы выбрали Английский. Какой тип задания вы хотите проверить?",
        reply_markup=get_english_type_kb()
    )

@dp.message(UserStates.choosing_subject, F.text == "🔢 Математика")
async def process_math(message: Message, state: FSMContext):
    await state.update_data(subject="math", type="math")
    await state.set_state(UserStates.active)
    await message.answer(
        "Вы выбрали Математику. Теперь отправьте мне фотографию или текст задания, и я его проверю!",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(UserStates.choosing_english_type, F.text == "📝 IELTS")
async def process_ielts(message: Message, state: FSMContext):
    await state.update_data(subject="english", type="ielts")
    await state.set_state(UserStates.active)
    await message.answer(
        "Вы выбрали IELTS. Отправьте ваше эссе или другое задание уровня IELTS, и я дам развернутый фидбек.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(UserStates.choosing_english_type, F.text == "🎯 General")
async def process_general(message: Message, state: FSMContext):
    await state.update_data(subject="english", type="general")
    await state.set_state(UserStates.active)
    await message.answer(
        "Вы выбрали General English. Отправьте задание для проверки.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(F.text == "⬅️ Назад")
async def process_back(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == UserStates.choosing_english_type:
        await cmd_start(message, state)
    elif current_state == UserStates.active:
        user_data = await state.get_data()
        if user_data.get("subject") == "english":
            await process_english(message, state)
        else:
            await cmd_start(message, state)

@dp.message(UserStates.active, F.photo | F.document | F.text)
async def handle_homework(message: Message, bot: Bot, state: FSMContext, album: List[Message] = None):
    # Если это текстовое сообщение "Назад", оно обработается выше, 
    # но на всякий случай проверяем здесь
    if message.text == "⬅️ Назад":
        return

    user_data = await state.get_data()
    mode_type = user_data.get("type", "general")
    subject = user_data.get("subject", "math")
    
    if subject == "math":
        prompt = SYSTEM_PROMPT_MATH
    elif mode_type == "ielts":
        prompt = SYSTEM_PROMPT_IELTS
    else:
        prompt = SYSTEM_PROMPT_ENGLISH_GENERAL
        
    # Создаем модель с нужным промптом
    current_model = genai.GenerativeModel(
        model_name=AVAILABLE_MODEL,
        system_instruction=prompt,
    )

    messages = album if album else [message]
    contents = [] # Список для Gemini (текст + картинки)
    
    status_msg = await message.answer("🔍 Проверяю ваше задание, подождите немного...")

    try:
        for msg in messages:
            if msg.text:
                contents.append(msg.text)
            elif msg.caption:
                contents.append(msg.caption)
                
            img = await process_photo_message(msg, bot)
            if img:
                contents.append(img)
                
        if not contents:
            await status_msg.edit_text("❌ Я не вижу текста или изображения. Пожалуйста, отправьте задание снова.")
            return

        # Генерация ответа (через асинхронный метод старой библиотеки)
        response = await current_model.generate_content_async(contents)
        
        reply_text = response.text
        if not reply_text:
            await status_msg.edit_text("🤔 Я не смог распознать текст или задания на этом фото.")
            return

        # Экранируем математические знаки < и >, но оставляем наши <b> теги
        safe_response = reply_text.replace("<", "&lt;").replace(">", "&gt;")
        safe_response = safe_response.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        
        # Умное разбиение на куски, если текст всё еще длинный
        def chunk_text(text: str, max_len: int = 4000) -> list[str]:
            chunks = []
            while len(text) > max_len:
                split_at = text.rfind('\n\n', 0, max_len)
                if split_at == -1:
                    split_at = text.rfind('\n', 0, max_len)
                if split_at == -1:
                    split_at = max_len
                chunks.append(text[:split_at])
                text = text[split_at:].lstrip()
            chunks.append(text)
            return chunks

        if len(safe_response) > 4000:
            for text_chunk in chunk_text(safe_response):
                await message.answer(text_chunk, parse_mode="HTML")
            await status_msg.delete() 
        else:
            await status_msg.edit_text(safe_response, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Error: {e}")
        error_msg = str(e).lower()
        if "429" in error_msg or "quota" in error_msg:
             await status_msg.edit_text("⏳ Лимиты API на сегодня исчерпаны. Попробуйте создать новый ключ или подождите немного.")
        elif "404" in error_msg:
             await status_msg.edit_text("⚠️ Ошибка: модель не найдена. Проверьте API ключ или новый проект.")
        else:
             await status_msg.edit_text("⚠️ Произошла ошибка. Проверьте четкость фото или попробуйте позже.")

async def main():
    logging.info("Bot started and ready!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
