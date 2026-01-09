import asyncio
import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.types import Message

# Загружаем токен
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()

# Health-check для Koyeb
@app.get("/")
async def health_check():
    return {"status": "ok"}

# Пример хендлера
@dp.message()
async def echo(message: Message):
    await message.answer("Бот работает на Koyeb!")

# Запуск aiogram при старте FastAPI
@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot))
