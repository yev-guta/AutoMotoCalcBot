import os
import asyncio
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from customs_calculator_bot import dp, bot  # твой файл

app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "ok"}

# Webhook endpoint
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    await dp.feed_update(bot, data)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    # Устанавливаем webhook при старте
    webhook_url = f"https://{os.getenv('KOYEB_APP_URL')}/webhook"
    await bot.set_webhook(webhook_url)


# import asyncio
# import os
# from fastapi import FastAPI
#
# # Импортируем bot и dp из твоего файла
# from customs_calculator_bot import bot, dp
#
# app = FastAPI()
#
# @app.get("/")
# async def health_check():
#     return {"status": "ok"}
#
# # Запускаем aiogram при старте FastAPI
# @app.on_event("startup")
# async def on_startup():
#     asyncio.create_task(dp.start_polling(bot))


