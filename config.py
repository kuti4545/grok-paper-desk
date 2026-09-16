"""Sanal masa. Boyut ve kaldirac Grok kararinda."""

import os

BITGET_BASE = "https://api.bitget.com"
PRODUCT_TYPE = "USDT-FUTURES"

START_EQUITY = float(os.getenv("START_EQUITY", "300"))
# Sadece yazim hatasi durdurucu. Grok 1-50 secebilir.
ABSURD_LEVERAGE = int(os.getenv("ABSURD_LEVERAGE", "50"))
MAX_OPEN = int(os.getenv("MAX_OPEN", "6"))
CANDIDATE_SCORE = float(os.getenv("CANDIDATE_SCORE", "5.0"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCANNER_JSON = os.getenv(
    "SCANNER_JSON",
    "https://raw.githubusercontent.com/kuti4545/bitget-scanner/main/docs/latest.json",
)

BOOK_PATH = os.getenv("BOOK_PATH", "docs/book.json")
DECISION_PATH = os.getenv("DECISION_PATH", "docs/grok_decision.json")

SKIP_SYMBOLS = {
    "SPYUSDT", "QQQUSDT", "TSLAUSDT", "NVDAUSDT", "AAPLUSDT",
    "MSFTUSDT", "AMZNUSDT", "METAUSDT", "GOOGUSDT", "MSTRUSDT",
    "COINUSDT", "SOXLUSDT", "SOXSUSDT", "TQQQUSDT", "SPXUSDT",
    "JP225USDT", "NAS100USDT", "US30USDT", "PAXGUSDT", "XAUUSDT",
    "XAUTUSDT", "XAGUSDT", "HOODUSDT", "SAMSUNGEMUSDT",
}

INDICATORS = [
    "RSI",
    "MACD",
    "Hacim",
    "Bollinger",
    "VuManChu Cipher B",
    "PVG",
]
