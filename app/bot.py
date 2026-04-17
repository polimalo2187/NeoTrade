import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import MINI_APP_URL, TELEGRAM_BOT_TOKEN
from app.services.user_trading_service import UserTradingService


logger = logging.getLogger(__name__)

COINW_REGISTER_URL = "https://www.coinw.com/es_ES/register?r=26534383"


class Bot:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN no está configurado. "
                "Define el token o desactiva ENABLE_TELEGRAM_BOT para ejecutar solo backend/Mini App."
            )

        self.app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        self.user_service = UserTradingService()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.manejar_mensajes))
        self.app.add_error_handler(self.error_handler)

    @staticmethod
    def _gateway_text(nombre_usuario: str | None = None) -> str:
        saludo = f"Hola {nombre_usuario}.\n\n" if nombre_usuario else ""
        return (
            f"{saludo}"
            "🚀 Bienvenido a NeoTrade\n\n"
            "NeoTrade es una plataforma de trading automático en Spot diseñada para operar de forma profesional, "
            "rápida y centralizada desde nuestra Mini App.\n\n"
            "Desde la Mini App podrás:\n"
            "• conectar tu cuenta del exchange\n"
            "• activar o pausar tu bot\n"
            "• supervisar capital, estado operativo y actividad\n"
            "• gestionar referidos, comisiones y más\n\n"
            "⚠️ Importante: para usar NeoTrade es obligatorio registrarte en CoinW, ya que es el exchange donde opera el bot.\n\n"
            f"Registro en CoinW:\n{COINW_REGISTER_URL}\n\n"
            "Cuando ya tengas tu cuenta lista, entra directamente aquí:\n\n"
            "👇 Abre la Mini App y configura tu operativa en Spot"
        )

    def _mini_app_markup(self) -> InlineKeyboardMarkup | None:
        if not MINI_APP_URL:
            return None
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚀 Abrir Mini App", web_app=WebAppInfo(url=MINI_APP_URL))]]
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        usuario_id = update.effective_user.id
        nombre_usuario = update.effective_user.first_name or "usuario"
        referral_code = context.args[0] if context.args else None
        session = self.user_service.get_or_create_user(usuario_id, nombre_usuario, referral_code=referral_code)

        mensaje = self._gateway_text(nombre_usuario)
        if session.created and session.referral_linked:
            mensaje += "\n\n🔗 Referido vinculado correctamente."

        if update.message:
            await update.message.reply_text(mensaje, reply_markup=self._mini_app_markup())

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Usa la Mini App")
        await query.edit_message_text(
            self._gateway_text(),
            reply_markup=self._mini_app_markup(),
        )

    async def manejar_mensajes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            self._gateway_text(update.effective_user.first_name or "usuario"),
            reply_markup=self._mini_app_markup(),
        )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.exception("Error no controlado en Telegram bot", exc_info=context.error)

    def start_bot(self):
        logger.info("Iniciando polling de Telegram")
        self.app.run_polling(close_loop=False)
