import os

# Porcentaje del capital total del usuario que se utiliza en cada operación
CAPITAL_ACTIVO_PORC = float(os.getenv("CAPITAL_ACTIVO_PORC", 0.3))

# Stop Loss fijo por operación
STOP_LOSS_PORC = float(os.getenv("STOP_LOSS_PORC", 0.03))

# Porcentaje de fee del administrador y referidor
FEE_ADMIN_PORC = float(os.getenv("FEE_ADMIN_PORC", 0.12))
FEE_REFERIDO_PORC = float(os.getenv("FEE_REFERIDO_PORC", 0.03))

# Horarios de cobro y pago (hora de Cuba)
HORARIO_COBRO_FEE = os.getenv("HORARIO_COBRO_FEE", "12:00")
HORARIO_PAGO_REFERIDOS = os.getenv("HORARIO_PAGO_REFERIDOS", "14:00")

# Configuración de la estrategia
EMA_FAST = int(os.getenv("EMA_FAST", 20))
EMA_SLOW = int(os.getenv("EMA_SLOW", 50))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_TREND_MIN = int(os.getenv("RSI_TREND_MIN", 50))
RSI_PULLBACK_MIN = int(os.getenv("RSI_PULLBACK_MIN", 45))
RSI_PULLBACK_MAX = int(os.getenv("RSI_PULLBACK_MAX", 55))

# Score máximo de la estrategia
MAX_SCORE = int(os.getenv("MAX_SCORE", 100))

# Administradores de Telegram (IDs)
ADMIN_TELEGRAM_IDS = list(map(int, os.getenv("ADMIN_TELEGRAM_IDS", "").split(","))) if os.getenv("ADMIN_TELEGRAM_IDS") else []
