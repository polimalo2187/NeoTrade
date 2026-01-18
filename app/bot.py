# =========================
# Archivo: appbot.py
# Bot de Telegram para controlar trading automático y panel de administrador
# =========================

import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# =========================
# Importes corregidos según estructura real
# =========================
from app.botones import BOTONES_PRINCIPAL, BOTONES_CONFIGURACION
from app.mensajes import mensaje_capital, mensaje_historial, mensaje_referidos, mensaje_configuracion
from app.admin_panel import AdminPanel

from app.usuario import Usuario
from app.referidos import Referido
from app.models import UsuarioModel, OperacionModel, ReferidoModel
from app.config import ADMIN_TELEGRAM_IDS

# =========================
# Token de Telegram desde variable de entorno
# =========================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Debe configurar la variable de entorno TELEGRAM_BOT_TOKEN con el token real del bot")


class Bot:
    """
    Bot de Telegram para controlar el trading automático y panel de administrador.
    Compatible con python-telegram-bot v20.7
    """

    def __init__(self):
        self.app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        self.admin_panel = AdminPanel()

        # Comandos principales
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.manejar_mensajes))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Comando /start
        """
        usuario_id = update.effective_user.id
        nombre_usuario = update.effective_user.first_name

        # Registrar usuario en la base de datos si no existe
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": usuario_id})
        if not usuario_data:
            UsuarioModel.crear_usuario({
                "telegram_id": usuario_id,
                "capital_total": 0,
                "capital_activo": 0,
                "codigo_referido": str(usuario_id),
                "estado": None,
                "api_key_temp": None
            })
            usuario_data = UsuarioModel.obtener_usuario({"telegram_id": usuario_id})

        # Teclado principal del usuario
        teclado_usuario = self.menu_principal()

        # Verificar si es administrador
        if usuario_id in ADMIN_TELEGRAM_IDS:
            # Mostrar panel de usuario + panel admin
            await update.message.reply_text(
                f"¡Hola {nombre_usuario}! 👑\nBienvenido al Bot y Panel de Administrador.",
                reply_markup=self.menu_principal_admin()
            )
        else:
            await update.message.reply_text(
                f"¡Hola {nombre_usuario}! 🤖\nBienvenido al Bot de Trading.",
                reply_markup=teclado_usuario
            )

    # =========================
    # Teclados
    # =========================

    def menu_principal(self):
        teclado = []
        for fila in BOTONES_PRINCIPAL:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        teclado.append([InlineKeyboardButton("🔙 Volver atrás", callback_data="VOLVER_ATRAS")])
        teclado.append([InlineKeyboardButton("🏠 Menú principal", callback_data="VOLVER_MENU")])
        return InlineKeyboardMarkup(teclado)

    def menu_configuracion(self):
        teclado = []
        for fila in BOTONES_CONFIGURACION:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        teclado.append([InlineKeyboardButton("🔙 Volver atrás", callback_data="VOLVER_ATRAS")])
        teclado.append([InlineKeyboardButton("🏠 Menú principal", callback_data="VOLVER_MENU")])
        return InlineKeyboardMarkup(teclado)

    def menu_principal_admin(self):
        teclado = []
        for fila in BOTONES_PRINCIPAL:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        from app.botones import BOTONES_ADMIN
        for fila in BOTONES_ADMIN:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        teclado.append([InlineKeyboardButton("🔙 Volver atrás", callback_data="VOLVER_ATRAS")])
        teclado.append([InlineKeyboardButton("🏠 Menú principal", callback_data="VOLVER_MENU")])
        return InlineKeyboardMarkup(teclado)

    # =========================
    # Clicks en botones
    # =========================

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        telegram_id = query.from_user.id
        await query.answer()

        # Administrador
        if telegram_id in ADMIN_TELEGRAM_IDS:
            handled = await self.admin_panel.manejar_click(update, context)
            if handled:
                return

        # Botones universales
        if query.data == "VOLVER_MENU":
            if telegram_id in ADMIN_TELEGRAM_IDS:
                await query.edit_message_text("Menú principal:", reply_markup=self.menu_principal_admin())
            else:
                await query.edit_message_text("Menú principal:", reply_markup=self.menu_principal())
            # Reset estado
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            return

        if query.data == "VOLVER_ATRAS":
            if telegram_id in ADMIN_TELEGRAM_IDS:
                await query.edit_message_text("Volviendo atrás...", reply_markup=self.menu_principal_admin())
            else:
                await query.edit_message_text("Volviendo atrás...", reply_markup=self.menu_principal())
            # Reset estado
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            return

        # Usuario normal
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})

        if query.data == "🟢 Activar Bot":
            if usuario:
                usuario_obj = Usuario(
                    telegram_id,
                    api_key=usuario.get("api_key"),
                    api_secret=usuario.get("api_secret"),
                    capital_total=usuario.get("capital_total", 0)
                )
                usuario_obj.activar_bot()
            await query.edit_message_text("Bot activado ✅", reply_markup=self.menu_principal())
            return

        elif query.data == "🔴 Detener Bot":
            if usuario:
                usuario_obj = Usuario(
                    telegram_id,
                    api_key=usuario.get("api_key"),
                    api_secret=usuario.get("api_secret"),
                    capital_total=usuario.get("capital_total", 0)
                )
                usuario_obj.detener_bot()
            await query.edit_message_text("Bot detenido ⏹️", reply_markup=self.menu_principal())
            return

        elif query.data == "💰 Capital":
            await query.edit_message_text(mensaje_capital(usuario), reply_markup=self.menu_principal())
            return

        elif query.data == "📊 Historial":
            operaciones = OperacionModel.obtener_operaciones({"telegram_id": telegram_id})
            await query.edit_message_text(mensaje_historial(operaciones), reply_markup=self.menu_principal())
            return

        elif query.data == "🔗 Referidos":
            codigo_referido = usuario.get("codigo_referido", str(telegram_id))
            enlace = f"https://t.me/TradeNeo_bot?start={codigo_referido}"
            mensaje = mensaje_referidos(usuario) + f"\n\nTu enlace de referido: {enlace}"
            await query.edit_message_text(mensaje, reply_markup=self.menu_principal())
            return

        elif query.data == "💳 Introducir API Key":
            # Cambiar estado a esperar API Key
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_api_key"})
            await query.edit_message_text("Por favor, introduzca su API Key:", reply_markup=self.menu_principal())
            return

        elif query.data == "🔔 Notificaciones":
            await query.edit_message_text("Funcionalidad de notificaciones pendiente", reply_markup=self.menu_principal())
            return

        elif query.data == "⚙️ Configuración":
            await query.edit_message_text(mensaje_configuracion(), reply_markup=self.menu_configuracion())
            return

        else:
            await query.edit_message_text(
                "Opción no reconocida ❌",
                reply_markup=self.menu_principal_admin() if telegram_id in ADMIN_TELEGRAM_IDS else self.menu_principal()
            )
            return

    # =========================
    # Manejo de mensajes de usuario (API Key / Secret)
    # =========================

    async def manejar_mensajes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        texto = update.message.text
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})

        if not usuario or "estado" not in usuario or usuario["estado"] is None:
            return  # No estamos esperando nada

        # =========================
        # Esperando API Key
        # =========================
        if usuario["estado"] == "esperando_api_key":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {
                "api_key_temp": texto,
                "estado": "esperando_api_secret"
            })
            await update.message.reply_text(
                "Por favor, introduzca su API Secret:",
                reply_markup=self.menu_principal()
            )
            return

        # =========================
        # Esperando API Secret
        # =========================
        if usuario["estado"] == "esperando_api_secret":
            # Obtener API Key temporal
            api_key = usuario.get("api_key_temp")
            api_secret = texto
            # Validar API Key / Secret usando método de Usuario
            exito = Usuario.validar_api(api_key, api_secret)
            if exito:
                UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "estado": None,
                    "api_key_temp": None
                })
                await update.message.reply_text(
                    "API Key y API Secret configuradas correctamente ✅",
                    reply_markup=self.menu_principal()
                )
            else:
                UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {
                    "estado": "esperando_api_key",
                    "api_key_temp": None
                })
                await update.message.reply_text(
                    "API Key o API Secret inválidas ❌. Intente de nuevo. Introduzca su API Key:",
                    reply_markup=self.menu_principal()
                )
            return

    # =========================
    # Iniciar bot
    # =========================

    def start_bot(self):
        self.app.run_polling()
