from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import ADMIN_TELEGRAM_IDS
from app.models import OperacionModel, ReferidoModel, UsuarioModel


class AdminPanel:
    def es_admin(self, telegram_id: int) -> bool:
        return telegram_id in ADMIN_TELEGRAM_IDS

    def menu_administrador(self):
        keyboard = [
            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_usuarios_activos")],
            [InlineKeyboardButton("💰 Capital total usuarios", callback_data="admin_capital_total")],
            [InlineKeyboardButton("📊 Operaciones recientes", callback_data="admin_historial")],
            [InlineKeyboardButton("🔗 Referidos", callback_data="admin_referidos")],
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
                f"💰 Capital total estimado de usuarios: {total_capital:.4f} USDT"
            )
            return True

        if accion == "admin_historial":
            operaciones = OperacionModel.obtener_operaciones({}, limit=10)
            if not operaciones:
                await query.edit_message_text("No hay operaciones registradas aún.")
                return True
            mensaje = "📊 Operaciones recientes:\n\n" + "\n\n".join(
                f"{op.get('telegram_id')} | {op.get('symbol')} | {op.get('status')} | PnL {op.get('pnl_quote', 0):.4f}"
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

        return False
