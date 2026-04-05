import asyncio
import io
import os
import logging
from typing import Any, Awaitable, Callable, Dict, List, Union

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, TelegramObject
from aiogram.filters import CommandStart
from aiogram import BaseMiddleware

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
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Настройка Gemini
genai.configure(api_key=GEMINI_TOKEN)

SYSTEM_PROMPT = """You are an expert tutor in Mathematics and English Language. Your task is to analyze the image or text provided by the student, identify all tasks, and verify the correctness of the solutions.

For Mathematics: Check every step of the calculation. If there is an error, point out exactly which line is wrong, explain why, and provide the correct step-by-step solution.

For English: Check grammar, spelling, punctuation, and sentence structure. Explain the grammar rule that was violated.

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
[Текст упражнения или решения, где <b>исправленные</b> места выделены жирным]

💡 <b>Совет:</b>
[Короткое правило]
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

# Инициализируем модель с системной инструкцией
model = genai.GenerativeModel(
    model_name=AVAILABLE_MODEL,
    system_instruction=SYSTEM_PROMPT,
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
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я твой персональный AI-учитель.\n\n"
        "Отправь мне фотографию с заданием или просто <b>напиши текст</b> или <b>отправь фотографию</b> с заданием и я сам найду его и проверю.\n\n"
        "<i>(Можно отправлять текстовые сообщения, несколько фото или документы)</i>",
        parse_mode="HTML"
    )

@dp.message(F.photo | F.document | F.text)
async def handle_homework(message: Message, bot: Bot, album: List[Message] = None):
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
        response = await model.generate_content_async(contents)
        
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
