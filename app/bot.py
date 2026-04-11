import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.admin_panel import AdminPanel
from app.botones import BOTONES_CONFIGURACION, BOTONES_PRINCIPAL
from app.config import ADMIN_TELEGRAM_IDS, CAPITAL_ACTIVO_PORC, QUOTE_ASSET, TELEGRAM_BOT_TOKEN
from app.exchange import CoinWApiError, ExchangeClient
from app.fee_manager import FeeManager
from app.mensajes import mensaje_capital, mensaje_configuracion, mensaje_fee, mensaje_historial, mensaje_referidos
from app.models import OperacionModel, UsuarioModel
from app.usuario import Usuario


logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Debe configurar la variable de entorno TELEGRAM_BOT_TOKEN con el token real del bot")


def _normalize_api_credential(value: str) -> str:
    """Limpia credenciales pegadas desde móvil/portapapeles."""
    if value is None:
        return ""
    cleaned = str(value).strip()
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip("`\"' ")



def _format_decimal(value: float) -> str:
    return f"{float(value):.8f}"


class Bot:
    def __init__(self):
        self.app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        self.admin_panel = AdminPanel()
        self.fee_manager = FeeManager()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.boton_click))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.manejar_mensajes))
        self.app.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        usuario_id = update.effective_user.id
        nombre_usuario = update.effective_user.first_name or "usuario"
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": usuario_id})

        if not usuario_data:
            UsuarioModel.crear_usuario(
                {
                    "telegram_id": usuario_id,
                    "nombre": nombre_usuario,
                    "codigo_referido": str(usuario_id),
                }
            )
            mensaje_bienvenida = (
                f"¡Hola {nombre_usuario}! 🤖\n"
                "Este bot opera CoinW Spot de forma automática cuando activas el motor y configuras tus credenciales API."
            )
        else:
            mensaje_bienvenida = f"¡Hola nuevamente {nombre_usuario}! 🤖"
            if usuario_data.get("trading_pause_reason") == "fee_due":
                mensaje_bienvenida += "\n⛔ Tienes el trading pausado por fee pendiente. Revisa el botón 💸 Fee."

        reply_markup = self._menu_for(usuario_id)
        await update.message.reply_text(mensaje_bienvenida, reply_markup=reply_markup)

    def _navigation_keyboard(self, back_callback: str, include_home: bool = True) -> InlineKeyboardMarkup:
        keyboard = [[InlineKeyboardButton("🔙 Volver atrás", callback_data=back_callback)]]
        if include_home:
            keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="NAV_MAIN")])
        return InlineKeyboardMarkup(keyboard)

    def _append_navigation(self, keyboard_rows, back_callback: str, include_home: bool = True) -> InlineKeyboardMarkup:
        rows = [list(row) for row in keyboard_rows]
        rows.append([InlineKeyboardButton("🔙 Volver atrás", callback_data=back_callback)])
        if include_home:
            rows.append([InlineKeyboardButton("🏠 Menú principal", callback_data="NAV_MAIN")])
        return InlineKeyboardMarkup(rows)

    def menu_principal(self):
        teclado = [[InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila] for fila in BOTONES_PRINCIPAL]
        return InlineKeyboardMarkup(teclado)

    def menu_configuracion(self):
        teclado = [[InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila] for fila in BOTONES_CONFIGURACION]
        return self._append_navigation(teclado, "NAV_MAIN")

    def menu_principal_admin(self):
        teclado = [[InlineKeyboardButton(text=btn, callback_data=btn) for btn in fila] for fila in BOTONES_PRINCIPAL]
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

    async def boton_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        telegram_id = query.from_user.id
        await query.answer()

        if telegram_id in ADMIN_TELEGRAM_IDS:
            handled = await self.admin_panel.manejar_click(update, context)
            if handled:
                return

        if query.data == "NAV_MAIN":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None, "api_key_temp": None})
            await query.edit_message_text(
                "Menú principal:",
                reply_markup=self._menu_for(telegram_id),
            )
            return

        if query.data == "NAV_CONFIG":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None, "api_key_temp": None})
            await query.edit_message_text(
                mensaje_configuracion(),
                reply_markup=self.menu_configuracion(),
            )
            return

        if query.data == "NAV_FEE":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            usuario_nav = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {}
            invoice_nav = self.fee_manager.obtener_factura_usuario(telegram_id)
            await query.edit_message_text(
                mensaje_fee(usuario_nav, invoice_nav),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        if query.data == "NAV_REFERIDOS":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            usuario_nav = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {}
            await query.edit_message_text(
                mensaje_referidos(usuario_nav),
                reply_markup=self._navigation_keyboard("NAV_MAIN"),
            )
            return

        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if not usuario:
            await query.edit_message_text("Usuario no encontrado. Usa /start para inicializar el bot.")
            return

        if query.data == "🟢 Activar Bot":
            if not usuario.get("api_key") or not usuario.get("api_secret"):
                await query.edit_message_text(
                    "Antes de activar el bot debes configurar API Key y API Secret de CoinW Spot.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return

            balance_line = ""
            try:
                client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
                capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
                capital_total = float(capital["capital_total_estimated"])
                available_quote = float(capital["quote_available"])
                capital_activo = capital_total * CAPITAL_ACTIVO_PORC
                UsuarioModel.actualizar_capital_snapshot(telegram_id, capital_total, capital_activo)
                balance_line = (
                    f"\nCapital estimado detectado: {_format_decimal(capital_total)} {QUOTE_ASSET}"
                    f"\nDisponible en {QUOTE_ASSET}: {_format_decimal(available_quote)} {QUOTE_ASSET}"
                )
                logger.info(
                    "USUARIO_ACTIVADO | telegram_id=%s | quote_asset=%s | capital_estimado=%s | quote_disponible=%s | fee_due_total=%s | trading_pause_reason=%s",
                    telegram_id,
                    QUOTE_ASSET,
                    _format_decimal(capital_total),
                    _format_decimal(available_quote),
                    _format_decimal(float(usuario.get("fee_due_total") or 0.0)),
                    usuario.get("trading_pause_reason") or "none",
                )
            except CoinWApiError as exc:
                logger.warning(
                    "USUARIO_ACTIVADO_SIN_SNAPSHOT | telegram_id=%s | motivo=%s",
                    telegram_id,
                    exc,
                )
            except Exception:
                logger.exception("No se pudo obtener snapshot de capital al activar usuario %s", telegram_id)

            UsuarioModel.set_bot_activo(telegram_id, True)
            if usuario.get("trading_pause_reason") == "fee_due":
                invoice = self.fee_manager.obtener_factura_usuario(telegram_id)
                texto = "Bot activado ✅ pero el trading sigue bloqueado por fee pendiente.\n\n" + mensaje_fee(usuario, invoice) + balance_line
            else:
                texto = "Bot activado ✅\nEl motor ya puede abrir operaciones Spot reales." + balance_line
            await query.edit_message_text(texto, reply_markup=self._menu_for(telegram_id))
            return

        if query.data == "🔴 Detener Bot":
            UsuarioModel.set_bot_activo(telegram_id, False)
            await query.edit_message_text("Bot detenido ⏹️\nNo se abrirán nuevas operaciones.", reply_markup=self._menu_for(telegram_id))
            return

        if query.data == "💰 Capital":
            usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            if usuario.get("api_key") and usuario.get("api_secret"):
                try:
                    client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
                    capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
                    capital_total = float(capital["capital_total_estimated"])
                    capital_activo = capital_total * CAPITAL_ACTIVO_PORC
                    UsuarioModel.actualizar_capital_snapshot(telegram_id, capital_total, capital_activo)
                    usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or usuario
                except Exception as exc:
                    logger.warning("No se pudo refrescar el capital en vivo del usuario %s: %s", telegram_id, exc)
            await query.edit_message_text(mensaje_capital(usuario), reply_markup=self._navigation_keyboard("NAV_MAIN"))
            return

        if query.data == "📊 Historial":
            operaciones = OperacionModel.obtener_operaciones({"telegram_id": telegram_id}, limit=10)
            await query.edit_message_text(mensaje_historial(operaciones), reply_markup=self._navigation_keyboard("NAV_MAIN"))
            return

        if query.data == "🔗 Referidos":
            await query.edit_message_text(mensaje_referidos(usuario), reply_markup=self._navigation_keyboard("NAV_MAIN"))
            return

        if query.data == "💳 Introducir API Key":
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_api_key"})
            await query.edit_message_text("Por favor, introduce tu API Key de CoinW:", reply_markup=self._navigation_keyboard("NAV_CONFIG"))
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
            usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
            invoice = self.fee_manager.obtener_factura_usuario(telegram_id)
            await query.edit_message_text(mensaje_fee(usuario, invoice), reply_markup=self._navigation_keyboard("NAV_MAIN"))
            return

        if query.data == "✅ Ya pagué fee":
            invoice = self.fee_manager.obtener_factura_usuario(telegram_id)
            if not invoice:
                await query.edit_message_text(
                    "No tienes una factura activa para reportar en este momento.",
                    reply_markup=self._navigation_keyboard("NAV_FEE"),
                )
                return
            UsuarioModel.actualizar_usuario(
                {"telegram_id": telegram_id},
                {"estado": "esperando_reporte_fee"},
            )
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
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})

        if not usuario or not usuario.get("estado"):
            return

        logger.info("Mensaje de estado recibido telegram_id=%s estado=%s", telegram_id, usuario.get("estado"))

        if usuario["estado"] == "esperando_api_key":
            api_key = _normalize_api_credential(texto)
            UsuarioModel.actualizar_usuario(
                {"telegram_id": telegram_id},
                {"api_key_temp": api_key, "estado": "esperando_api_secret"},
            )
            await update.message.reply_text("Ahora introduce tu API Secret de CoinW:", reply_markup=self._navigation_keyboard("NAV_CONFIG"))
            return

        if usuario["estado"] == "esperando_api_secret":
            api_key = _normalize_api_credential(usuario.get("api_key_temp") or "")
            api_secret = _normalize_api_credential(texto)
            exito, error_msg = Usuario.validar_api(api_key, api_secret, return_error=True)
            if exito:
                UsuarioModel.actualizar_usuario(
                    {"telegram_id": telegram_id},
                    {
                        "api_key": api_key,
                        "api_secret": api_secret,
                        "estado": None,
                        "api_key_temp": None,
                    },
                )
                await update.message.reply_text(
                    "API Key y API Secret validadas correctamente ✅\nYa puedes activar el bot.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
            else:
                UsuarioModel.actualizar_usuario(
                    {"telegram_id": telegram_id},
                    {"estado": "esperando_api_key", "api_key_temp": None},
                )
                await update.message.reply_text(
                    f"No se pudo validar la API ❌\nMotivo: {error_msg}\nIntenta de nuevo. Introduce tu API Key:",
                    reply_markup=self._navigation_keyboard("NAV_CONFIG"),
                )
            return

        if usuario["estado"] == "esperando_reporte_fee":
            invoice = self.fee_manager.reportar_pago(telegram_id, texto)
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            if not invoice:
                await update.message.reply_text(
                    "No encontré una factura activa para reportar. Revisa primero el botón 💸 Fee.",
                    reply_markup=self._navigation_keyboard("NAV_MAIN"),
                )
                return
            await update.message.reply_text(
                (
                    "Pago reportado ✅\n\n"
                    f"Factura: {invoice.get('invoice_id')}\n"
                    "Tu reporte fue enviado al administrador. El trading seguirá pausado hasta confirmación manual."
                ),
                reply_markup=self._navigation_keyboard("NAV_FEE"),
            )



    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.exception("Error no controlado en Telegram bot", exc_info=context.error)

    def start_bot(self):
        logger.info("Iniciando polling de Telegram")
        self.app.run_polling(close_loop=False)
