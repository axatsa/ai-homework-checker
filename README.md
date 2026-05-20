# AI Homework Checker Bot

Telegram bot that uses Google Gemini AI to automatically check student homework — students send a photo of their work and the bot analyzes and grades it.

## Features
- Image-based homework submission
- Gemini AI analysis and feedback
- Multi-token support for rate limit handling
- FSM-based conversation flow
- Docker support for easy deployment

## Tech Stack
- Python 3.11+
- aiogram 3.x
- Google Gemini API
- Docker / Docker Compose

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env  # add BOT_TOKEN and GEMINI_TOKENS
python bot.py
```

Or with Docker:
```bash
docker-compose up --build
```