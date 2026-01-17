from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.buttons import BOTONES_PRINCIPAL, BOTONES_CONFIGURACION
from telegram.messages import mensaje_capital, mensaje_historial, mensaje_referidos, mensaje_configuracion
from users.user import Usuario
from users.referidos import Referido
from models.models import UsuarioModel, OperacionModel, ReferidoModel

class Bot:
    """
    Bot de Telegram para controlar el trading automático.
    """

    def __init__(self):
        self.app = ApplicationBuilder().token("TU_TELEGRAM_BOT_TOKEN").build()

        # Comandos principales
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Comando /start
        """
        usuario_id = update.effective_user.id
        await update.message.reply_text(
            f"¡Hola {update.effective_user.first_name}! 🤖\nBienvenido al Bot de Trading.",
            reply_markup=self.menu_principal()
        )
        # Registrar usuario en la base de datos si no existe
        if not UsuarioModel.obtener_usuario({"telegram_id": usuario_id}):
            UsuarioModel.crear_usuario({"telegram_id": usuario_id, "capital_total": 0, "capital_activo": 0})

    def menu_principal(self):
        """
        Devuelve el teclado principal con los botones organizados.
        """
        keyboard = []
        for fila in BOTONES_PRINCIPAL:
            keyboard.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        return InlineKeyboardMarkup(keyboard)

    def menu_configuracion(self):
        """
        Devuelve el teclado de configuración.
        """
        keyboard = []
        for fila in BOTONES_CONFIGURACION:
            keyboard.append([InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila])
        return InlineKeyboardMarkup(keyboard)

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja los clicks en los botones del bot.
        """
        query = update.callback_query
        await query.answer()
        usuario_id = query.from_user.id

        if query.data == "🟢 Activar Bot":
            await query.edit_message_text("Bot activado ✅")
            # Lógica para activar bot
        elif query.data == "🔴 Detener Bot":
            await query.edit_message_text("Bot detenido ⏹️")
            # Lógica para detener bot
        elif query.data == "💰 Capital":
            usuario = UsuarioModel.obtener_usuario({"telegram_id": usuario_id})
            await query.edit_message_text(mensaje_capital(usuario))
        elif query.data == "📊 Historial":
            operaciones = OperacionModel.obtener_operaciones({"telegram_id": usuario_id})
            await query.edit_message_text(mensaje_historial(operaciones))
        elif query.data == "🔗 Referidos":
            usuario = UsuarioModel.obtener_usuario({"telegram_id": usuario_id})
            await query.edit_message_text(mensaje_referidos(usuario))
        elif query.data == "⚙️ Configuración":
            await query.edit_message_text(mensaje_configuracion(), reply_markup=self.menu_configuracion())
        else:
            await query.edit_message_text("Opción no reconocida ❌")

    def start(self):
        """
        Inicia el bot de Telegram.
        """
        self.app.run_polling()
