BOTONES_PRINCIPAL = [
    ["🟢 Activar Bot", "🔴 Detener Bot"],
    ["💰 Capital", "📊 Historial"],
    ["🔗 Referidos", "💸 Fee"],
    ["⚙️ Configuración", "✅ Ya pagué fee"],
]

BOTONES_CONFIGURACION = [
    ["💳 Introducir API Key", "🔔 Notificaciones"],
]

BOTONES_REFERIDOS = [
    ["🔗 Mi enlace de referido"],
    ["📈 Ganancias de mis referidos"],
]

BOTONES_ADMIN = [
    ["👥 Usuarios activos"],
    ["💰 Capital total usuarios"],
    ["📊 Operaciones recientes"],
    ["🔗 Referidos"],
    ["🧾 Fees pendientes"],
    ["⛔ Usuarios bloqueados"],
]

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def generar_teclado(botones):
    teclado = []
    for fila in botones:
        teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
    return InlineKeyboardMarkup(teclado)
