#🇺🇦 Telegram bot for calculating customs duties in Ukraine

A bot for calculating customs duties, excise taxes, VAT, and pension fund payments when importing vehicles into Ukraine.

## 📋 Features

- **Cars**: gasoline, diesel, electric (with and without tax breaks)
- **Trucks**: up to 5 tons
- **Motorcycles**: gasoline and electric
- **Current exchange rates**: get the NBU exchange rate for a selected date
- **Calculation history**: save all user calculations
- **Statistics**: for developers

## 🚀 Installation

### 1. Clone the project

```bash
git clone <repository_url>
cd customs-calculator-bot
```

### 2. Install dependencies
(pip freeze > requirements.txt)

```bash
python -m venv venv
# source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

### 3. Create a bot in Telegram

1. Find [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` command
3. Follow the instructions and get a token

### 4. Set up environment variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Fill in `.env`:

```env
BOT_TOKEN=your_token_from_BotFather
DEVELOPER_ID=your_telegram_id
CARRIER_USERNAME=carrier_username
```

**How ​​to find your Telegram ID:**
- Write to the bot [@userinfobot](https://t.me/userinfobot)

### 5. Run the bot

```bash
python customs-calculator-bot.py
```

## 📊 Calculation Formulas

### Passenger car (gasoline)

```
Total = Duty + Excise Duty + VAT + Pension Fund

Duty = Cost × 10%
Excise Duty = (Volume / 1,000) × Rate × Age Factor
VAT = (Cost + Duty + Excise Duty) × 20%
```

**Excise Duty Rates:**
- Up to 3,000 cm³: EUR 50 per 1,000 cm³
- Over 3,000 cm³: EUR 100 per 1,000 cm³

### Passenger Car (Diesel)

```
Duty = Cost × 10%
Excise Duty = (Volume / 1,000) × Rate × Age Factor Age
VAT = (Price + Duty + Excise Tax) × 20%
```

**Excise Tax Rates:**
- Up to 3,500 cm³: EUR 75 per 1,000 cm³
- Over 3,500 cm³: EUR 150 per 1,000 cm³

### Electric Vehicle

**With exemptions (until 31.12.2025):**
```
Duty = 0%
Excise Tax = EUR 1 × kWh of battery
VAT = 0%
```

**Without exemptions (from 01.01.2026):**
```
Duty = 0%
Excise Tax = EUR 1 × kWh of battery
VAT = (Price + Duty + Excise Tax) × 20%
```

### Truck (up to 5 tons)

```
Duty = Cost × 10%
Excise tax = Volume × 1000 × Coeff. Age
VAT = (Price + Duty + Excise Tax) × 20%
```

**Age Coefficients:**
- Up to 5 years: 0.02 EUR/cm³
- 5-8 years: 0.8 EUR/cm³
- Over 8 years: 1 EUR/cm³

### Motorcycle (petrol)

```
Duty = Price × 10%
Excise Tax = Volume × Coefficient
VAT = (Price + Duty + Excise Tax) × 20%
```

**Coefficients:**
- Up to 500 cm³: 0.062 EUR/cm³
- 500-800 cm³: 0.443 EUR/cm³
- Over 800 cm³: 0.447 EUR/cm³

### Electric Motorcycle

```
Duty = Cost x 10%
Excise Tax = 22 EUR (fixed)
VAT = (Cost + Duty + Excise Tax) x 20%
```

### Pension Fund

```
Cost < 150,000 UAH: 3%
Cost ≥ 150,000 UAH: 5%
```

## 💱 Exchange Rates

Rates are obtained automatically from the National Bank of Ukraine (NBU) API for the selected date.

## 🎯 Usage

### Basic commands:

- `/start` - start the bot

### Menu:

1. **🚗 Passenger Car** - calculation for a passenger car
2. **🚛 Truck** - calculation for a truck
3. **🏍️ Motorcycle** - calculation for a motorcycle
4. **💱 Exchange Rates** - view NBU exchange rates
5. **📞 Contact Carrier** - contact the carrier
6. **💬 Contact Developer** - contact the developer
7. **📜 Payment History** - your latest payments

### Usage example:

1. Click "🚗 Passenger Car"
2. Select engine type (gasoline/diesel/electric)
3. Enter the price: `15,000 USD` or `14,000 EUR`
4. Enter additional expenses: `500` (or `0`)
5. Enter the specifications:
- For gasoline/diesel: `2000 3` (volume in cm³ and age)
- For electric: `75` (battery capacity in kWh)
6. Select the date for the exchange rate
7. Get the full quote!

## 🔧 Technical Details

### Tech Stack:

- **Python 3.8+**
- **aiogram 3.4** - asynchronous library for Telegram Bot API
- **aiohttp** - asynchronous HTTP requests
- **python-dotenv** - environment variable management

### Architecture:

- FSM (Finite State Machine) for state management
- Asynchronous request processing
- NBU API for obtaining exchange rates
- In-memory calculation storage (use a database for production)

## 📝 Functionality Expansion

To add a database (PostgreSQL, MongoDB):

1. Install the database driver
2. Replace `calculations_db = []` with a connection to the database
3. Implement methods for saving/reading from the database

## ⚠️ Important Notes

1. **Exchange Rates**: The bot uses the official NBU exchange rates
2. **Benefits for Electric Vehicles**: Valid until December 31, 2025
3. **Calculation Accuracy**: Formulas are valid as of 2025
4. **Concurrent Users**: The bot supports multiple users thanks to FSM

## 📞 Contacts

- Developer: Specify in the `.env` file
- Carrier: Specify the username in the `.env` file

## 📄 License

MIT License

---

**Note**: The bot provides an approximate calculation. Exact amounts may vary. For official information, please contact the Ukrainian customs authorities.