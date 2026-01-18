import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.wallet import WalletAdmin
from app.models import UsuarioModel, OperacionModel, ReferidoModel


# ========================================
# IDs de administrador desde variable de entorno
# ========================================
ADMIN_TELEGRAM_IDS = os.environ.get("ADMIN_TELEGRAM_IDS", "")
if ADMIN_TELEGRAM_IDS:
    # Convertimos la cadena "123,456,789" en lista de ints
    ADMIN_TELEGRAM_IDS = [int(x.strip()) for x in ADMIN_TELEGRAM_IDS.split(",")]
else:
    ADMIN_TELEGRAM_IDS = []  # Ningún admin si no está configurado


class AdminPanel:
    """
    Panel de administrador en Telegram, controlado por ID de Telegram.
    """

    def __init__(self):
        self.wallet = WalletAdmin()

    def es_admin(self, telegram_id: int) -> bool:
        """
        Verifica si el usuario es administrador por su ID de Telegram.
        """
        return telegram_id in ADMIN_TELEGRAM_IDS

    def menu_administrador(self):
        """
        Retorna el teclado con opciones de administrador.
        """
        keyboard = [
            [InlineKeyboardButton("🟢 Activar/Detener usuario", callback_data="activar_detener")],
            [InlineKeyboardButton("💰 Capital total de usuarios", callback_data="capital_total")],
            [InlineKeyboardButton("📊 Historial completo", callback_data="historial_completo")],
            [InlineKeyboardButton("🔗 Comisiones de referidos", callback_data="comisiones_referidos")],
            [InlineKeyboardButton("⚙️ Configuración avanzada", callback_data="configuracion_avanzada")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def manejar_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja los clicks del panel de administrador.
        """
        query = update.callback_query
        telegram_id = query.from_user.id

        if not self.es_admin(telegram_id):
            await query.answer("❌ No tienes permisos de administrador", show_alert=True)
            return

        await query.answer()
        accion = query.data

        if accion == "activar_detener":
            await query.edit_message_text(
                "Función de activar/detener usuarios pendiente de implementación"
            )

        elif accion == "capital_total":
            usuarios = UsuarioModel.obtener_todos_usuarios()
            total_capital = sum(u.get("capital_total", 0) for u in usuarios)
            await query.edit_message_text(
                f"💰 Capital total de todos los usuarios: {total_capital:.2f} USDT"
            )

        elif accion == "historial_completo":
            operaciones = OperacionModel.obtener_operaciones({})
            if not operaciones:
                mensaje = "No hay operaciones registradas aún."
            else:
                mensaje = "\n".join(
                    f"{o.get('telegram_id')}: {o.get('ganancia', 0)} USDT"
                    for o in operaciones
                )
            await query.edit_message_text(f"📊 Historial completo:\n{mensaje}")

        elif accion == "comisiones_referidos":
            referidos = ReferidoModel.obtener_referidos({})
            if not referidos:
                mensaje = "No hay comisiones registradas aún."
            else:
                mensaje = "\n".join(
                    f"{r.get('referidor_id')}: {r.get('comision', 0)} USDT"
                    for r in referidos
                )
            await query.edit_message_text(f"🔗 Comisiones de referidos:\n{mensaje}")

        elif accion == "configuracion_avanzada":
            await query.edit_message_text(
                "⚙️ Configuración avanzada pendiente de implementación"
            )

        else:
            await query.edit_message_text("Opción no reconocida ❌")
