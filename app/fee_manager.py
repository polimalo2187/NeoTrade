import logging
from datetime import datetime
from typing import Dict, Optional

import requests

from app.config import (
    ADMIN_COINW_UID,
    ADMIN_TELEGRAM_IDS,
    FEE_ADMIN_PORC,
    FEE_REFERIDO_PORC,
    FEE_SETTLEMENT_THRESHOLD,
    PAYMENT_ASSET,
    PAYMENT_METHOD,
    TELEGRAM_BOT_TOKEN,
)
from app.fee_calculator import FeeCalculator
from app.models import FeeModel, PaymentInvoiceModel, ReferralCommissionModel, ReferidoModel, UsuarioModel


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
        self.calculadora = FeeCalculator(fee_admin=FEE_ADMIN_PORC, fee_referido=FEE_REFERIDO_PORC)
        self.notifier = FeeNotifier(TELEGRAM_BOT_TOKEN)

    def calcular_fee_admin(self, ganancia_neta: float) -> float:
        fee = self.calculadora.calcular_fee(ganancia_neta, referido_activo=False)
        return round(float(fee["admin"]), 8)

    def registrar_fee_operacion(self, usuario: Dict, operacion: Dict) -> float:
        telegram_id = int(usuario["telegram_id"])
        ganancia = max(float(operacion.get("pnl_quote") or 0.0), 0.0)
        if ganancia <= 0:
            OperacionModelSafe.actualizar_con_fee(
                telegram_id,
                operacion,
                fee_generated=0.0,
                credit_applied=0.0,
                invoice_id=None,
                fee_admin_net=0.0,
                referral_commission=0.0,
                fee_collection_status="none",
                referrer_id=None,
            )
            return 0.0

        if operacion.get("fee_status") == "generated" and float(operacion.get("fee_generated") or 0.0) > 0:
            return round(float(operacion.get("fee_generated") or 0.0), 8)

        existing_fee = FeeModel.obtener_fee(
            {
                "telegram_id": telegram_id,
                "operation_order_number": operacion.get("order_number"),
                "status": "generated",
            }
        )
        if existing_fee:
            return round(float(existing_fee.get("total_fee") or existing_fee.get("fee_admin") or 0.0), 8)

        usuario_actual = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or usuario
        referidor_id = usuario_actual.get("referidor_id")
        referido_activo = bool(referidor_id)
        fee_split = self.calculadora.calcular_fee(ganancia, referido_activo=referido_activo)
        fee_total = round(float(fee_split["total"]), 8)
        fee_admin_neta = round(float(fee_split["admin"]), 8)
        referral_commission = round(float(fee_split["referido"]), 8)

        credit_balance = float(usuario_actual.get("fee_credit_balance") or 0.0)
        due_total = float(usuario_actual.get("fee_due_total") or 0.0)
        credit_applied = round(min(credit_balance, fee_total), 8)
        fee_pendiente = round(max(fee_total - credit_applied, 0.0), 8)
        nuevo_credito = round(max(credit_balance - credit_applied, 0.0), 8)
        nueva_deuda = round(due_total + fee_pendiente, 8)
        collection_status = "collected" if fee_pendiente <= 0 else ("partial_collected" if credit_applied > 0 else "pending")

        UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "fee_due_total": nueva_deuda,
                "fee_credit_balance": nuevo_credito,
                "fee_status": "due" if nueva_deuda > 0 else "clear",
                "last_fee_generated_at": datetime.utcnow(),
            },
        )

        fee_record_id = FeeModel.registrar_fee(
            {
                "telegram_id": telegram_id,
                "operation_order_number": operacion.get("order_number"),
                "gross_profit": ganancia,
                "total_fee": fee_total,
                "fee_admin": fee_admin_neta,
                "fee_referido": referral_commission,
                "referrer_id": int(referidor_id) if referidor_id else None,
                "credit_applied": credit_applied,
                "collected_fee": credit_applied,
                "outstanding_fee": fee_pendiente,
                "fee_due_after": nueva_deuda,
                "status": "generated",
                "collection_status": collection_status,
                "fecha": datetime.utcnow(),
            }
        )

        OperacionModelSafe.actualizar_con_fee(
            telegram_id,
            operacion,
            fee_generated=fee_total,
            credit_applied=credit_applied,
            invoice_id=None,
            fee_admin_net=fee_admin_neta,
            referral_commission=referral_commission,
            fee_collection_status=collection_status,
            referrer_id=int(referidor_id) if referidor_id else None,
        )

        if referidor_id and referral_commission > 0:
            ReferralCommissionModel.registrar_comision(
                {
                    "referidor_id": int(referidor_id),
                    "referido_id": telegram_id,
                    "operation_order_number": operacion.get("order_number"),
                    "source_fee_id": str(fee_record_id),
                    "gross_profit": ganancia,
                    "fee_total_amount": fee_total,
                    "admin_net_amount": fee_admin_neta,
                    "commission_amount": referral_commission,
                    "status": "available" if collection_status == "collected" else "pending_collection",
                    "payout_status": "available" if collection_status == "collected" else "pending",
                    "available_amount": referral_commission if collection_status == "collected" else 0.0,
                    "paid_amount": 0.0,
                    "available_at": datetime.utcnow() if collection_status == "collected" else None,
                }
            )
            if collection_status == "collected":
                UsuarioModel.registrar_referral_disponible(int(referidor_id), referral_commission)
                ReferidoModel.registrar_comision_disponible(telegram_id, referral_commission)
            else:
                UsuarioModel.registrar_referral_pendiente(int(referidor_id), referral_commission)
                ReferidoModel.registrar_comision_pendiente(telegram_id, referral_commission)

        logger.info(
            "FEE_GENERADA | telegram_id=%s | order_number=%s | ganancia=%s | fee_total=%s | fee_admin_neta=%s | fee_referido=%s | credit_applied=%s | fee_due_total=%s | referrer_id=%s | collection_status=%s",
            telegram_id,
            operacion.get("order_number"),
            f"{ganancia:.8f}",
            f"{fee_total:.8f}",
            f"{fee_admin_neta:.8f}",
            f"{referral_commission:.8f}",
            f"{credit_applied:.8f}",
            f"{nueva_deuda:.8f}",
            referidor_id,
            collection_status,
        )
        return fee_total

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
        amount_to_apply = round(min(amount_received, base_due), 8)

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

        self._aplicar_cobro_a_fees_generadas(telegram_id, amount_to_apply)

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

    def _aplicar_cobro_a_fees_generadas(self, telegram_id: int, amount_to_apply: float) -> None:
        restante = round(float(amount_to_apply or 0.0), 8)
        if restante <= 0:
            return

        fees_pendientes = FeeModel.obtener_fees_pendientes_cobro(telegram_id)
        for fee in fees_pendientes:
            if restante <= 0:
                break
            total_fee = round(float(fee.get("total_fee") or 0.0), 8)
            collected_fee = round(float(fee.get("collected_fee") or 0.0), 8)
            outstanding_fee = round(float(fee.get("outstanding_fee") or max(total_fee - collected_fee, 0.0)), 8)
            if outstanding_fee <= 0:
                continue

            aplicado = round(min(restante, outstanding_fee), 8)
            nuevo_cobrado = round(collected_fee + aplicado, 8)
            nuevo_pendiente = round(max(total_fee - nuevo_cobrado, 0.0), 8)
            collection_status = "collected" if nuevo_pendiente <= 0 else "partial_collected"

            FeeModel.actualizar_fee(
                {"_id": fee.get("_id")},
                {
                    "collected_fee": nuevo_cobrado,
                    "outstanding_fee": nuevo_pendiente,
                    "collection_status": collection_status,
                    "last_collected_at": datetime.utcnow(),
                },
            )
            restante = round(restante - aplicado, 8)

            if collection_status == "collected":
                self._liberar_comision_referido_si_aplica(fee)

    def _liberar_comision_referido_si_aplica(self, fee: Dict) -> None:
        referidor_id = fee.get("referrer_id")
        referral_amount = round(float(fee.get("fee_referido") or 0.0), 8)
        if not referidor_id or referral_amount <= 0:
            return

        operation_order_number = fee.get("operation_order_number")
        commission = ReferralCommissionModel.obtener_comision(
            {"referido_id": int(fee.get("telegram_id")), "operation_order_number": operation_order_number}
        )
        if not commission:
            return
        if commission.get("status") == "available" or commission.get("payout_status") == "paid":
            return

        ReferralCommissionModel.actualizar_comision(
            {"_id": commission.get("_id")},
            {
                "status": "available",
                "payout_status": "available",
                "available_amount": referral_amount,
                "available_at": datetime.utcnow(),
            },
        )
        UsuarioModel.liberar_referral_a_disponible(int(referidor_id), referral_amount)
        ReferidoModel.liberar_comision_a_disponible(int(fee.get("telegram_id")), referral_amount)
        logger.info(
            "REFERRAL_COMMISSION_AVAILABLE | referido_id=%s | referidor_id=%s | order_number=%s | commission=%s %s",
            fee.get("telegram_id"),
            referidor_id,
            operation_order_number,
            f"{referral_amount:.8f}",
            PAYMENT_ASSET,
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
    def actualizar_con_fee(
        telegram_id: int,
        operacion: Dict,
        fee_generated: float,
        credit_applied: float,
        invoice_id: Optional[str],
        fee_admin_net: float,
        referral_commission: float,
        fee_collection_status: str,
        referrer_id: Optional[int],
    ):
        from app.models import OperacionModel  # import local para evitar ciclos duros

        OperacionModel.actualizar_operacion(
            {"telegram_id": telegram_id, "order_number": operacion.get("order_number")},
            {
                "fee_generated": float(fee_generated),
                "fee_admin_net": float(fee_admin_net),
                "referral_commission": float(referral_commission),
                "referrer_id": int(referrer_id) if referrer_id else None,
                "fee_credit_applied": float(credit_applied),
                "fee_invoice_id": invoice_id,
                "fee_status": "generated" if fee_generated > 0 else "none",
                "fee_collection_status": fee_collection_status,
            },
        )
