# =========================
# Botones del menú principal para usuario normal
# =========================

BOTONES_PRINCIPAL = [
    ["🟢 Activar Bot", "🔴 Detener Bot"],
    ["💰 Capital", "📊 Historial"],
    ["🔗 Referidos", "⚙️ Configuración"]
]

# =========================
# Botones del menú de configuración
# =========================

BOTONES_CONFIGURACION = [
    ["💳 Introducir API Key", "🔔 Notificaciones"],
    ["⚙️ Preferencias"]
]

# =========================
# Botones del menú de referidos
# =========================

BOTONES_REFERIDOS = [
    ["🔗 Mi enlace de referido"],
    ["📈 Ganancias de mis referidos"]
]

# =========================
# Botones del panel de administración
# (solo visible para IDs de administrador)
# =========================

BOTONES_ADMIN = [
    ["🟢 Activar/Detener usuario", "💰 Capital total de usuarios"],
    ["📊 Historial completo", "🔗 Comisiones de referidos"],
    ["⚙️ Configuración avanzada"]
]

# =========================
# Funciones auxiliares para generar teclados dinámicos
# =========================

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def generar_teclado(botones):
    """
    Convierte una lista de listas de botones en InlineKeyboardMarkup.
    """
    teclado = []
    for fila in botones:
        teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
    return InlineKeyboardMarkup(teclado)
