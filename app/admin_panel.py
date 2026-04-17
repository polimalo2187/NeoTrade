from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import ADMIN_TELEGRAM_IDS, PAYMENT_ASSET
from app.fee_manager import FeeManager
from app.models import OperacionModel, PaymentInvoiceModel, ReferidoModel, ReferralPayoutRequestModel, UsuarioModel
from app.services.user_trading_service import UserTradingService


class AdminPanel:
    def __init__(self):
        self.fee_manager = FeeManager()
        self.user_service = UserTradingService()

    def es_admin(self, telegram_id: int) -> bool:
        return telegram_id in ADMIN_TELEGRAM_IDS

    def menu_administrador(self):
        keyboard = [
            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_usuarios_activos")],
            [InlineKeyboardButton("💰 Capital total usuarios", callback_data="admin_capital_total")],
            [InlineKeyboardButton("📊 Operaciones recientes", callback_data="admin_historial")],
            [InlineKeyboardButton("🔗 Referidos", callback_data="admin_referidos")],
            [InlineKeyboardButton("🧾 Fees pendientes", callback_data="admin_fee_pendientes")],
            [InlineKeyboardButton("💸 Payouts referidos", callback_data="admin_referral_payouts")],
            [InlineKeyboardButton("⛔ Usuarios bloqueados", callback_data="admin_usuarios_bloqueados")],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _with_navigation(self, keyboard_rows=None, back_callback: str = "NAV_MAIN"):
        rows = [list(row) for row in (keyboard_rows or [])]
        rows.append([InlineKeyboardButton("🔙 Volver atrás", callback_data=back_callback)])
        rows.append([InlineKeyboardButton("🏠 Menú principal", callback_data="NAV_MAIN")])
        return InlineKeyboardMarkup(rows)

    async def manejar_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        telegram_id = query.from_user.id

        if not self.es_admin(telegram_id):
            await query.answer("❌ No tienes permisos de administrador", show_alert=True)
            return True

        accion = query.data
        if accion == "admin_menu":
            await query.edit_message_text(
                "Panel de administración:",
                reply_markup=self._with_navigation(self.menu_administrador().inline_keyboard, back_callback="NAV_MAIN"),
            )
            return True

        if not accion.startswith("admin_"):
            return False

        if accion == "admin_usuarios_activos":
            usuarios = UsuarioModel.obtener_usuarios_activos()
            activos = len(usuarios)
            con_posicion = sum(1 for u in usuarios if u.get("active_position"))
            await query.edit_message_text(
                f"👥 Usuarios activos: {activos}\n📍 Con posición abierta: {con_posicion}",
                reply_markup=self._with_navigation(back_callback="admin_menu"),
            )
            return True

        if accion == "admin_capital_total":
            usuarios = UsuarioModel.obtener_todos_usuarios()
            total_capital = sum(float(u.get("capital_total", 0) or 0) for u in usuarios)
            await query.edit_message_text(
                f"💰 Capital total estimado de usuarios: {total_capital:.4f} {PAYMENT_ASSET}",
                reply_markup=self._with_navigation(back_callback="admin_menu"),
            )
            return True

        if accion == "admin_historial":
            operaciones = OperacionModel.obtener_operaciones({}, limit=10)
            if not operaciones:
                await query.edit_message_text(
                    "No hay operaciones registradas aún.",
                    reply_markup=self._with_navigation(back_callback="admin_menu"),
                )
                return True
            mensaje = "📊 Operaciones recientes:\n\n" + "\n\n".join(
                f"{op.get('telegram_id')} | {op.get('symbol')} | {op.get('status')} | PnL {op.get('pnl_quote', 0):.4f} | Fee {float(op.get('fee_generated', 0) or 0):.4f}"
                for op in operaciones
            )
            await query.edit_message_text(mensaje[:4096], reply_markup=self._with_navigation(back_callback="admin_menu"))
            return True

        if accion == "admin_referidos":
            referidos = ReferidoModel.obtener_referidos({})
            if not referidos:
                await query.edit_message_text(
                    "No hay referidos registrados.",
                    reply_markup=self._with_navigation(back_callback="admin_menu"),
                )
                return True
            mensaje = "🔗 Referidos:\n\n" + "\n".join(
                f"ref {r.get('referidor_id')} -> usr {r.get('referido_id')} | pendiente {float(r.get('total_pendiente', 0) or 0):.4f} | disponible {float(r.get('total_disponible', 0) or 0):.4f}"
                for r in referidos[:20]
            )
            await query.edit_message_text(mensaje[:4096], reply_markup=self._with_navigation(back_callback="admin_menu"))
            return True

        if accion == "admin_fee_pendientes":
            invoices = PaymentInvoiceModel.obtener_facturas({"status": {"$in": ["pending", "reported"]}}, limit=10)
            if not invoices:
                await query.edit_message_text(
                    "No hay facturas de fee pendientes.",
                    reply_markup=self._with_navigation(back_callback="admin_menu"),
                )
                return True
            lines = ["🧾 Fees pendientes:"]
            keyboard = []
            for inv in invoices:
                lines.append(
                    f"\nUsuario {inv.get('telegram_id')} | {inv.get('invoice_id')} | {float(inv.get('invoice_amount', 0) or 0):.2f} {inv.get('asset', PAYMENT_ASSET)} | {inv.get('status')}"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"✅ {inv.get('invoice_id')[-8:]}",
                            callback_data=f"admin_confirm_fee_{inv.get('invoice_id')}",
                        ),
                        InlineKeyboardButton(
                            f"❌ {inv.get('invoice_id')[-8:]}",
                            callback_data=f"admin_reject_fee_{inv.get('invoice_id')}",
                        ),
                    ]
                )
            await query.edit_message_text(
                "\n".join(lines)[:4096],
                reply_markup=self._with_navigation(keyboard, back_callback="admin_menu"),
            )
            return True

        if accion == "admin_referral_payouts":
            requests = ReferralPayoutRequestModel.obtener_requests({"status": {"$in": ["requested", "processing"]}}, limit=10)
            if not requests:
                await query.edit_message_text(
                    "No hay payouts de referidos pendientes.",
                    reply_markup=self._with_navigation(back_callback="admin_menu"),
                )
                return True
            lines = ["💸 Payouts de referidos pendientes:"]
            keyboard = []
            for request in requests:
                lines.append(
                    f"\nUsuario {request.get('referidor_id')} | {request.get('request_id')} | {float(request.get('amount_requested', 0) or 0):.2f} {request.get('asset', PAYMENT_ASSET)} | UID {request.get('coinw_uid') or 'N/A'}"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"✅ {request.get('request_id')[-8:]}",
                            callback_data=f"admin_confirm_refpayout_{request.get('request_id')}",
                        ),
                        InlineKeyboardButton(
                            f"❌ {request.get('request_id')[-8:]}",
                            callback_data=f"admin_reject_refpayout_{request.get('request_id')}",
                        ),
                    ]
                )
            await query.edit_message_text(
                "\n".join(lines)[:4096],
                reply_markup=self._with_navigation(keyboard, back_callback="admin_menu"),
            )
            return True

        if accion == "admin_usuarios_bloqueados":
            usuarios = UsuarioModel.obtener_usuarios_bloqueados_fee()
            if not usuarios:
                await query.edit_message_text(
                    "No hay usuarios bloqueados por fee.",
                    reply_markup=self._with_navigation(back_callback="admin_menu"),
                )
                return True
            mensaje = "⛔ Usuarios bloqueados por fee:\n\n" + "\n".join(
                f"{u.get('telegram_id')} | deuda {float(u.get('fee_due_total', 0) or 0):.2f} {PAYMENT_ASSET} | factura {u.get('pending_fee_invoice_id') or 'N/A'}"
                for u in usuarios[:20]
            )
            await query.edit_message_text(mensaje[:4096], reply_markup=self._with_navigation(back_callback="admin_menu"))
            return True

        if accion.startswith("admin_confirm_fee_"):
            invoice_id = accion.replace("admin_confirm_fee_", "", 1)
            invoice = self.fee_manager.confirmar_pago(invoice_id, telegram_id)
            if not invoice:
                await query.answer("No se pudo confirmar esa factura", show_alert=True)
                return True
            await query.edit_message_text(
                f"✅ Pago confirmado: {invoice_id}",
                reply_markup=self._with_navigation(back_callback="admin_fee_pendientes"),
            )
            return True

        if accion.startswith("admin_reject_fee_"):
            invoice_id = accion.replace("admin_reject_fee_", "", 1)
            invoice = self.fee_manager.rechazar_pago(invoice_id, telegram_id)
            if not invoice:
                await query.answer("No se pudo rechazar esa factura", show_alert=True)
                return True
            await query.edit_message_text(
                f"❌ Pago rechazado: {invoice_id}",
                reply_markup=self._with_navigation(back_callback="admin_fee_pendientes"),
            )
            return True

        if accion.startswith("admin_confirm_refpayout_"):
            request_id = accion.replace("admin_confirm_refpayout_", "", 1)
            result = self.user_service.admin_confirm_referral_payout(request_id, telegram_id)
            if result.status == "request_not_found":
                await query.answer("No se pudo confirmar ese payout", show_alert=True)
                return True
            await query.edit_message_text(
                f"✅ Payout confirmado: {request_id}",
                reply_markup=self._with_navigation(back_callback="admin_referral_payouts"),
            )
            return True

        if accion.startswith("admin_reject_refpayout_"):
            request_id = accion.replace("admin_reject_refpayout_", "", 1)
            result = self.user_service.admin_reject_referral_payout(
                request_id,
                telegram_id,
                "Solicitud rechazada por administración",
            )
            if result.status == "request_not_found":
                await query.answer("No se pudo rechazar ese payout", show_alert=True)
                return True
            await query.edit_message_text(
                f"❌ Payout rechazado: {request_id}",
                reply_markup=self._with_navigation(back_callback="admin_referral_payouts"),
            )
            return True

        return False
