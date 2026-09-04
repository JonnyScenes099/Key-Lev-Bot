"""
Key Levels Telegram Bot
------------------------
Computes daily key levels (prior day/week high, low, close, and pivot points)
for a list of instruments, and posts them to a Telegram chat or channel.

Also supports an on-demand command: /levels TICKER

Data source: yfinance (free, no API key required). Works for stocks, ETFs,
indices (e.g. "^GSPC"), forex (e.g. "EURUSD=X"), and crypto (e.g. "BTC-USD").

Requirements (see requirements.txt):
    python-telegram-bot==21.*
    yfinance
    APScheduler
    python-dotenv
"""

import logging
import os

import yfinance as yf
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # channel or group to auto-post to

# Instruments to post automatically every morning. Edit this list freely.
WATCHLIST = ["EURUSD=X", "^GSPC", "BTC-USD", "GC=F"]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def compute_key_levels(ticker: str) -> dict:
    """
    Pulls recent daily candles and computes:
      - Previous day high/low/close
      - Previous week high/low
      - Classic floor-trader pivot point (P, R1, S1)
    """
    data = yf.Ticker(ticker).history(period="10d", interval="1d")
    if data.empty or len(data) < 2:
        raise ValueError(f"Not enough data returned for {ticker}")

    prev_day = data.iloc[-2]
    last_5 = data.iloc[-6:-1]  # rough "prior week" window

    high, low, close = prev_day["High"], prev_day["Low"], prev_day["Close"]
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high

    return {
        "ticker": ticker,
        "prev_day_high": round(high, 4),
        "prev_day_low": round(low, 4),
        "prev_day_close": round(close, 4),
        "week_high": round(last_5["High"].max(), 4),
        "week_low": round(last_5["Low"].min(), 4),
        "pivot": round(pivot, 4),
        "r1": round(r1, 4),
        "s1": round(s1, 4),
    }


def format_levels_message(levels: dict) -> str:
    return (
        f"📊 *{levels['ticker']}* Key Levels\n"
        f"Prev Day High: `{levels['prev_day_high']}`\n"
        f"Prev Day Low: `{levels['prev_day_low']}`\n"
        f"Prev Day Close: `{levels['prev_day_close']}`\n"
        f"Week High: `{levels['week_high']}`\n"
        f"Week Low: `{levels['week_low']}`\n"
        f"Pivot: `{levels['pivot']}`  |  R1: `{levels['r1']}`  |  S1: `{levels['s1']}`"
    )


async def levels_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /levels TICKER — on-demand lookup."""
    if not context.args:
        await update.message.reply_text("Usage: /levels EURUSD=X")
        return

    ticker = context.args[0].upper()
    try:
        levels = compute_key_levels(ticker)
        await update.message.reply_markdown(format_levels_message(levels))
    except Exception as exc:
        logger.exception("Failed to compute levels for %s", ticker)
        await update.message.reply_text(f"Couldn't get levels for {ticker}: {exc}")


async def post_daily_levels(app: Application) -> None:
    """Scheduled job: posts the whole watchlist to CHAT_ID."""
    if not CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID not set — skipping scheduled post.")
        return

    for ticker in WATCHLIST:
        try:
            levels = compute_key_levels(ticker)
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=format_levels_message(levels),
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Failed to post levels for %s", ticker)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Key Levels Bot is running.\nUse /levels TICKER (e.g. /levels BTC-USD) "
        "to get on-demand levels."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("levels", levels_command))

    scheduler = AsyncIOScheduler()
    # Runs every day at 07:00 UTC — adjust the hour to your preferred time.
    scheduler.add_job(post_daily_levels, "cron", hour=7, minute=0, args=[app])
    scheduler.start()

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
