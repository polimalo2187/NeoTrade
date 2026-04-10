from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import ADMIN_TELEGRAM_IDS, PAYMENT_ASSET
from app.fee_manager import FeeManager
from app.models import OperacionModel, PaymentInvoiceModel, ReferidoModel, UsuarioModel


class AdminPanel:
    def __init__(self):
        self.fee_manager = FeeManager()

    def es_admin(self, telegram_id: int) -> bool:
        return telegram_id in ADMIN_TELEGRAM_IDS

    def menu_administrador(self):
        keyboard = [
            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_usuarios_activos")],
            [InlineKeyboardButton("💰 Capital total usuarios", callback_data="admin_capital_total")],
            [InlineKeyboardButton("📊 Operaciones recientes", callback_data="admin_historial")],
            [InlineKeyboardButton("🔗 Referidos", callback_data="admin_referidos")],
            [InlineKeyboardButton("🧾 Fees pendientes", callback_data="admin_fee_pendientes")],
            [InlineKeyboardButton("⛔ Usuarios bloqueados", callback_data="admin_usuarios_bloqueados")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def manejar_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        telegram_id = query.from_user.id

        if not self.es_admin(telegram_id):
            await query.answer("❌ No tienes permisos de administrador", show_alert=True)
            return True

        accion = query.data
        if not accion.startswith("admin_"):
            return False

        if accion == "admin_usuarios_activos":
            usuarios = UsuarioModel.obtener_usuarios_activos()
            activos = len(usuarios)
            con_posicion = sum(1 for u in usuarios if u.get("active_position"))
            await query.edit_message_text(
                f"👥 Usuarios activos: {activos}\n📍 Con posición abierta: {con_posicion}"
            )
            return True

        if accion == "admin_capital_total":
            usuarios = UsuarioModel.obtener_todos_usuarios()
            total_capital = sum(float(u.get("capital_total", 0) or 0) for u in usuarios)
            await query.edit_message_text(
                f"💰 Capital total estimado de usuarios: {total_capital:.4f} {PAYMENT_ASSET}"
            )
            return True

        if accion == "admin_historial":
            operaciones = OperacionModel.obtener_operaciones({}, limit=10)
            if not operaciones:
                await query.edit_message_text("No hay operaciones registradas aún.")
                return True
            mensaje = "📊 Operaciones recientes:\n\n" + "\n\n".join(
                f"{op.get('telegram_id')} | {op.get('symbol')} | {op.get('status')} | PnL {op.get('pnl_quote', 0):.4f} | Fee {float(op.get('fee_generated', 0) or 0):.4f}"
                for op in operaciones
            )
            await query.edit_message_text(mensaje[:4096])
            return True

        if accion == "admin_referidos":
            referidos = ReferidoModel.obtener_referidos({})
            if not referidos:
                await query.edit_message_text("No hay referidos registrados.")
                return True
            mensaje = "🔗 Referidos:\n\n" + "\n".join(
                f"ref {r.get('referidor_id')} -> usr {r.get('referido_id')} | comisión {r.get('comision', 0):.4f}"
                for r in referidos[:20]
            )
            await query.edit_message_text(mensaje[:4096])
            return True

        if accion == "admin_fee_pendientes":
            invoices = PaymentInvoiceModel.obtener_facturas({"status": {"$in": ["pending", "reported"]}}, limit=10)
            if not invoices:
                await query.edit_message_text("No hay facturas de fee pendientes.")
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
            await query.edit_message_text("\n".join(lines)[:4096], reply_markup=InlineKeyboardMarkup(keyboard))
            return True

        if accion == "admin_usuarios_bloqueados":
            usuarios = UsuarioModel.obtener_usuarios_bloqueados_fee()
            if not usuarios:
                await query.edit_message_text("No hay usuarios bloqueados por fee.")
                return True
            mensaje = "⛔ Usuarios bloqueados por fee:\n\n" + "\n".join(
                f"{u.get('telegram_id')} | deuda {float(u.get('fee_due_total', 0) or 0):.2f} {PAYMENT_ASSET} | factura {u.get('pending_fee_invoice_id') or 'N/A'}"
                for u in usuarios[:20]
            )
            await query.edit_message_text(mensaje[:4096])
            return True

        if accion.startswith("admin_confirm_fee_"):
            invoice_id = accion.replace("admin_confirm_fee_", "", 1)
            invoice = self.fee_manager.confirmar_pago(invoice_id, telegram_id)
            if not invoice:
                await query.answer("No se pudo confirmar esa factura", show_alert=True)
                return True
            await query.edit_message_text(f"✅ Pago confirmado: {invoice_id}")
            return True

        if accion.startswith("admin_reject_fee_"):
            invoice_id = accion.replace("admin_reject_fee_", "", 1)
            invoice = self.fee_manager.rechazar_pago(invoice_id, telegram_id)
            if not invoice:
                await query.answer("No se pudo rechazar esa factura", show_alert=True)
                return True
            await query.edit_message_text(f"❌ Pago rechazado: {invoice_id}")
            return True

        return False
