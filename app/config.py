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


def _env_int_first(names: List[str], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return int(value)
    return default


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
APP_SERVICE = os.getenv("APP_SERVICE", "").strip().lower()
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENABLE_TELEGRAM_BOT = _env_bool("ENABLE_TELEGRAM_BOT", True)
ENABLE_API_SERVER = _env_bool("ENABLE_API_SERVER", True)
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()
API_HOST = os.getenv("API_HOST", "0.0.0.0").strip()
API_PORT = _env_int_first(["API_PORT", "PORT"], 8000)
API_PREFIX = os.getenv("API_PREFIX", "/api/v1").strip() or "/api/v1"
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS = _env_int("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", 3600)
MINI_APP_SESSION_TTL_SECONDS = _env_int("MINI_APP_SESSION_TTL_SECONDS", 43200)
MINI_APP_SESSION_SECRET = os.getenv("MINI_APP_SESSION_SECRET", "").strip()

# =========================
# CoinW / Trading
# =========================
COINW_BASE_URL = os.getenv("COINW_BASE_URL", "https://api.coinw.com")
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT").upper()
# Producción: usar prácticamente todo el saldo útil dejando un pequeño colchón.
CAPITAL_ACTIVO_PORC = min(max(_env_float("CAPITAL_ACTIVO_PORC", 0.995), 0.0), 1.0)
STOP_LOSS_PORC = _env_float("STOP_LOSS_PORC", 0.02)
TAKE_PROFIT_PORC = _env_float("TAKE_PROFIT_PORC", 0.04)
MIN_SIGNAL_SCORE = _env_float("MIN_SIGNAL_SCORE", 55.0)
MIN_24H_QUOTE_VOLUME = _env_float("MIN_24H_QUOTE_VOLUME", 1_000_000.0)
MIN_USDT_ORDER = _env_float("MIN_USDT_ORDER", 3.0)
DEFAULT_SYMBOLS = [symbol.upper() for symbol in _env_list("DEFAULT_SYMBOLS")]
MAX_SYMBOLS_TO_SCAN = _env_int("MAX_SYMBOLS_TO_SCAN", 40)
PARALLEL_SCAN_WORKERS = _env_int("PARALLEL_SCAN_WORKERS", 4)
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
RSI_TREND_MIN = _env_int("RSI_TREND_MIN", 50)
RSI_PULLBACK_MIN = _env_int("RSI_PULLBACK_MIN", 42)
RSI_PULLBACK_MAX = _env_int("RSI_PULLBACK_MAX", 64)
MAX_SCORE = _env_int("MAX_SCORE", 100)
RECENT_SWING_LOOKBACK = _env_int("RECENT_SWING_LOOKBACK", 8)
DYNAMIC_TP_ACTIVATION_R = _env_float("DYNAMIC_TP_ACTIVATION_R", 1.0)
WEAKNESS_CONFIRMATIONS_REQUIRED = _env_int("WEAKNESS_CONFIRMATIONS_REQUIRED", 2)
WEAKNESS_MIN_SCORE = _env_int("WEAKNESS_MIN_SCORE", 3)
MANAGER_REPLAY_MAX_CANDLES = _env_int("MANAGER_REPLAY_MAX_CANDLES", 500)
ATR_PERIOD = _env_int("ATR_PERIOD", 14)
MIN_ATR_PCT = _env_float("MIN_ATR_PCT", 0.0025)
MAX_ATR_PCT = _env_float("MAX_ATR_PCT", 0.05)
TREND_EMA_FAST_SLOPE_MIN = _env_float("TREND_EMA_FAST_SLOPE_MIN", 0.0008)
TREND_EMA_SLOW_SLOPE_MIN = _env_float("TREND_EMA_SLOW_SLOPE_MIN", 0.0003)
PULLBACK_LOOKBACK = _env_int("PULLBACK_LOOKBACK", 12)
PULLBACK_MIN_DEPTH_PCT = _env_float("PULLBACK_MIN_DEPTH_PCT", 0.002)
PULLBACK_MAX_DEPTH_PCT = _env_float("PULLBACK_MAX_DEPTH_PCT", 0.04)
ENTRY_MIN_BODY_RATIO = _env_float("ENTRY_MIN_BODY_RATIO", 0.32)
ENTRY_MIN_CLOSE_POSITION = _env_float("ENTRY_MIN_CLOSE_POSITION", 0.55)
ENTRY_MIN_VOLUME_RATIO = _env_float("ENTRY_MIN_VOLUME_RATIO", 0.9)
MAX_STOP_DISTANCE_PCT = _env_float("MAX_STOP_DISTANCE_PCT", 0.03)
BREAK_EVEN_OFFSET_R = _env_float("BREAK_EVEN_OFFSET_R", 0.05)
TRAIL_STOP_ATR_MULTIPLIER = _env_float("TRAIL_STOP_ATR_MULTIPLIER", 0.8)
WEAKNESS_RSI_DELTA = _env_float("WEAKNESS_RSI_DELTA", 3.0)
TP1_PARTIAL_MIN_QUOTE = _env_float("TP1_PARTIAL_MIN_QUOTE", 20.0)
TP1_PARTIAL_FRACTION = min(max(_env_float("TP1_PARTIAL_FRACTION", 0.30), 0.0), 0.95)

# =========================
# Filtro de régimen de mercado
# =========================
ENABLE_MARKET_REGIME_FILTER = _env_bool("ENABLE_MARKET_REGIME_FILTER", True)
REGIME_BTC_SYMBOL = os.getenv("REGIME_BTC_SYMBOL", f"BTC_{QUOTE_ASSET}").upper().strip() or f"BTC_{QUOTE_ASSET}"
REGIME_STALE_DECISION_MAX_SECONDS = max(_env_int("REGIME_STALE_DECISION_MAX_SECONDS", 900), 0)
REGIME_BREADTH_SAMPLE_SIZE = _env_int("REGIME_BREADTH_SAMPLE_SIZE", 12)
REGIME_BREADTH_CONTINUATION_MIN = min(max(_env_float("REGIME_BREADTH_CONTINUATION_MIN", 0.55), 0.0), 1.0)
REGIME_BREADTH_WARNING_MIN = min(max(_env_float("REGIME_BREADTH_WARNING_MIN", 0.35), 0.0), 1.0)
REGIME_BREADTH_RISK_OFF_MAX = min(max(_env_float("REGIME_BREADTH_RISK_OFF_MAX", 0.30), 0.0), 1.0)
REGIME_BTC_LAST_CANDLE_DROP_PCT = abs(_env_float("REGIME_BTC_LAST_CANDLE_DROP_PCT", 0.025))
REGIME_BTC_LAST_CANDLE_RISK_OFF_PCT = abs(_env_float("REGIME_BTC_LAST_CANDLE_RISK_OFF_PCT", 0.035))
REGIME_BTC_ATR_SPIKE_MULTIPLIER = max(_env_float("REGIME_BTC_ATR_SPIKE_MULTIPLIER", 1.8), 1.0)
REGIME_CONFIRM_CONTINUATION_CYCLES = max(_env_int("REGIME_CONFIRM_CONTINUATION_CYCLES", 2), 1)
REGIME_CONFIRM_EXIT_CYCLES = max(_env_int("REGIME_CONFIRM_EXIT_CYCLES", 2), 1)
REGIME_COOLDOWN_CYCLES_AFTER_EXIT = max(_env_int("REGIME_COOLDOWN_CYCLES_AFTER_EXIT", 2), 0)

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
REFERRAL_PAYOUT_MIN_USDT = _env_float("REFERRAL_PAYOUT_MIN_USDT", 3.0)
REFERRAL_PAYOUT_COOLDOWN_HOURS = _env_int("REFERRAL_PAYOUT_COOLDOWN_HOURS", 24)
