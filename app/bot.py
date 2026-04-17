import logging
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.admin_panel import AdminPanel
from app.botones import BOTONES_CONFIGURACION, BOTONES_PRINCIPAL
from app.config import ADMIN_TELEGRAM_IDS, MINI_APP_URL, QUOTE_ASSET, TELEGRAM_BOT_TOKEN
from app.mensajes import mensaje_capital, mensaje_configuracion, mensaje_fee, mensaje_historial, mensaje_referidos
from app.services.user_trading_service import BotActivationResult, UserTradingService


logger = logging.getLogger(__name__)


class Bot:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN no está configurado. "
                "Define el token o desactiva ENABLE_TELEGRAM_BOT para ejecutar solo backend/Mini App."
            )

        self.app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        self.admin_panel = AdminPanel()
        self.user_service = UserTradingService()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.manejar_mensajes))
        self.app.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        usuario_id = update.effective_user.id
        nombre_usuario = update.effective_user.first_name or "usuario"
        referral_code = context.args[0] if context.args else None
        session = self.user_service.get_or_create_user(usuario_id, nombre_usuario, referral_code=referral_code)
        usuario_data = session.user

        if session.created:
            mensaje_bienvenida = (
                f"¡Hola {nombre_usuario}! 🤖\n"
                "Este bot opera CoinW Spot de forma automática y ya queda preparado para migrar la operativa hacia la Mini App."
            )
            if session.referral_linked:
                mensaje_bienvenida += "\n🔗 Referido vinculado correctamente."
        else:
            mensaje_bienvenida = f"¡Hola nuevamente {nombre_usuario}! 🤖"
            if usuario_data.get("trading_pause_reason") == "fee_due":
                mensaje_bienvenida += "\n⛔ Tienes el trading pausado por fee pendiente. Revisa el botón 💸 Fee."

        reply_markup = self._menu_for(usuario_id)
        await update.message.reply_text(mensaje_bienvenida, reply_markup=reply_markup)

    def _mini_app_rows(self) -> List[List[InlineKeyboardButton]]:
        if not MINI_APP_URL:
            return []
        return [[InlineKeyboardButton("🚀 Abrir Mini App", web_app=WebAppInfo(url=MINI_APP_URL))]]

    def _navigation_keyboard(self, back_callback: str, include_home: bool = True) -> InlineKeyboardMarkup:
        keyboard = self._mini_app_rows()
        keyboard.append([InlineKeyboardButton("🔙 Volver atrás", callback_data=back_callback)])
        if include_home:
            keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="NAV_MAIN")])
        return InlineKeyboardMarkup(keyboard)

    def _append_navigation(self, keyboard_rows, back_callback: str, include_home: bool = True) -> InlineKeyboardMarkup:
        rows = self._mini_app_rows() + [list(row) for row in keyboard_rows]
        rows.append([InlineKeyboardButton("🔙 Volver atrás", callback_data=back_callback)])
        if include_home:
            rows.append([InlineKeyboardButton("🏠 Menú principal", callback_data="NAV_MAIN")])
        return InlineKeyboardMarkup(rows)

    def menu_principal(self):
        teclado = self._mini_app_rows() + [
            [InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila]
            for fila in BOTONES_PRINCIPAL
        ]
        return InlineKeyboardMarkup(teclado)

    def menu_configuracion(self):
        teclado = [[InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila] for fila in BOTONES_CONFIGURACION]
        return self._append_navigation(teclado, "NAV_MAIN")

    def menu_principal_admin(self):
        teclado = self._mini_app_rows() + [
            [InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila]
            for fila in BOTONES_PRINCIPAL
        ]
        admin_buttons = [
            ("👥 Usuarios activos", "admin_usuarios_activos"),
            ("💰 Capital total usuarios", "admin_capital_total"),
            ("📊 Operaciones recientes", "admin_historial"),
            ("🔗 Referidos", "admin_referidos"),
            ("🧾 Fees pendientes", "admin_fee_pendientes"),
            ("⛔ Usuarios bloqueados", "admin_usuarios_bloqueados"),
        ]
        for text_btn, callback in admin_buttons:
            teclado.append([InlineKeyboardButton(text=text_btn, callback_data=callback)])
        return InlineKeyboardMarkup(teclado)

    def _menu_for(self, telegram_id: int):
        return self.menu_principal_admin() if telegram_id in ADMIN_TELEGRAM_IDS else self.menu_principal()

    @staticmethod
    def _activation_balance_suffix(result: BotActivationResult) -> str:
        if result.capital_total <= 0 and result.available_quote <= 0:
            return ""
        return (
            f"\nCapital estimado detectado: {UserTradingService.format_decimal(result.capital_total)} {QUOTE_ASSET}"
            f"\nDisponible en {QUOTE_ASSET}: {UserTradingService.format_decimal(result.available_quote)} {QUOTE_ASSET}"
        )

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        telegram_id = query.from_user.id
        await query.answer()

        if telegram_id in ADMIN_TELEGRAM_IDS:
            handled = await self.admin_panel.manejar_click(update, context)
            if handled:
                return

        if query.data == "NAV_MAIN":
            self.user_service.reset_navigation_state(telegram_id, clear_temp_api=True)
            await query.edit_message_text(
                "Menú principal:",
                reply_markup=self._menu_for(telegram_id),
            )
            return

        if query.data == "NAV_CONFIG":
            self.user_service.reset_navigation_state(telegram_id, clear_temp_api=True)
            await query.edit_message_text(
                mensaje_configuracion(),
                reply_markup=self.menu_configuracion(),
            )
            return

        if query.data == "NAV_FEE":
            self.user_service.reset_navigation_state(telegram_id)
            usuario_nav = self.user_service.get_user(telegram_id) or {}
            invoice_nav = self.user_service.get_fee_invoice(telegram_id)
            await query.edit_message_text(
                mensaje_fee(usuario_nav, invoice_nav),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "NAV_REFERIDOS":
            self.user_service.reset_navigation_state(telegram_id)
            usuario_nav = self.user_service.get_user(telegram_id) or {}
            await query.edit_message_text(
                mensaje_referidos(usuario_nav),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        usuario = self.user_service.get_user(telegram_id)
        if not usuario:
            await query.edit_message_text("Usuario no encontrado. Usa /start para inicializar el bot.")
            return

        if query.data == "🟢 Activar Bot":
            result = self.user_service.activate_bot(telegram_id)
            if result.status == "missing_credentials":
                await query.edit_message_text(
                    "Antes de activar el bot debes configurar API Key y API Secret de CoinW Spot.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return
            if result.status == "empty_spot_balance":
                await query.edit_message_text(
                    "No pude activar el bot porque CoinW devolvió la cuenta Spot vacía para esa API.\n\n"
                    "Revisa en CoinW estas 3 cosas:\n"
                    "1) que el dinero esté en Spot Trading y no en Buy Crypto/Funding,\n"
                    "2) que esa API pertenezca a la misma cuenta donde ves el saldo,\n"
                    "3) que la API tenga acceso Spot.\n\n"
                    f"Detalles del bot: capital estimado detectado = 0 {QUOTE_ASSET}.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return
            if result.status == "user_not_found":
                await query.edit_message_text(
                    "Usuario no encontrado. Usa /start para inicializar el bot.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return

            balance_line = self._activation_balance_suffix(result)
            if result.user and result.user.get("trading_pause_reason") == "fee_due":
                texto = (
                    "Bot activado ✅ pero el trading sigue bloqueado por fee pendiente.\n\n"
                    + mensaje_fee(result.user, result.invoice)
                    + balance_line
                )
            else:
                texto = "Bot activado ✅\nEl motor ya puede abrir operaciones Spot reales." + balance_line
            await query.edit_message_text(texto, reply_markup=self._menu_for(telegram_id))
            return

        if query.data == "🔴 Detener Bot":
            self.user_service.deactivate_bot(telegram_id)
            await query.edit_message_text(
                "Bot detenido ⏹️\nNo se abrirán nuevas operaciones.",
                reply_markup=self._menu_for(telegram_id),
            )
            return

        if query.data == "💰 Capital":
            capital_result = self.user_service.refresh_capital(telegram_id)
            if capital_result.status == "empty_spot_balance":
                await query.edit_message_text(
                    "CoinW devolvió los balances Spot vacíos para esa API.\n\n"
                    "Eso significa que el bot no está viendo fondos en la cuenta Spot consultada por la API.\n"
                    "Revisa en CoinW que el dinero esté en Spot Trading y que la API pertenezca a esa misma cuenta.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return
            usuario_capital = capital_result.user or usuario
            await query.edit_message_text(
                mensaje_capital(usuario_capital),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "📊 Historial":
            operaciones = self.user_service.get_recent_operations(telegram_id, limit=10)
            await query.edit_message_text(
                mensaje_historial(operaciones),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "🔗 Referidos":
            await query.edit_message_text(
                mensaje_referidos(usuario),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "💳 Introducir API Key":
            self.user_service.begin_api_key_capture(telegram_id)
            await query.edit_message_text(
                "Por favor, introduce tu API Key de CoinW:",
                reply_markup=self._navigation_keyboard("NAV_CONFIG"),
            )
            return

        if query.data == "🔔 Notificaciones":
            await query.edit_message_text(
                "Las notificaciones operativas ya están habilitadas para aperturas y cierres de operaciones.",
                reply_markup=self._navigation_keyboard("NAV_CONFIG"),
            )
            return

        if query.data == "⚙️ Configuración":
            await query.edit_message_text(mensaje_configuracion(), reply_markup=self.menu_configuracion())
            return

        if query.data == "💸 Fee":
            usuario_fee = self.user_service.get_user(telegram_id) or usuario
            invoice = self.user_service.get_fee_invoice(telegram_id)
            await query.edit_message_text(
                mensaje_fee(usuario_fee, invoice),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "✅ Ya pagué fee":
            invoice = self.user_service.begin_fee_report(telegram_id)
            if not invoice:
                await query.edit_message_text(
                    "No tienes una factura activa para reportar en este momento.",
                    reply_markup=self._navigation_keyboard("NAV_FEE"),
                )
                return
            await query.edit_message_text(
                (
                    "Escribe un solo mensaje con los detalles del pago reportado.\n\n"
                    "Ejemplo:\n"
                    "Monto: 5 USDT\n"
                    "Hora aproximada: 10:35\n"
                    "Nota: transferencia interna CoinW realizada\n"
                    f"Factura: {invoice.get('invoice_id')}"
                ),
                reply_markup=self._navigation_keyboard("NAV_FEE"),
            )
            return

        await query.edit_message_text(
            "Opción no reconocida ❌",
            reply_markup=self._navigation_keyboard("NAV_MAIN"),
        )

    async def manejar_mensajes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        texto = (update.message.text or "").strip()
        result = self.user_service.process_stateful_message(telegram_id, texto)

        if result.status == "ignored":
            return

        if result.status == "awaiting_api_secret":
            await update.message.reply_text(
                "Ahora introduce tu API Secret de CoinW:",
                reply_markup=self._navigation_keyboard("NAV_CONFIG"),
            )
            return

        if result.status == "api_validated":
            await update.message.reply_text(
                "API Key y API Secret validadas correctamente ✅\nYa puedes activar el bot.",
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if result.status == "api_invalid":
            await update.message.reply_text(
                f"No se pudo validar la API ❌\nMotivo: {result.reason}\nIntenta de nuevo. Introduce tu API Key:",
                reply_markup=self._navigation_keyboard("NAV_CONFIG"),
            )
            return

        if result.status == "fee_report_missing_invoice":
            await update.message.reply_text(
                "No encontré una factura activa para reportar. Revisa primero el botón 💸 Fee.",
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if result.status == "fee_reported":
            await update.message.reply_text(
                (
                    "Pago reportado ✅\n\n"
                    f"Factura: {result.invoice.get('invoice_id')}\n"
                    "Tu reporte fue enviado al administrador. El trading seguirá pausado hasta confirmación manual."
                ),
                reply_markup=self._navigation_keyboard("NAV_FEE"),
            )
            return

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.exception("Error no controlado en Telegram bot", exc_info=context.error)

    def start_bot(self):
        logger.info("Iniciando polling de Telegram")
        self.app.run_polling(close_loop=False)
