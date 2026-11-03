# Dummy OTP API + Telegram Bot (sab fake/random, sirf testing)

## API (Vercel par deploy)
- /api/countries
- /api/number?country=IN&count=10
- /api/otp?number=+916043388827

## Bot (PC/VPS/Render par)
cd bot && pip install -r requirements.txt
export BOT_TOKEN="..." ; export API_URL="https://your-app.vercel.app/api"
python bot.py

## Price rule
- Screenshot wale countries: same price
- Top 50 (baaki): 22-78
- Baaki sab: market 113/123
