import os
from typing import List


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _env_list(name: str) -> List[str]:
    value = os.getenv(name, "")
    if not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# =========================
# Infraestructura
# =========================
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# =========================
# CoinW / Trading
# =========================
COINW_BASE_URL = os.getenv("COINW_BASE_URL", "https://api.coinw.com")
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT").upper()
# Producción: usar prácticamente todo el saldo útil dejando un pequeño colchón.
CAPITAL_ACTIVO_PORC = min(max(_env_float("CAPITAL_ACTIVO_PORC", 0.995), 0.0), 1.0)
STOP_LOSS_PORC = _env_float("STOP_LOSS_PORC", 0.02)
TAKE_PROFIT_PORC = _env_float("TAKE_PROFIT_PORC", 0.04)
MIN_SIGNAL_SCORE = _env_float("MIN_SIGNAL_SCORE", 70.0)
MIN_24H_QUOTE_VOLUME = _env_float("MIN_24H_QUOTE_VOLUME", 1_000_000.0)
MIN_USDT_ORDER = _env_float("MIN_USDT_ORDER", 5.0)
DEFAULT_SYMBOLS = [symbol.upper() for symbol in _env_list("DEFAULT_SYMBOLS")]
MAX_SYMBOLS_TO_SCAN = _env_int("MAX_SYMBOLS_TO_SCAN", 8)
SCAN_INTERVAL_SECONDS = _env_int("SCAN_INTERVAL_SECONDS", 30)
SYMBOL_REFRESH_SECONDS = _env_int("SYMBOL_REFRESH_SECONDS", 300)
CANDLE_LIMIT = _env_int("CANDLE_LIMIT", 120)
DRY_RUN = _env_bool("DRY_RUN", False)
ENABLE_TRADING_ENGINE = _env_bool("ENABLE_TRADING_ENGINE", True)
ENABLE_SCHEDULER = _env_bool("ENABLE_SCHEDULER", False)

# CoinW Spot documenta 5m, 15m y 2h/4h; 1h no aparece en la lista oficial.
TREND_PERIOD_SECONDS = _env_int("TREND_PERIOD_SECONDS", 7200)
PULLBACK_PERIOD_SECONDS = _env_int("PULLBACK_PERIOD_SECONDS", 900)
ENTRY_PERIOD_SECONDS = _env_int("ENTRY_PERIOD_SECONDS", 300)

# =========================
# Estrategia
# =========================
EMA_FAST = _env_int("EMA_FAST", 20)
EMA_SLOW = _env_int("EMA_SLOW", 50)
RSI_PERIOD = _env_int("RSI_PERIOD", 14)
RSI_TREND_MIN = _env_int("RSI_TREND_MIN", 52)
RSI_PULLBACK_MIN = _env_int("RSI_PULLBACK_MIN", 45)
RSI_PULLBACK_MAX = _env_int("RSI_PULLBACK_MAX", 58)
MAX_SCORE = _env_int("MAX_SCORE", 100)
RECENT_SWING_LOOKBACK = _env_int("RECENT_SWING_LOOKBACK", 8)
DYNAMIC_TP_ACTIVATION_R = _env_float("DYNAMIC_TP_ACTIVATION_R", 1.0)
WEAKNESS_CONFIRMATIONS_REQUIRED = _env_int("WEAKNESS_CONFIRMATIONS_REQUIRED", 2)
WEAKNESS_MIN_SCORE = _env_int("WEAKNESS_MIN_SCORE", 3)
MANAGER_REPLAY_MAX_CANDLES = _env_int("MANAGER_REPLAY_MAX_CANDLES", 500)
ATR_PERIOD = _env_int("ATR_PERIOD", 14)
MIN_ATR_PCT = _env_float("MIN_ATR_PCT", 0.0025)
MAX_ATR_PCT = _env_float("MAX_ATR_PCT", 0.05)
TREND_EMA_FAST_SLOPE_MIN = _env_float("TREND_EMA_FAST_SLOPE_MIN", 0.002)
TREND_EMA_SLOW_SLOPE_MIN = _env_float("TREND_EMA_SLOW_SLOPE_MIN", 0.001)
PULLBACK_LOOKBACK = _env_int("PULLBACK_LOOKBACK", 12)
PULLBACK_MIN_DEPTH_PCT = _env_float("PULLBACK_MIN_DEPTH_PCT", 0.004)
PULLBACK_MAX_DEPTH_PCT = _env_float("PULLBACK_MAX_DEPTH_PCT", 0.03)
ENTRY_MIN_BODY_RATIO = _env_float("ENTRY_MIN_BODY_RATIO", 0.45)
ENTRY_MIN_CLOSE_POSITION = _env_float("ENTRY_MIN_CLOSE_POSITION", 0.65)
ENTRY_MIN_VOLUME_RATIO = _env_float("ENTRY_MIN_VOLUME_RATIO", 1.05)
MAX_STOP_DISTANCE_PCT = _env_float("MAX_STOP_DISTANCE_PCT", 0.03)
BREAK_EVEN_OFFSET_R = _env_float("BREAK_EVEN_OFFSET_R", 0.05)
TRAIL_STOP_ATR_MULTIPLIER = _env_float("TRAIL_STOP_ATR_MULTIPLIER", 0.8)
WEAKNESS_RSI_DELTA = _env_float("WEAKNESS_RSI_DELTA", 3.0)

# =========================
# Administradores
# =========================
ADMIN_TELEGRAM_IDS = [int(item) for item in _env_list("ADMIN_TELEGRAM_IDS")]
ADMIN_COINW_UID = os.getenv("ADMIN_COINW_UID", "").strip()

# =========================
# Fees / pagos manuales internos
# =========================
FEE_ADMIN_PORC = _env_float("FEE_ADMIN_PORC", 0.15)
FEE_REFERIDO_PORC = _env_float("FEE_REFERIDO_PORC", 0.03)
FEE_SETTLEMENT_THRESHOLD = _env_float("FEE_SETTLEMENT_THRESHOLD", 5.0)
PAYMENT_ASSET = os.getenv("PAYMENT_ASSET", "USDT").upper().strip()
PAYMENT_METHOD = os.getenv("PAYMENT_METHOD", "coinw_internal").strip().lower()
HORARIO_COBRO_FEE = os.getenv("HORARIO_COBRO_FEE", "12:00")
HORARIO_PAGO_REFERIDOS = os.getenv("HORARIO_PAGO_REFERIDOS", "14:00")
