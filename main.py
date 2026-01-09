import asyncio
import os
from fastapi import FastAPI

# Импортируем bot и dp из твоего файла
from customs_calculator_bot import bot, dp

app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "ok"}

# Запускаем aiogram при старте FastAPI
@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot))
