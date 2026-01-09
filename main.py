import asyncio
from fastapi import FastAPI
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.types import Message

import os

TOKEN = os.getenv("BOT_TOKEN")  # бери токен из .env

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "ok"}

@dp.message()
async def echo(message: Message):
    await message.answer("Бот работает на Koyeb!")

async def start_bot():
    await dp.start_polling(bot)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())  # запускаем бота в фоне

    uvicorn.run(app, host="0.0.0.0", port=8000)
