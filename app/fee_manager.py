import logging
from datetime import datetime
from typing import Dict, Optional

import requests

from app.config import (
    ADMIN_COINW_UID,
    ADMIN_TELEGRAM_IDS,
    FEE_ADMIN_PORC,
    FEE_SETTLEMENT_THRESHOLD,
    PAYMENT_ASSET,
    PAYMENT_METHOD,
    TELEGRAM_BOT_TOKEN,
)
from app.fee_calculator import FeeCalculator
from app.models import FeeModel, PaymentInvoiceModel, UsuarioModel


logger = logging.getLogger(__name__)


class FeeNotifier:
    def __init__(self, bot_token: Optional[str]):
        self.bot_token = bot_token

    def send(self, chat_id: int, text: str) -> None:
        if not self.bot_token:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception:
            logger.exception("No se pudo enviar mensaje Telegram a %s", chat_id)


class FeeManager:
    def __init__(self):
        self.calculadora = FeeCalculator(fee_admin=FEE_ADMIN_PORC)
        self.notifier = FeeNotifier(TELEGRAM_BOT_TOKEN)

    def calcular_fee_admin(self, ganancia_neta: float) -> float:
        fee = self.calculadora.calcular_fee(ganancia_neta)
        return round(float(fee["admin"]), 8)

    def registrar_fee_operacion(self, usuario: Dict, operacion: Dict) -> float:
        telegram_id = int(usuario["telegram_id"])
        ganancia = max(float(operacion.get("pnl_quote") or 0.0), 0.0)
        if ganancia <= 0:
            OperacionModelSafe.actualizar_con_fee(telegram_id, operacion, 0.0, 0.0, None)
            return 0.0

        fee_generada = self.calcular_fee_admin(ganancia)
        usuario_actual = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or usuario
        credit_balance = float(usuario_actual.get("fee_credit_balance") or 0.0)
        due_total = float(usuario_actual.get("fee_due_total") or 0.0)
        credit_applied = min(credit_balance, fee_generada)
        fee_pendiente = max(fee_generada - credit_applied, 0.0)
        nuevo_credito = max(credit_balance - credit_applied, 0.0)
        nueva_deuda = round(due_total + fee_pendiente, 8)

        UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "fee_due_total": nueva_deuda,
                "fee_credit_balance": nuevo_credito,
                "fee_status": "due" if nueva_deuda > 0 else "clear",
                "last_fee_generated_at": datetime.utcnow(),
            },
        )
        FeeModel.registrar_fee(
            {
                "telegram_id": telegram_id,
                "operation_order_number": operacion.get("order_number"),
                "fee_admin": fee_generada,
                "credit_applied": credit_applied,
                "fee_due_after": nueva_deuda,
                "status": "generated",
                "fecha": datetime.utcnow(),
            }
        )
        OperacionModelSafe.actualizar_con_fee(
            telegram_id,
            operacion,
            fee_generada,
            credit_applied,
            None,
        )
        logger.info(
            "FEE_GENERADA | telegram_id=%s | order_number=%s | ganancia=%s | fee_generada=%s | credit_applied=%s | fee_due_total=%s",
            telegram_id,
            operacion.get("order_number"),
            f"{ganancia:.8f}",
            f"{fee_generada:.8f}",
            f"{credit_applied:.8f}",
            f"{nueva_deuda:.8f}",
        )
        return fee_generada

    def ensure_invoice_if_threshold_reached(self, telegram_id: int) -> Optional[Dict]:
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if not usuario:
            return None

        fee_due_total = float(usuario.get("fee_due_total") or 0.0)
        threshold = float(usuario.get("fee_threshold") or FEE_SETTLEMENT_THRESHOLD)
        if fee_due_total < threshold:
            return None

        if usuario.get("active_position"):
            UsuarioModel.marcar_fee_lock_pending(telegram_id)
            return None

        invoice = PaymentInvoiceModel.obtener_factura_pendiente_usuario(telegram_id)
        if invoice:
            UsuarioModel.aplicar_bloqueo_fee(telegram_id, invoice["invoice_id"])
            return invoice

        invoice = self.crear_factura(usuario)
        UsuarioModel.aplicar_bloqueo_fee(telegram_id, invoice["invoice_id"])
        logger.warning(
            "FEE_LOCK_APLICADO | telegram_id=%s | invoice_id=%s | amount=%s %s | destination_uid=%s",
            telegram_id,
            invoice["invoice_id"],
            f"{float(invoice.get('invoice_amount') or 0.0):.2f}",
            invoice.get("asset", PAYMENT_ASSET),
            invoice.get("destination_uid") or ADMIN_COINW_UID or "NO_CONFIGURADO",
        )
        self.notifier.send(telegram_id, self.construir_instrucciones_pago(invoice))
        return invoice

    def crear_factura(self, usuario: Dict) -> Dict:
        telegram_id = int(usuario["telegram_id"])
        base_due = round(float(usuario.get("fee_due_total") or 0.0), 2)
        invoice_id = self._generar_invoice_id(telegram_id)
        data = {
            "invoice_id": invoice_id,
            "telegram_id": telegram_id,
            "base_due": base_due,
            "invoice_amount": base_due,
            "asset": PAYMENT_ASSET,
            "payment_method": PAYMENT_METHOD,
            "destination_uid": ADMIN_COINW_UID,
            "status": "pending",
            "report_text": None,
            "reported_at": None,
            "confirmed_at": None,
            "confirmed_by": None,
            "admin_note": None,
        }
        PaymentInvoiceModel.registrar_factura(data)
        return PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})

    def construir_instrucciones_pago(self, invoice: Dict) -> str:
        return (
            "⛔ Trading pausado por fee pendiente\n\n"
            f"Monto exacto a pagar: {float(invoice.get('invoice_amount', 0)):.2f} {invoice.get('asset', PAYMENT_ASSET)}\n"
            f"Método: CoinW Internal Transfer\n"
            f"UID destino: {invoice.get('destination_uid') or ADMIN_COINW_UID or 'NO_CONFIGURADO'}\n"
            f"Código de pago: {invoice.get('invoice_id')}\n\n"
            "Instrucciones:\n"
            "1) Entra a tu cuenta CoinW.\n"
            "2) Haz una transferencia interna en USDT a ese UID.\n"
            "3) Envía exactamente ese monto.\n"
            "4) Luego pulsa '✅ Ya pagué fee' y reporta el pago."
        )

    def obtener_factura_usuario(self, telegram_id: int) -> Optional[Dict]:
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if not usuario:
            return None
        invoice_id = usuario.get("pending_fee_invoice_id")
        if invoice_id:
            invoice = PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})
            if invoice and invoice.get("status") in {"pending", "reported"}:
                return invoice
        return PaymentInvoiceModel.obtener_factura_pendiente_usuario(telegram_id)

    def reportar_pago(self, telegram_id: int, report_text: str) -> Optional[Dict]:
        invoice = self.obtener_factura_usuario(telegram_id)
        if not invoice:
            return None
        PaymentInvoiceModel.actualizar_factura(
            {"invoice_id": invoice["invoice_id"]},
            {
                "status": "reported",
                "report_text": report_text,
                "reported_at": datetime.utcnow(),
            },
        )
        invoice = PaymentInvoiceModel.obtener_factura({"invoice_id": invoice["invoice_id"]})
        logger.info(
            "FEE_PAGO_REPORTADO | telegram_id=%s | invoice_id=%s | status=%s",
            telegram_id,
            invoice.get("invoice_id"),
            invoice.get("status"),
        )
        self._notificar_admins_reporte(invoice)
        return invoice

    def confirmar_pago(self, invoice_id: str, admin_id: int) -> Optional[Dict]:
        invoice = PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})
        if not invoice or invoice.get("status") not in {"pending", "reported"}:
            return None

        telegram_id = int(invoice["telegram_id"])
        usuario = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if not usuario:
            return None

        due_total = float(usuario.get("fee_due_total") or 0.0)
        paid_total = float(usuario.get("fee_paid_total") or 0.0)
        credit_balance = float(usuario.get("fee_credit_balance") or 0.0)
        amount_received = round(float(invoice.get("invoice_amount") or 0.0), 8)
        base_due = round(float(invoice.get("base_due") or amount_received), 8)

        nueva_deuda = max(round(due_total - base_due, 8), 0.0)
        if nueva_deuda < 0.01:
            nueva_deuda = 0.0
        nuevo_credito = credit_balance
        if amount_received > due_total:
            nuevo_credito += amount_received - due_total

        PaymentInvoiceModel.actualizar_factura(
            {"invoice_id": invoice_id},
            {
                "status": "confirmed",
                "confirmed_at": datetime.utcnow(),
                "confirmed_by": admin_id,
                "amount_received": amount_received,
            },
        )
        FeeModel.registrar_fee(
            {
                "telegram_id": telegram_id,
                "fee_admin": -amount_received,
                "invoice_id": invoice_id,
                "status": "payment_confirmed",
                "fecha": datetime.utcnow(),
            }
        )

        if nueva_deuda <= 0:
            UsuarioModel.limpiar_bloqueo_fee(
                telegram_id,
                due_total=0.0,
                paid_total=paid_total + amount_received,
                credit_balance=nuevo_credito,
            )
            self.notifier.send(
                telegram_id,
                (
                    "✅ Pago de fee confirmado\n\n"
                    f"Factura: {invoice_id}\n"
                    f"Monto acreditado: {amount_received:.2f} {PAYMENT_ASSET}\n"
                    "Tu trading ha sido reactivado."
                ),
            )
        else:
            UsuarioModel.actualizar_usuario(
                {"telegram_id": telegram_id},
                {
                    "fee_due_total": nueva_deuda,
                    "fee_paid_total": paid_total + amount_received,
                    "fee_credit_balance": nuevo_credito,
                    "last_fee_paid_at": datetime.utcnow(),
                    "pending_fee_invoice_id": None,
                },
            )
            replacement_invoice = self.crear_factura(UsuarioModel.obtener_usuario({"telegram_id": telegram_id}))
            UsuarioModel.aplicar_bloqueo_fee(telegram_id, replacement_invoice["invoice_id"])
            logger.warning(
                "FEE_PAGO_PARCIAL | telegram_id=%s | invoice_id_anterior=%s | nueva_deuda=%s %s | nueva_factura=%s",
                telegram_id,
                invoice_id,
                f"{nueva_deuda:.2f}",
                PAYMENT_ASSET,
                replacement_invoice["invoice_id"],
            )
            self.notifier.send(
                telegram_id,
                (
                    "✅ Pago aplicado parcialmente\n\n"
                    f"Aún queda pendiente: {nueva_deuda:.2f} {PAYMENT_ASSET}\n\n"
                    + self.construir_instrucciones_pago(replacement_invoice)
                ),
            )

        return PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})

    def rechazar_pago(self, invoice_id: str, admin_id: int, motivo: str = "Pago no validado") -> Optional[Dict]:
        invoice = PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})
        if not invoice or invoice.get("status") not in {"pending", "reported"}:
            return None

        PaymentInvoiceModel.actualizar_factura(
            {"invoice_id": invoice_id},
            {
                "status": "rejected",
                "admin_note": motivo,
                "confirmed_at": datetime.utcnow(),
                "confirmed_by": admin_id,
            },
        )
        telegram_id = int(invoice["telegram_id"])
        UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"pending_fee_invoice_id": None},
        )
        replacement_invoice = self.crear_factura(UsuarioModel.obtener_usuario({"telegram_id": telegram_id}))
        UsuarioModel.aplicar_bloqueo_fee(telegram_id, replacement_invoice["invoice_id"])
        self.notifier.send(
            telegram_id,
            (
                "❌ El pago reportado no fue validado todavía.\n\n"
                f"Motivo admin: {motivo}\n\n"
                + self.construir_instrucciones_pago(replacement_invoice)
            ),
        )
        return PaymentInvoiceModel.obtener_factura({"invoice_id": invoice_id})


    def cobrar_fee_diaria(self, usuarios):
        """Compatibilidad con el scheduler antiguo.

        Mantiene el comportamiento previo de registrar fees agregadas por operaciones cerradas del día
        si algún flujo legado sigue poblando `operaciones_cerradas_dia`.
        """
        for usuario in usuarios:
            telegram_id = usuario["telegram_id"] if isinstance(usuario, dict) else getattr(usuario, "telegram_id")
            operaciones = usuario.get("operaciones_cerradas_dia", []) if isinstance(usuario, dict) else getattr(usuario, "operaciones_cerradas_dia", [])
            total_fee_admin = 0.0
            for operacion in operaciones:
                ganancia = operacion.get("ganancia", operacion.get("pnl_quote", 0))
                total_fee_admin += self.calcular_fee_admin(float(ganancia or 0))
            if total_fee_admin > 0:
                FeeModel.registrar_fee(
                    {
                        "telegram_id": telegram_id,
                        "fee_admin": total_fee_admin,
                        "status": "legacy_daily_summary",
                        "fecha": datetime.utcnow(),
                    }
                )

    def _notificar_admins_reporte(self, invoice: Dict) -> None:
        summary = (
            "🧾 Pago fee reportado\n\n"
            f"Usuario: {invoice.get('telegram_id')}\n"
            f"Factura: {invoice.get('invoice_id')}\n"
            f"Monto: {float(invoice.get('invoice_amount', 0)):.2f} {invoice.get('asset', PAYMENT_ASSET)}\n"
            f"UID destino: {invoice.get('destination_uid') or ADMIN_COINW_UID}\n"
            f"Reporte usuario: {invoice.get('report_text') or 'Sin detalle'}\n\n"
            "Revisa el panel admin para confirmar o rechazar."
        )
        for admin_id in ADMIN_TELEGRAM_IDS:
            self.notifier.send(admin_id, summary)

    def _generar_invoice_id(self, telegram_id: int) -> str:
        return f"FEE-{telegram_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


class OperacionModelSafe:
    @staticmethod
    def actualizar_con_fee(telegram_id: int, operacion: Dict, fee_generated: float, credit_applied: float, invoice_id: Optional[str]):
        from app.models import OperacionModel  # import local para evitar ciclos duros

        OperacionModel.actualizar_operacion(
            {"telegram_id": telegram_id, "order_number": operacion.get("order_number")},
            {
                "fee_generated": float(fee_generated),
                "fee_credit_applied": float(credit_applied),
                "fee_invoice_id": invoice_id,
                "fee_status": "generated" if fee_generated > 0 else "none",
            },
        )
