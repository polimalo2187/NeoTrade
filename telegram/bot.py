from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.buttons import BOTONES_PRINCIPAL, BOTONES_CONFIGURACION
from telegram.messages import mensaje_capital, mensaje_historial, mensaje_referidos, mensaje_configuracion
from users.user import Usuario
from users.referidos import Referido
from models.models import UsuarioModel, OperacionModel, ReferidoModel
from telegram.admin_panel import AdminPanel
from config import ADMIN_TELEGRAM_IDS

class Bot:
    """
    Bot de Telegram para controlar el trading automático y panel de administrador.
    """

    def __init__(self):
        self.app = ApplicationBuilder().token("TU_TELEGRAM_BOT_TOKEN").build()
        self.admin_panel = AdminPanel()

        # Comandos principales
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))

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
                "capital_activo": 0
            })

        # Verificar si es administrador
        if usuario_id in ADMIN_TELEGRAM_IDS:
            await update.message.reply_text(
                f"¡Hola {nombre_usuario}! 👑\nBienvenido al Panel de Administrador.",
                reply_markup=self.admin_panel.menu_administrador()
            )
        else:
            await update.message.reply_text(
                f"¡Hola {nombre_usuario}! 🤖\nBienvenido al Bot de Trading.",
                reply_markup=self.menu_principal()
            )

    def menu_principal(self):
        """
        Devuelve el teclado principal de usuario con los botones organizados.
        """
        teclado = []
        for fila in BOTONES_PRINCIPAL:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        return InlineKeyboardMarkup(teclado)

    def menu_configuracion(self):
        """
        Devuelve el teclado de configuración.
        """
        teclado = []
        for fila in BOTONES_CONFIGURACION:
            teclado.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        return InlineKeyboardMarkup(teclado)

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja los clicks en los botones del bot, usuarios o administradores.
        """
        query = update.callback_query
        telegram_id = query.from_user.id
        await query.answer()

        # Administrador
        if telegram_id in ADMIN_TELEGRAM_IDS:
            await self.admin_panel.manejar_click(update, context)
            return

        # Usuario normal
        if query.data == "🟢 Activar Bot":
            usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            if usuario_data:
                usuario_obj = Usuario(telegram_id, usuario_data.get("capital_total",0), usuario_data.get("capital_activo",0))
                usuario_obj.activar_bot()
                usuario_obj.guardar()
            await query.edit_message_text("Bot activado ✅")
        elif query.data == "🔴 Detener Bot":
            usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            if usuario_data:
                usuario_obj = Usuario(telegram_id, usuario_data.get("capital_total",0), usuario_data.get("capital_activo",0))
                usuario_obj.detener_bot()
                usuario_obj.guardar()
            await query.edit_message_text("Bot detenido ⏹️")
        elif query.data == "💰 Capital":
            usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            await query.edit_message_text(mensaje_capital(usuario))
        elif query.data == "📊 Historial":
            operaciones = OperacionModel.obtener_operaciones({"telegram_id": telegram_id})
            await query.edit_message_text(mensaje_historial(operaciones))
        elif query.data == "🔗 Referidos":
            usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            await query.edit_message_text(mensaje_referidos(usuario))
        elif query.data == "⚙️ Configuración":
            await query.edit_message_text(mensaje_configuracion(), reply_markup=self.menu_configuracion())
        else:
            await query.edit_message_text("Opción no reconocida ❌")

    def start_bot(self):
        """
        Inicia el bot de Telegram.
        """
        self.app.run_polling()
