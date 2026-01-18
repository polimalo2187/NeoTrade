# Configuraciones globales del bot de trading

# Porcentaje del capital total del usuario que se utiliza en cada operación
CAPITAL_ACTIVO_PORC = 0.3  # 30%

# Stop Loss fijo por operación
STOP_LOSS_PORC = 0.03  # 3%

# Porcentaje de fee del administrador y referidor
FEE_ADMIN_PORC = 0.12      # 12%
FEE_REFERIDO_PORC = 0.03   # 3%

# Horarios de cobro y pago (hora de Cuba)
HORARIO_COBRO_FEE = "12:00"       # Cobro de fee diario a los usuarios
HORARIO_PAGO_REFERIDOS = "14:00"  # Pago de comisión de referidos

# Configuración de la estrategia
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_TREND_MIN = 50
RSI_PULLBACK_MIN = 45
RSI_PULLBACK_MAX = 55

# Score máximo de la estrategia
MAX_SCORE = 100
