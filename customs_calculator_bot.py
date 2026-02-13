import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import asyncio
# import sqlite3
# from contextlib import contextmanager

import asyncpg
from db import get_pool

# Loading environment variables
load_dotenv()

# Setting up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot initialization
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEVELOPER_ID = int(os.getenv('DEVELOPER_ID', '0'))
CARRIER_USERNAME = os.getenv('CARRIER_USERNAME', 'carrier')

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# In-memory calculation database (backup storage)
calculations_db = []


# Initializing the database
async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calculations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                vehicle_type TEXT NOT NULL,
                cost REAL NOT NULL,
                currency TEXT NOT NULL,
                additional REAL DEFAULT 0,
                total_uah REAL NOT NULL,
                duty REAL NOT NULL,
                excise REAL NOT NULL,
                vat REAL NOT NULL,
                pension REAL NOT NULL,
                total_payments REAL NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                year INTEGER,
                engine_volume REAL,
                battery_kwh REAL,
                usd_rate REAL,
                eur_rate REAL,
                total_customs REAL
            );
        """)


# FSM states
class CalculationStates(StatesGroup):
    choosing_vehicle = State()
    entering_cost = State()
    entering_currency = State()
    entering_additional = State()
    entering_additional_currency = State()
    entering_engine_volume = State()
    entering_year = State()
    entering_battery = State()
    choosing_date = State()
    custom_date = State()


# Function for obtaining the NBU exchange rate
async def get_nbu_rate(currency: str, date: datetime) -> Optional[float]:
    """Obtaining exchange rates from the NBU"""
    try:
        date_str = date.strftime('%Y%m%d')
        url = f"https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode={currency}&date={date_str}&json"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        return data[0]['rate']
        return None
    except Exception as e:
        logger.error(f"Помилка отримання курсу: {e}")
        return None


# Function for calculating the coefficient by year of manufacture
def calculate_age_coefficient(year: int) -> float:
    """Calculation of the age coefficient by year of release"""
    current_year = datetime.now().year
    next_year_after_production = year + 1
    age_diff = current_year - next_year_after_production

    if age_diff < 1:
        return 1.0
    elif age_diff >= 15:
        return 15.0
    else:
        return float(age_diff)


# Calculation function for a passenger car (gasoline)
def calculate_petrol_car(cost_uah: float, engine_volume: float, year: int) -> Dict:
    """Calculation for a gasoline car"""
    # Duty 10%
    duty = cost_uah * 0.10

    # Excise tax
    if engine_volume <= 3000:
        excise_rate = 50  # euro per 1000 cm3
    else:
        excise_rate = 100

    age_coef = calculate_age_coefficient(year)
    excise_eur = (engine_volume / 1000) * excise_rate * age_coef

    return {
        'duty': duty,
        'excise_eur': excise_eur,
        'age_coef': age_coef
    }


# Calculation function for diesel cars
def calculate_diesel_car(cost_uah: float, engine_volume: float, year: int) -> Dict:
    """Calculation for a diesel vehicle"""
    duty = cost_uah * 0.10

    if engine_volume <= 3500:
        excise_rate = 75
    else:
        excise_rate = 150

    age_coef = calculate_age_coefficient(year)
    excise_eur = (engine_volume / 1000) * excise_rate * age_coef

    return {
        'duty': duty,
        'excise_eur': excise_eur,
        'age_coef': age_coef
    }


# Calculation function for electric vehicle
# def calculate_electric_car(cost_uah: float, battery_kwh: float, with_benefits: bool) -> Dict:
#     """Calculation for an electric vehicle"""
#     excise_eur = battery_kwh * 1.0
#     duty = 0.0
#
#     if with_benefits:
#         # With benefits until December 31, 2025
#         vat = 0.0
#         return {
#             'duty': duty,
#             'excise_eur': excise_eur,
#             'vat': vat,
#             'with_benefits': True
#         }
#     else:
#         # No benefits
#         vat = 0.0
#         return {
#             'duty': duty,
#             'excise_eur': excise_eur,
#             'vat': vat,
#             'with_benefits': False
#         }

def calculate_electric_car(cost_uah: float, battery_kwh: float, with_benefits: bool) -> Dict:
    """Calculation for an electric vehicle"""
    excise_eur = battery_kwh * 1.0
    duty = 0.0
    return {
        'duty': duty,
        'excise_eur': excise_eur,
        'with_benefits': with_benefits
    }

def calculate_hybrid_petrol(cost_uah: float, engine_volume: float, year: int) -> Dict:
    return calculate_petrol_car(cost_uah, engine_volume, year)

def calculate_hybrid_diesel(cost_uah: float, engine_volume: float, year: int) -> Dict:
    return calculate_diesel_car(cost_uah, engine_volume, year)


# Calculation function for a truck
def calculate_truck(cost_uah: float, engine_volume: float, year: int) -> Dict:
    """Calculation for a petrol truck up to 5 tons"""
    # 5% duty for freight
    duty = cost_uah * 0.05

    current_year = datetime.now().year
    age = current_year - year

    if age < 5:
        excise_rate = 0.02
    elif age < 8:
        excise_rate = 0.8
    else:
        excise_rate = 1.0

    excise_eur = engine_volume  * excise_rate

    return {
        'duty': duty,
        'excise_eur': excise_eur,
        'age_coef': excise_rate
    }

def calculate_diesel_truck(cost_uah: float, engine_volume: float, year: int) -> Dict:
    """Calculation for a diesel truck up to 5 tons"""
    # 5% duty for freight
    duty = cost_uah * 0.10

    current_year = datetime.now().year
    age = current_year - year

    if age < 5:
        excise_rate = 0.02
    elif age < 8:
        excise_rate = 0.8
    else:
        excise_rate = 1.0

    excise_eur = engine_volume  * excise_rate

    return {
        'duty': duty,
        'excise_eur': excise_eur,
        'age_coef': excise_rate
    }

# Расчёт для электрического грузовика (электровантажівка)
def calculate_electric_truck(cost_uah: float) -> Dict:
    """Электрогрузовик: мито 10%, акциз 0, ПДВ 20%, пенсионный 0"""
    duty = cost_uah * 0.10
    excise_eur = 0.0
    return {
        'duty': duty,
        'excise_eur': excise_eur,
    }


# Calculation function for motorcycle
def calculate_motorcycle(cost_uah: float, engine_volume: float) -> Dict:
    """Calculation for a motorcycle"""
    duty = cost_uah * 0.10

    if engine_volume <= 50:
        excise_rate = 0.062
    elif engine_volume <= 250:
        excise_rate = 0.062
    elif engine_volume <= 500:
        excise_rate = 0.062
    elif engine_volume <= 800:
        excise_rate = 0.443
    else:
        excise_rate = 0.447

    excise_eur = engine_volume * excise_rate

    return {
        'duty': duty,
        'excise_eur': excise_eur
    }


# Calculation function for electric motorcycle
def calculate_electric_motorcycle(cost_uah: float) -> Dict:
    """Calculation for an electric motorcycle"""
    duty = cost_uah * 0.10
    excise_eur = 22.0

    return {
        'duty': duty,
        'excise_eur': excise_eur
    }


# Pension fund calculation function
def calculate_pension_fund(cost_uah: float, is_electric: bool = False) -> float:
    """
    Розрахунок збору до пенсійного фонду

    Пенсійний збір НЕ сплачується за електромобілі!

    Для других авто:
    - До 499 620 грн (165 прожиткових мінімумів): 3%
    - 499 620 - 878 120 грн (165-290 прожиткових мінімумів): 4%
    - Понад 878 120 грн (290 прожиткових мінімумів): 5%
    """
    # Електромобілі НЕ сплачують пенсійний збір
    if is_electric:
        return 0.0

    if cost_uah < 499620:
        return cost_uah * 0.03
    elif cost_uah < 878120:
        return cost_uah * 0.04
    else:
        return cost_uah * 0.05


# Main menu
def get_main_menu() -> ReplyKeyboardMarkup:
    """Creating a main menu"""
    kb = [
        [KeyboardButton(text="🚗 Легковий автомобіль")],
        [KeyboardButton(text="🚛 Вантажний автомобіль")],
        [KeyboardButton(text="🏍️ Мотоцикл")],
        [KeyboardButton(text="💱 Курс валют")],
        #[KeyboardButton(text="🚢 Доставка Європа - Україна")],
        [KeyboardButton(text="💬 Зв'язок із розробником")],
        [KeyboardButton(text="📜 Історія розрахунків")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# @dp.message(F.text == "🚢 Доставка Європа - Україна")
# async def contact_carrier(message: types.Message):
#     """Контакт перевозчика"""
#     await message.answer(
#         f"🚢 <b>Доставка Європа - Україна</b>\n\n"
#         f"📞 Зв'язатися з перевізником: @{CARRIER_USERNAME}\n\n"
#         f"💬 Запитайте вартість доставки Вашого автомобіля!",
#         parse_mode="HTML"
#     )


# Menu for selecting the type of passenger car
def get_car_type_menu() -> InlineKeyboardMarkup:
    """Menu of passenger car types"""
    buttons = [
        [InlineKeyboardButton(text="⛽ Бензин", callback_data="car_petrol")],
        [InlineKeyboardButton(text="🛢️ Дизель", callback_data="car_diesel")],
        # [InlineKeyboardButton(text="⚡ Електро (Пільги закінчилися 31.12.2025)", callback_data="car_electric_benefits")],
        [InlineKeyboardButton(text="⚡ Електро (без пільг)", callback_data="car_electric_no_benefits")],
        [InlineKeyboardButton(text="🔌 Гібрид (бензин)", callback_data="car_hybrid_petrol")],
        [InlineKeyboardButton(text="🔌 Гібрид (дизель)", callback_data="car_hybrid_diesel")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_truck_type_menu() -> InlineKeyboardMarkup:
    """Truck engine type selection menu"""
    buttons = [
        [InlineKeyboardButton(text="⛽ Бензин (5%)", callback_data="truck_petrol")],
        [InlineKeyboardButton(text="Дизель (10%)", callback_data="truck_diesel")],
        [InlineKeyboardButton(text="⚡ Електро (акциз 0)", callback_data="truck_electric")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Motorcycle type selection menu
def get_motorcycle_type_menu() -> InlineKeyboardMarkup:
    """Motorcycle Types Menu"""
    buttons = [
        [InlineKeyboardButton(text="⛽ Бензиновий", callback_data="moto_petrol")],
        [InlineKeyboardButton(text="⚡ Електричний", callback_data="moto_electric")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Select date menu
def get_date_menu() -> InlineKeyboardMarkup:
    """Course date selection menu"""
    buttons = [
        [InlineKeyboardButton(text="📅 Сьогодні", callback_data="date_today")],
        [InlineKeyboardButton(text="📅 Завтра", callback_data="date_tomorrow")],
        [InlineKeyboardButton(text="📅 Вчора", callback_data="date_yesterday")],
        [InlineKeyboardButton(text="📅 Інша дата", callback_data="date_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# /start command handler
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Processing the /start command"""
    await state.clear()
    await message.answer(
        "🇺🇦 <b>Калькулятор митних платежів України для авто та мото!</b>\n\n"
        "Виберіть тип транспортного засобу для розрахунку:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )


# Booklet "Passenger car"
@dp.message(F.text == "🚗 Легковий автомобіль")
async def choose_car(message: types.Message, state: FSMContext):
    """Selecting a passenger car type"""
    await message.answer(
        "Виберіть тип двигуна:",
        reply_markup=get_car_type_menu()
    )
    await state.set_state(CalculationStates.choosing_vehicle)


# Truck handler
@dp.message(F.text == "🚛 Вантажний автомобіль")
async def choose_truck(message: types.Message, state: FSMContext):
    """Выбор типа двигателя грузовика"""
    await state.clear()
    await message.answer(
        "Виберіть тип двигуна:\n\n"
        "• <b>Бензин</b> — мито 5%\n"
        "• <b>Дизель</b> — мито 10%",
        reply_markup=get_truck_type_menu(),
        parse_mode="HTML"
    )
    await state.set_state(CalculationStates.choosing_vehicle)


# Motorcycle handler
@dp.message(F.text == "🏍️ Мотоцикл")
async def choose_motorcycle(message: types.Message, state: FSMContext):
    """Choosing a motorcycle type"""
    await message.answer(
        "Виберіть тип мотоцикла:",
        reply_markup=get_motorcycle_type_menu()
    )
    await state.set_state(CalculationStates.choosing_vehicle)


# Exchange Rate Handler
@dp.message(F.text == "💱 Курс валют")
async def show_rates_menu(message: types.Message, state: FSMContext):
    """Exchange Rates Menu"""
    await state.clear()  # Clearing the state
    await message.answer(
        "📊 Виберіть дату для перегляду курсу:",
        reply_markup=get_date_menu()
    )


# "Contact with carrier" handler
# @dp.message(F.text == "📞 Зв'язок із перевізником")
# async def contact_carrier(message: types.Message):
#     """Carrier contact"""
#     await message.answer(
#         f"📞 Зв'язатися з перевізником: @{CARRIER_USERNAME}"
#     )


# "Contact the Developer" handler
@dp.message(F.text == "💬 Зв'язок із розробником")
async def contact_developer(message: types.Message):
    """Retailer contact"""
    await message.answer(
        f"💬 Зв'язатися з розробником: @EvGT_7"
    )

@dp.message(F.text.contains == "📜 Історія розрахунків")
async def show_history(message: types.Message):
    """Show user payment history (last 5 calculations)"""
    user_id = message.from_user.id

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT vehicle_type, total_payments, created_at, year, engine_volume, battery_kwh,
                       total_uah, total_customs, currency, usd_rate, eur_rate
                FROM calculations
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 5
            """, user_id)
    except Exception as e:
        logger.error(f"Помилка читання історії з БД для {user_id}: {e}")
        rows = []

    # fallback на память, если хочешь оставить
    if not rows:
        memory_calcs = [c for c in calculations_db if c.get('user_id') == user_id]
        memory_calcs = sorted(memory_calcs, key=lambda x: x.get('date', ''), reverse=True)[:5]
        rows = memory_calcs

    if not rows:
        await message.answer("📜 Історія розрахунків порожня")
        return

    history_text = "📜 <b>Ваші останні розрахунки (до 5):</b>\n\n"

    for calc in rows:
        # asyncpg.Record
        if not isinstance(calc, dict):
            vehicle_type = calc["vehicle_type"]
            year = calc["year"]
            engine_volume = calc["engine_volume"]
            battery_kwh = calc["battery_kwh"]
            total_uah = calc["total_uah"] or 0
            total_customs = calc["total_customs"] or 0
            currency = calc["currency"]
            usd_rate = calc["usd_rate"] or 0
            eur_rate = calc["eur_rate"] or 0
            date_str = str(calc["created_at"])[:19]
        else:  # из памяти
            vehicle_type = calc.get("vehicle_type", "N/A")
            year = calc.get("year")
            engine_volume = calc.get("engine_volume")
            battery_kwh = calc.get("battery_kwh")
            total_uah = calc.get("total_uah", 0)
            total_customs = calc.get("total_customs", 0)
            currency = calc.get("currency", "UAH")
            usd_rate = calc.get("usd_rate", 0)
            eur_rate = calc.get("eur_rate", 0)
            date_str = calc.get("date", "N/A")

        if engine_volume:
            spec = f"{engine_volume} см³"
        elif battery_kwh:
            spec = f"{battery_kwh} кВт·год"
        else:
            spec = "—"

        if currency == "USD" and usd_rate > 0:
            customs_in_currency = total_customs / usd_rate
            curr_symbol = "USD"
        elif currency == "EUR" and eur_rate > 0:
            customs_in_currency = total_customs / eur_rate
            curr_symbol = "EUR"
        else:
            customs_in_currency = total_customs
            curr_symbol = "грн"

        history_text += (
            f"🚗 <b>{vehicle_type}</b>\n"
            + (f"📅 Рік: {year}\n" if year else "")
            + f"🔧 {spec}\n"
            f"💰 Вартість = {total_uah:.2f} грн\n"
            f"💵 РАЗОМ митниця: {total_customs:.2f} грн ({customs_in_currency:.2f} {curr_symbol})\n"
            f"📅 {date_str}\n\n"
        )

    await message.answer(history_text, parse_mode="HTML")



# Statistics Handler (for developer only)
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    """Show statistics (developer only)"""
    if message.from_user.id != DEVELOPER_ID:
        await message.answer("❌ У вас немає доступу до статистики")
        return

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            total_calcs = await conn.fetchval("SELECT COUNT(*) FROM calculations")
            unique_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM calculations")
            today_calcs = await conn.fetchval("""
                SELECT COUNT(*) 
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '1 day'
            """)
            popular_vehicles = await conn.fetch("""
                SELECT vehicle_type, COUNT(*) AS count
                FROM calculations
                GROUP BY vehicle_type
                ORDER BY count DESC
                LIMIT 5
            """)
        stats_text = (
            "📊 <b>Статистика робота</b>\n\n"
            f"👥 Унікальних користувачів: {unique_users}\n"
            f"🧮 Усього розрахунків: {total_calcs}\n"
            f"📅 За останні 24ч: {today_calcs}\n\n"
            "<b>Популярні типи ТЗ:</b>\n"
        )
        for v in popular_vehicles:
            stats_text += f"• {v['vehicle_type']}: {v['count']}\n"
    except Exception as e:
        logger.error(f"Помилка статистики: {e}")
        total_calcs = len(calculations_db)
        unique_users = len(set(c["user_id"] for c in calculations_db))
        stats_text = (
            "📊 <b>Статистика робота</b>\n\n"
            f"👥 Унікальних користувачів: {unique_users}\n"
            f"🧮 Усього розрахунків: {total_calcs}\n"
        )

    await message.answer(stats_text, parse_mode="HTML")



# Callback handler for vehicle types
@dp.callback_query(F.data.startswith("car_"))
async def process_car_type(callback: types.CallbackQuery, state: FSMContext):
    """Processing vehicle type selection"""
    car_type = callback.data.replace("car_", "")
    await state.update_data(vehicle_type=f"car_{car_type}")
    #await state.set_state(CalculationStates.entering_cost)

    # Для электро С ЛЬГОТАМИ - только батарея
    if car_type == "electric_benefits":
        await state.set_state(CalculationStates.entering_battery)
        await callback.message.edit_text(
            "⚡ <b>Електромобіль (З ПІЛЬГАМИ)</b>\n\n"
            "🔋 Введіть ємність батареї у кВт·год.:\n"
            "<code>75</code>",
            parse_mode="HTML"
        )
    # Для электро БЕЗ ЛЬГОТ - сначала стоимость
    elif car_type == "electric_no_benefits":
        await state.set_state(CalculationStates.entering_cost)
        await callback.message.edit_text(
            "⚡ <b>Електромобіль (БЕЗ ПІЛЬГ)</b>\n\n"
            "💰 Введіть вартість автомобіля:\n"
            "<code>15000</code>",
            parse_mode="HTML"
        )
    elif car_type == "hybrid_petrol":
        await state.update_data(vehicle_type="car_hybrid_petrol")
        await state.set_state(CalculationStates.entering_cost)
        await callback.message.edit_text(
            "🔌 <b>Гібрид (бензин)</b>\n\n"
            "💰 Введіть вартість автомобіля:\n"
            "<code>15000</code>",
            parse_mode="HTML"
        )
    elif car_type == "hybrid_diesel":
        await state.update_data(vehicle_type="car_hybrid_diesel")
        await state.set_state(CalculationStates.entering_cost)
        await callback.message.edit_text(
            "🔌 <b>Гібрид (дизель)</b>\n\n"
            "💰 Введіть вартість автомобіля:\n"
            "<code>15000</code>",
            parse_mode="HTML"
        )
    else:
        # Для других авто запрашиваем стоимость
        await state.set_state(CalculationStates.entering_cost)
        await callback.message.edit_text(
            f"💰 Введіть вартість автомобіля:\n"
            f"<code>15000</code>",
            parse_mode="HTML"
        )

    await callback.answer()

@dp.callback_query(F.data.startswith("truck_"))
async def process_truck_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора типа грузовика"""
    engine = callback.data.replace("truck_", "")
    vehicle_type = f"truck_{engine}"
    await state.update_data(vehicle_type=vehicle_type)
    await state.set_state(CalculationStates.entering_cost)

    if engine in ("petrol", "diesel"):
        await callback.message.edit_text(
            "Введіть вартість вантажного автомобіля:\n"
            "<code>12000</code>",
            parse_mode="HTML"
        )
    elif engine == "electric":
        await callback.message.edit_text(
            "⚡ <b>Електричний вантажний автомобіль</b>\n\n"
            "💰 Введіть вартість:\n"
            "<code>30000</code>",
            parse_mode="HTML"
        )
    await callback.answer()


# Callback handler for motorcycle types
@dp.callback_query(F.data.startswith("moto_"))
async def process_moto_type(callback: types.CallbackQuery, state: FSMContext):
    """Processing motorcycle type selection"""
    moto_type = callback.data.replace("moto_", "")
    await state.update_data(vehicle_type=f"moto_{moto_type}")
    await state.set_state(CalculationStates.entering_cost)

    await callback.message.edit_text(
        f"💰 Введіть вартість мотоцикла у форматі:\n"
        f"<code>8000 USD</code> або <code>7500 EUR</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# Обробник введення вартості
@dp.message(CalculationStates.entering_cost)
async def process_cost(message: types.Message, state: FSMContext):
    """Обробка введення вартості"""
    try:
        cost = float(message.text.strip())
        await state.update_data(cost=cost)
        await state.set_state(CalculationStates.entering_currency)

        # Кнопки выбора валюты
        buttons = [
            [InlineKeyboardButton(text="🇺🇸 USD", callback_data="currency_USD")],
            [InlineKeyboardButton(text="🇪🇺 EUR", callback_data="currency_EUR")],
            [InlineKeyboardButton(text="🇺🇦 UAH", callback_data="currency_UAH")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"💰 Вартість: {cost}\n\nВиберіть валюту:",
            reply_markup=keyboard
        )
    except:
        await message.answer("❌ Введіть число. Наприклад: <code>15000</code>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("currency_"))
async def process_currency(callback: types.CallbackQuery, state: FSMContext):
    """Processing the selection of cost currency"""
    currency = callback.data.replace("currency_", "")
    await state.update_data(currency=currency)
    await state.set_state(CalculationStates.entering_additional)

    await callback.message.edit_text(
        f"💵 Введіть додаткові витрати (або 0):\n"
        f"<code>500</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(CalculationStates.entering_additional)
async def process_additional(message: types.Message, state: FSMContext):
    """Processing additional expenses"""
    try:
        additional = float(message.text.strip())
        await state.update_data(additional=additional)

        if additional > 0:
            await state.set_state(CalculationStates.entering_additional_currency)

            # Buttons for selecting the currency of additional expenses
            buttons = [
                [InlineKeyboardButton(text="🇺🇸 USD", callback_data="add_currency_USD")],
                [InlineKeyboardButton(text="🇪🇺 EUR", callback_data="add_currency_EUR")],
                [InlineKeyboardButton(text="🇺🇦 UAH", callback_data="add_currency_UAH")]
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

            await message.answer(
                f"💵 Додаткові витрати: {additional}\n\nВиберіть валюту:",
                reply_markup=keyboard
            )
        else:
            # If there are no additional expenses, we keep the default USD and move on.
            await state.update_data(additional_currency="USD")

            # We determine the next step based on the vehicle type
            data = await state.get_data()
            vehicle_type = data['vehicle_type']

            if vehicle_type == "car_electric_benefits":
                # С льготами - только батарея (стоимость уже 0)
                await state.set_state(CalculationStates.entering_battery)
                await message.answer(
                    "🔋 Введіть ємність батареї у кВт·год.:\n"
                    "<code>75</code>",
                    parse_mode="HTML"
                )
            elif vehicle_type == "car_electric_no_benefits":
                # Без льгот - запрашиваем батарею после стоимости
                await state.set_state(CalculationStates.entering_battery)
                await message.answer(
                    "🔋 Введіть ємність батареї у кВт·год.:\n"
                    "<code>75</code>",
                    parse_mode="HTML"
                )
            elif vehicle_type == "truck_electric":
                await state.set_state(CalculationStates.choosing_date)
                await message.answer(
                    "📅 Виберіть дату курсу валют:",
                    reply_markup=get_date_menu()
                )
            elif vehicle_type == "moto_electric":
                await state.set_state(CalculationStates.choosing_date)
                await message.answer(
                    "📅 Виберіть дату курсу валют:",
                    reply_markup=get_date_menu()
                )
            elif vehicle_type == "moto_petrol":
                await state.set_state(CalculationStates.entering_engine_volume)
                await message.answer(
                    "🔧 Введіть об'єм двигуна см³:\n"
                    "<code>600</code>",
                    parse_mode="HTML"
                )
            else:
                # For cars with an engine (petrol/diesel/truck)
                await state.set_state(CalculationStates.entering_engine_volume)
                await message.answer(
                    "🔧 Введіть об'єм двигуна см³:\n"
                    "<code>2000</code>",
                    parse_mode="HTML"
                )
    except:
        await message.answer("❌ Введіть число")


@dp.callback_query(F.data.startswith("add_currency_"))
async def process_additional_currency(callback: types.CallbackQuery, state: FSMContext):
    """Processing the selection of currency for additional expenses"""
    currency = callback.data.replace("add_currency_", "")
    await state.update_data(additional_currency=currency)

    await callback.message.delete()

    # We determine the next step based on the vehicle type
    data = await state.get_data()
    vehicle_type = data['vehicle_type']

    if vehicle_type == "car_electric_benefits":
        # С льготами - только батарея (стоимость уже 0)
        await state.set_state(CalculationStates.entering_battery)
        await callback.message.answer(
            "🔋 Введіть ємність батареї у кВт·год.:\n"
            "<code>75</code>",
            parse_mode="HTML"
        )
    elif vehicle_type == "car_electric_no_benefits":
        # Без льгот - запрашиваем батарею после стоимости
        await state.set_state(CalculationStates.entering_battery)
        await callback.message.answer(
            "🔋 Введіть ємність батареї у кВт·год.:\n"
            "<code>75</code>",
            parse_mode="HTML"
        )
    elif vehicle_type == "truck_electric":
        await state.set_state(CalculationStates.choosing_date)
        await callback.message.answer(
            "📅 Виберіть дату курсу валют:",
            reply_markup=get_date_menu()
        )
    elif vehicle_type == "moto_electric":
        await state.set_state(CalculationStates.choosing_date)
        await callback.message.answer(
            "📅 Виберіть дату курсу валют:",
            reply_markup=get_date_menu()
        )
    elif vehicle_type == "moto_petrol":
        await state.set_state(CalculationStates.entering_engine_volume)
        await callback.message.answer(
            "🔧 Введіть об'єм двигуна см³:\n"
            "<code>600</code>",
            parse_mode="HTML"
        )
    else:
        # For cars with an engine (petrol/diesel/hybrids/truck_petrol/truck_diesel)
        await state.set_state(CalculationStates.entering_engine_volume)
        await callback.message.answer(
            "🔧 Введіть об'єм двигуна см³:\n"
            "<code>2000</code>",
            parse_mode="HTML"
        )

    await callback.answer()


# Vehicle characteristics handler
@dp.message(CalculationStates.entering_engine_volume)
async def process_engine_volume(message: types.Message, state: FSMContext):
    """Engine displacement processing"""
    try:
        engine_volume = float(message.text.strip())
        await state.update_data(engine_volume=engine_volume)

        data = await state.get_data()
        vehicle_type = data['vehicle_type']

        # Motorcycles don't need a year
        if vehicle_type == "moto_petrol":
            await state.set_state(CalculationStates.choosing_date)
            await message.answer(
                "📅 Виберіть дату курсу валют:",
                reply_markup=get_date_menu()
            )
        else:
            # For cars, we request the year
            await state.set_state(CalculationStates.entering_year)
            await message.answer(
                "📅 Введіть рік випуску автомобіля:\n"
                "<code>2020</code>",
                parse_mode="HTML"
            )
    except:
        await message.answer("❌ Введіть число. Наприклад: <code>2000</code>", parse_mode="HTML")


@dp.message(CalculationStates.entering_year)
async def process_year(message: types.Message, state: FSMContext):
    """Processing of the year of manufacture"""
    try:
        year = int(message.text.strip())
        current_year = datetime.now().year

        if year < 1900 or year > current_year + 1:
            await message.answer(f"❌ Неправильний рік. Введіть рік від 1900 до {current_year + 1}")
            return

        await state.update_data(year=year)
        await state.set_state(CalculationStates.choosing_date)
        await message.answer(
            "📅 Виберіть дату курсу валют:",
            reply_markup=get_date_menu()
        )
    except:
        await message.answer("❌ Введіть рік. Наприклад: <code>2020</code>", parse_mode="HTML")

@dp.message(CalculationStates.entering_battery)
async def process_battery(message: types.Message, state: FSMContext):
    """Battery capacity processing"""
    try:
        battery_kwh = float(message.text.strip())
        await state.update_data(battery_kwh=battery_kwh)
        # For electric vehicles, we skip straight to selecting the date.
        # Cost = 0, as it's not needed for the calculation.
        data = await state.get_data()
        vehicle_type = data['vehicle_type']

        # ТОЛЬКО для электро С ЛЬГОТАМИ обнуляем стоимость
        if vehicle_type == "car_electric_benefits":
            await state.update_data(
                cost=0,
                currency="EUR",
                additional=0,
                additional_currency="EUR"
            )
        await state.set_state(CalculationStates.choosing_date)
        await message.answer(
            "📅 Виберіть дату курсу валют:",
            reply_markup=get_date_menu()
        )
    except:
        await message.answer("❌ Введіть число. Наприклад: <code>75</code>", parse_mode="HTML")


# Date picker handler
@dp.callback_query(F.data.startswith("date_"))
async def process_date_choice(callback: types.CallbackQuery, state: FSMContext):
    """Date selection processing"""
    date_choice = callback.data.replace("date_", "")

    # We check if there is an active calculation
    data = await state.get_data()

    if date_choice == "custom":
        await state.set_state(CalculationStates.custom_date)
        await callback.message.edit_text(
            "📅 Введіть дату у форматі ДД.ММ.РРРР:\n"
            "<code>01.01.2025</code>",
            parse_mode="HTML"
        )
    else:
        if date_choice == "today":
            date = datetime.now()
        elif date_choice == "tomorrow":
            date = datetime.now() + timedelta(days=1)
        elif date_choice == "yesterday":
            date = datetime.now() - timedelta(days=1)

        # If there is data for calculation, we perform the calculation.
        if 'vehicle_type' in data:
            await perform_calculation(callback.message, state, date)
            await state.clear()
        else:
            # Otherwise, we just show the rate
            await show_rate_only(callback.message, date)

    await callback.answer()


# Custom Date Handler
@dp.message(CalculationStates.custom_date)
async def process_custom_date(message: types.Message, state: FSMContext):
    """Handling a custom date"""
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")

        data = await state.get_data()
        if 'vehicle_type' in data:
            await perform_calculation(message, state, date)
            await state.clear()
        else:
            await show_rate_only(message, date)
    except:
        await message.answer("❌ Неправильний формат дати. Використовуйте: ДД.ММ.РРРР")


# Function to display the exchange rate without calculation
async def show_rate_only(message: types.Message, date: datetime):
    """Show only the exchange rate without calculation"""
    usd_rate = await get_nbu_rate("USD", date)
    eur_rate = await get_nbu_rate("EUR", date)

    if not usd_rate or not eur_rate:
        await message.answer("❌ Помилка отримання курсу валют")
        return

    response = f"💱 <b>Курс НБУ на {date.strftime('%d.%m.%Y')}</b>\n\n"
    response += f"🇺🇸 1 USD = {usd_rate:.4f} грн\n"
    response += f"🇪🇺 1 EUR = {eur_rate:.4f} грн\n\n"
    response += f"💵 100 USD = {usd_rate * 100:.2f} грн\n"
    response += f"💶 100 EUR = {eur_rate * 100:.2f} грн"

    await message.answer(response, parse_mode="HTML", reply_markup=get_main_menu())


# Calculation execution function

async def save_calculation_to_db(calc_data: dict):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO calculations (
                    user_id, username, vehicle_type, cost, currency, additional,
                    total_uah, duty, excise, vat, pension, total_payments,
                    year, engine_volume, battery_kwh, usd_rate, eur_rate, total_customs
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18
                )
            """,
                calc_data['user_id'],
                calc_data['username'],
                calc_data['vehicle_type'],
                calc_data['cost'],
                calc_data['currency'],
                calc_data['additional'],
                calc_data['total_uah'],
                calc_data['duty'],
                calc_data['excise'],
                calc_data['vat'],
                calc_data['pension'],
                calc_data['total_payments'],
                calc_data['year'],
                calc_data['engine_volume'],
                calc_data['battery_kwh'],
                calc_data['usd_rate'],
                calc_data['eur_rate'],
                calc_data['total_customs'],
            )
        logger.info(f"✅ Розрахунок збережено для користувача {calc_data['user_id']}")
    except Exception as e:
        logger.error(f"❌ Помилка збереження у БД (PostgreSQL): {e}")


async def perform_calculation(message: types.Message, state: FSMContext, date: datetime):
    """Calculation of customs duties"""
    data = await state.get_data()

    # Получение курсов валют
    usd_rate = await get_nbu_rate("USD", date)
    eur_rate = await get_nbu_rate("EUR", date)
    if not usd_rate or not eur_rate:
        await message.answer("❌ Помилка отримання курсу валют")
        return

    # Converting the cost to hryvnia
    cost = data['cost']
    currency = data['currency']
    if currency == "USD":
        cost_rate = usd_rate
    elif currency == "EUR":
        cost_rate = eur_rate
    else:
        cost_rate = 1.0
    cost_uah = cost * cost_rate

    # Converting additional expenses
    additional = data.get('additional', 0)
    additional_currency = data.get('additional_currency', 'USD')
    if additional_currency == "USD":
        add_rate = usd_rate
    elif additional_currency == "EUR":
        add_rate = eur_rate
    else:
        add_rate = 1.0
    additional_uah = additional * add_rate

    total_uah = cost_uah + additional_uah
    vehicle_type = data['vehicle_type']

    # Let's check if it's an electric car
    is_electric = vehicle_type.startswith("car_electric") or vehicle_type == "moto_electric" or vehicle_type == "truck_electric"

    # Calculation depending on the type of vehicle
    duty = 0.0
    excise_uah = 0.0
    vat = 0.0
    pension = 0.0
    total_customs = 0.0

    if vehicle_type == "car_petrol":
        result = calculate_petrol_car(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "car_diesel":
        result = calculate_diesel_car(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type.startswith("car_electric"):
        with_benefits = vehicle_type == "car_electric_benefits"  # Точна перевірка
        result = calculate_electric_car(total_uah, data['battery_kwh'], with_benefits)
        duty = result['duty']  # 0
        excise_uah = result['excise_eur'] * eur_rate
        if with_benefits:
            vat = 0.0
        else:
            vat_base = total_uah + excise_uah
            vat = vat_base * 0.20
    elif vehicle_type == "car_hybrid_petrol":
        result = calculate_hybrid_petrol(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "car_hybrid_diesel":
        result = calculate_hybrid_diesel(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "truck_petrol":
        result = calculate_truck(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "truck_diesel":
        result = calculate_diesel_truck(total_uah, data['engine_volume'], data['year'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "truck_electric":
        result = calculate_electric_truck(total_uah)
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "moto_petrol":
        result = calculate_motorcycle(total_uah, data['engine_volume'])
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate
    elif vehicle_type == "moto_electric":
        result = calculate_electric_motorcycle(total_uah)
        duty = result['duty']
        excise_uah = result['excise_eur'] * eur_rate

    # VAT calculation
    if vehicle_type != "car_electric_benefits":
        vat = (total_uah + duty + excise_uah) * 0.20

    # Pension Fund
    if vehicle_type.startswith("truck_") or is_electric:
        pension = 0.0
    else:
        pension = calculate_pension_fund(total_uah, is_electric)

    # Total customs duties (WITHOUT pension fund)
    total_customs = duty + excise_uah + vat

    # Total (with pension fund)
    total_payments = total_customs + pension

    # We get the year and calculate the coefficient for display
    year_info = ""
    if 'year' in data:
        age_coef = calculate_age_coefficient(data['year'])
        current_year = datetime.now().year
        age = current_year - data['year']
        year_info = f"📅 Рік випуску: {data['year']} (вік: {age} лет)\n"
        year_info += f"📊 Коефіцієнт віку: {age_coef}\n"

    # Battery information for electric vehicles
    battery_info = ""
    if 'battery_kwh' in data:
        battery_info = f"🔋 Місткість батареї: {data['battery_kwh']} кВт·год\n"

    # Convert the total to the cost currency for comparison
    if currency == "USD":
        total_in_currency = total_customs / usd_rate
        currency_symbol = "$"
    elif currency == "EUR":
        total_in_currency = total_customs / eur_rate
        currency_symbol = "€"
    else:
        total_in_currency = total_customs
        currency_symbol = "грн"

    # Forming a response
    response = f"📊 <b>Результат розрахунку</b>\n\n"
    response += f"💰 Вартість: {cost} {currency} = {cost_uah:.2f} грн\n"
    if additional > 0:
        response += f"➕ Дод. витрати: {additional} {additional_currency} = {additional_uah:.2f} грн\n"
    response += f"💵 Загальна вартість: {total_uah:.2f} грн\n\n"

    if year_info:
        response += year_info + "\n"
    if battery_info:
        response += battery_info + "\n"

    response += f"<b>Митні платежі:</b>\n"

    # We show the correct duty rate
    if vehicle_type == "truck_petrol":
        response += f"• Мито (5%): {duty:.2f} грн\n"
    elif vehicle_type == "truck_diesel":
        response += f"• Мито (10%): {duty:.2f} грн\n"
    elif vehicle_type == "truck_electric":
        response += f"• Мито (10%): {duty:.2f} грн\n"
    elif vehicle_type.startswith("car_electric") or vehicle_type == "moto_electric":
        if vehicle_type == "car_electric_benefits":
            response += f"• Мито (0% - пільга): {duty:.2f} грн\n"
        else:
            response += f"• Мито (0%): {duty:.2f} грн\n"
    else:
        response += f"• Мито (10%): {duty:.2f} грн\n"

    response += f"• Акциз: {result.get('excise_eur', 0):.2f} EUR = {excise_uah:.2f} грн\n"

    if vehicle_type == "car_electric_benefits":
        response += f"• ПДВ (0% - пільга): {vat:.2f} грн\n"
    else:
        response += f"• ПДВ (20%): {vat:.2f} грн\n"

    response += f"\n💵 <b>РАЗОМ митниця: {total_customs:.2f} грн ({total_in_currency:.2f} {currency_symbol})</b>\n"

    # Пенсійний фонд
    if is_electric:
        response += f"\n• Пенсійний фонд: 0.00 грн (електромобілі не сплачують ✅)\n"
    else:
        # Определяем процент
        if total_uah < 499620:
            pension_percent = "3%"
        elif total_uah < 878120:
            pension_percent = "4%"
        else:
            pension_percent = "5%"
        response += f"\n• Пенсійний фонд ({pension_percent}): {pension:.2f} грн\n"

    response += f"\n💰 <b>ВСЬОГО з пенсійним: {total_payments:.2f} грн</b>\n"
    response += f"\n📅 Курс НБУ на {date.strftime('%d.%m.%Y')}:\n"
    response += f"USD: {usd_rate:.2f} грн | EUR: {eur_rate:.2f} грн"

    await message.answer(response, parse_mode="HTML", reply_markup=get_main_menu())

    # # Saving to the database and memory
    # calc_data = {
    #     'user_id': message.from_user.id,
    #     'username': message.from_user.username or '',
    #     'vehicle_type': vehicle_type,
    #     'cost': cost,
    #     'currency': currency,
    #     'additional': additional,
    #     'total_uah': total_uah,
    #     'duty': duty,
    #     'excise': excise_uah,
    #     'vat': vat,
    #     'pension': pension,
    #     'total_payments': total_payments,
    #     'year': data.get('year'),
    #     'engine_volume': data.get('engine_volume'),
    #     'battery_kwh': data.get('battery_kwh'),
    #     'usd_rate': usd_rate,
    #     'eur_rate': eur_rate,
    #     'total_customs': total_customs,
    #     'date': datetime.now().strftime('%d.%m.%Y %H:%M')
    # }
    #
    # # Saving to local memory
    # calculations_db.append(calc_data)
    #
    # # Saving to SQLite
    # try:
    #     with get_db() as conn:
    #         cursor = conn.cursor()
    #         cursor.execute('''
    #                        INSERT INTO calculations
    #                        (user_id, username, vehicle_type, cost, currency, additional,
    #                         total_uah, duty, excise, vat, pension, total_payments,
    #                         year, engine_volume, battery_kwh, usd_rate, eur_rate, total_customs)
    #                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #                        ''', (
    #                            calc_data['user_id'],
    #                            calc_data['username'],
    #                            calc_data['vehicle_type'],
    #                            calc_data['cost'],
    #                            calc_data['currency'],
    #                            calc_data['additional'],
    #                            calc_data['total_uah'],
    #                            calc_data['duty'],
    #                            calc_data['excise'],
    #                            calc_data['vat'],
    #                            calc_data['pension'],
    #                            calc_data['total_payments'],
    #                            calc_data['year'], calc_data['engine_volume'], calc_data['battery_kwh'],
    #                            calc_data['usd_rate'], calc_data['eur_rate'], calc_data['total_customs']
    #                        ))
    #         conn.commit()
    #         logger.info(f"✅ Розрахунок збережено для користувача {calc_data['user_id']}")
    # except Exception as e:
    #     logger.error(f"❌ Помилка збереження у БД: {e}")

    # Saving to the database and memory
    calc_data = {
        'user_id': message.from_user.id,
        'username': message.from_user.username or '',
        'vehicle_type': vehicle_type,
        'cost': cost,
        'currency': currency,
        'additional': additional,
        'total_uah': total_uah,
        'duty': duty,
        'excise': excise_uah,
        'vat': vat,
        'pension': pension,
        'total_payments': total_payments,
        'year': data.get('year'),
        'engine_volume': data.get('engine_volume'),
        'battery_kwh': data.get('battery_kwh'),
        'usd_rate': usd_rate,
        'eur_rate': eur_rate,
        'total_customs': total_customs,
        'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
    }

    # локальная память (как резерв)
    calculations_db.append(calc_data)

    # сохранение в Supabase (PostgreSQL)
    await save_calculation_to_db(calc_data)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Processing the /start command"""
    await state.clear()
    await message.answer(
        "🇺🇦 <b>Калькулятор митних платежів України</b>\n\n"
        "Розрахунок включає:\n"
        "• Ввізне мито\n"
        "• Акцизний збір\n"
        "• ПДВ (20%)\n"
        "• Пенсійний збір (⚡ електромобілі не сплачують!)\n\n"
        "Виберіть тип транспортного засобу:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("pension"))
async def show_pension_info(message: types.Message):
    """Information about pension tax"""
    info = (
        "📋 <b>Пенсійний збір 2025</b>\n\n"
        "<b>Розміри:</b>\n"
        "• До 499 620 грн (165 прожитк. мін.) — <b>3%</b>\n"
        "• 499 620 - 878 120 грн (165-290 прожитк. мін.) — <b>4%</b>\n"
        "• Понад 878 120 грн (290 прожитк. мін.) — <b>5%</b>\n\n"
        "⚡ <b>ВАЖЛИВО:</b> Пенсійний збір <u>НЕ сплачується</u> за легкові автомобілі, "
        "оснащені виключно електродвигунами!\n\n"
        "🔋 Електромобілі звільнені від пенсійного збору."
    )
    await message.answer(info, parse_mode="HTML")


@dp.message(Command("export"))
async def export_history(message: types.Message):
    """Exporting payment history to CSV (developer only)"""
    if message.from_user.id != DEVELOPER_ID:
        return

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, user_id, username, vehicle_type, cost, currency,
                       total_uah, total_payments, created_at
                FROM calculations
                ORDER BY created_at DESC
            """)

        if not rows:
            await message.answer("No data available for export")
            return

        # CSV header
        csv_content = "ID,User_ID,Username,Vehicle_Type,Cost,Currency,Total_UAH,Total_Payments,Date\n"

        # CSV rows
        for row in rows:
            csv_content += (
                f"{row['id']},"
                f"{row['user_id']},"
                f"{row['username'] or ''},"
                f"{row['vehicle_type']},"
                f"{row['cost']},"
                f"{row['currency']},"
                f"{row['total_uah']:.2f},"
                f"{row['total_payments']:.2f},"
                f"{row['created_at']}\n"
            )

        # Convert to file
        from io import BytesIO
        file = BytesIO(csv_content.encode("utf-8"))

        await message.answer_document(
            types.BufferedInputFile(file.getvalue(), filename="calculations.csv"),
            caption="📊 Експорт усіх розрахунків"
        )

    except Exception as e:
        await message.answer(f"❌ Помилка експорту: {str(e)}")

@dp.message(Command("export_xlsx"))
async def export_xlsx(message: types.Message):
    if message.from_user.id != DEVELOPER_ID:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM calculations
            ORDER BY created_at DESC
        """)

    if not rows:
        await message.answer("Немає даних для експорту")
        return

    from openpyxl import Workbook
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "Calculations"

    # Заголовки
    ws.append(list(rows[0].keys()))

    # Данные
    for row in rows:
        ws.append(list(row.values()))

    file = BytesIO()
    wb.save(file)
    file.seek(0)

    await message.answer_document(
        types.BufferedInputFile(file.read(), filename="calculations.xlsx"),
        caption="📘 Експорт у Excel"
    )

# Callback handler "Back"
@dp.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Return to the main menu"""
    await state.clear()
    await callback.message.edit_text(
        "🇺🇦 <b>Калькулятор митних платежів України для авто та мото!</b>\n\n"
        "Виберіть тип транспортного засобу для розрахунку:",
        parse_mode="HTML"
    )
    await callback.answer()


# Launching the bot
async def main():
    """Launching the bot"""
    # Инициализация БД
    try:
        await init_db()
        logger.info("✅ The database has been initialized.")
    except Exception as e:
        logger.warning(f"⚠️ Failed to initialize the database: {e}")
        logger.info("The bot will only work with memory")

    logger.info("🚀 The bot has been launched!")
    #await dp.start_polling(bot)


# if __name__ == '__main__':
#     asyncio.run(main())

