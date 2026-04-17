from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import DESCENDING

from app.config import FEE_ADMIN_PORC, FEE_SETTLEMENT_THRESHOLD, PAYMENT_ASSET, PAYMENT_METHOD
from app.db import Database


db = Database()


class UsuarioModel:
    COLECCION = "usuarios"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(UsuarioModel.COLECCION, "telegram_id", unique=True)
        db.crear_indice(UsuarioModel.COLECCION, "bot_activo")
        db.crear_indice(UsuarioModel.COLECCION, "trading_enabled")
        db.crear_indice(UsuarioModel.COLECCION, "fee_status")
        db.crear_indice(UsuarioModel.COLECCION, "referidor_id", sparse=True)

    @staticmethod
    def defaults(usuario_data: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        defaults = {
            "capital_total": 0.0,
            "capital_activo": 0.0,
            "codigo_referido": str(usuario_data.get("telegram_id")),
            "referidor_id": None,
            "referred_by_code": None,
            "referral_linked_at": None,
            "ganancia_diaria_referidos": 0.0,
            "ganancia_acumulada_referidos": 0.0,
            "referral_pending_balance": 0.0,
            "referral_available_balance": 0.0,
            "referral_paid_total": 0.0,
            "estado": None,
            "api_key": None,
            "api_secret": None,
            "api_key_temp": None,
            "bot_activo": False,
            "trading_enabled": True,
            "trading_pause_reason": None,
            "trading_lock_pending": False,
            "active_position": None,
            "last_engine_error": None,
            "payment_method": PAYMENT_METHOD,
            "payment_asset": PAYMENT_ASSET,
            "fee_percent": float(FEE_ADMIN_PORC),
            "fee_threshold": float(FEE_SETTLEMENT_THRESHOLD),
            "fee_due_total": 0.0,
            "fee_paid_total": 0.0,
            "fee_credit_balance": 0.0,
            "fee_status": "clear",
            "pending_fee_invoice_id": None,
            "last_fee_generated_at": None,
            "last_fee_paid_at": None,
            "created_at": now,
            "updated_at": now,
            "stats": {
                "opened": 0,
                "closed": 0,
                "wins": 0,
                "losses": 0,
                "pnl_quote": 0.0,
            },
        }
        defaults.update(usuario_data)
        return defaults

    @staticmethod
    def crear_usuario(usuario_data: Dict[str, Any]):
        data = UsuarioModel.defaults(usuario_data)
        return db.insertar_documento(UsuarioModel.COLECCION, data)

    @staticmethod
    def obtener_usuario(filtro: Dict[str, Any]):
        return db.buscar_documento(UsuarioModel.COLECCION, filtro)

    @staticmethod
    def actualizar_usuario(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        actualizacion = dict(actualizacion)
        actualizacion["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(UsuarioModel.COLECCION, filtro, actualizacion)

    @staticmethod
    def upsert_usuario_por_telegram_id(telegram_id: int, actualizacion: Dict[str, Any]):
        data = UsuarioModel.defaults({"telegram_id": telegram_id})
        data.update(actualizacion)
        data["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": telegram_id},
            data,
            upsert=True,
        )

    @staticmethod
    def obtener_todos_usuarios() -> List[Dict[str, Any]]:
        return db.buscar_todos_documentos(UsuarioModel.COLECCION)

    @staticmethod
    def obtener_usuarios_activos() -> List[Dict[str, Any]]:
        return db.buscar_todos_documentos(
            UsuarioModel.COLECCION,
            {
                "bot_activo": True,
                "trading_enabled": True,
                "api_key": {"$ne": None},
                "api_secret": {"$ne": None},
            },
        )

    @staticmethod
    def obtener_usuarios_para_engine() -> List[Dict[str, Any]]:
        return db.buscar_todos_documentos(
            UsuarioModel.COLECCION,
            {
                "bot_activo": True,
                "api_key": {"$ne": None},
                "api_secret": {"$ne": None},
                "$or": [
                    {"trading_enabled": True},
                    {"active_position": {"$ne": None}},
                ],
            },
        )

    @staticmethod
    def obtener_usuarios_bloqueados_fee() -> List[Dict[str, Any]]:
        return db.buscar_todos_documentos(
            UsuarioModel.COLECCION,
            {"trading_pause_reason": "fee_due"},
            sort=[("updated_at", DESCENDING)],
            limit=50,
        )

    @staticmethod
    def set_bot_activo(telegram_id: int, activo: bool):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"bot_activo": activo},
        )

    @staticmethod
    def guardar_posicion_activa(telegram_id: int, posicion: Dict[str, Any]):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"active_position": posicion},
        )

    @staticmethod
    def limpiar_posicion_activa(telegram_id: int):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"active_position": None},
        )

    @staticmethod
    def actualizar_engine_error(telegram_id: int, error: Optional[str]):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"last_engine_error": error},
        )

    @staticmethod
    def pausar_trading_manual(telegram_id: int):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "trading_enabled": False,
                "trading_pause_reason": "manual_pause",
            },
        )

    @staticmethod
    def reanudar_trading_manual(telegram_id: int):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "trading_enabled": True,
                "trading_pause_reason": None,
            },
        )

    @staticmethod
    def vincular_referidor(telegram_id: int, referidor_id: int, referral_code: str):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "referidor_id": int(referidor_id),
                "referred_by_code": str(referral_code),
                "referral_linked_at": datetime.utcnow(),
            },
        )

    @staticmethod
    def registrar_referral_pendiente(referidor_id: int, monto: float):
        return db.incrementar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": referidor_id},
            {"referral_pending_balance": float(monto)},
        )

    @staticmethod
    def registrar_referral_disponible(referidor_id: int, monto: float):
        return db.incrementar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": referidor_id},
            {
                "referral_available_balance": float(monto),
                "ganancia_diaria_referidos": float(monto),
                "ganancia_acumulada_referidos": float(monto),
            },
        )

    @staticmethod
    def liberar_referral_a_disponible(referidor_id: int, monto: float):
        return db.incrementar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": referidor_id},
            {
                "referral_pending_balance": -float(monto),
                "referral_available_balance": float(monto),
                "ganancia_diaria_referidos": float(monto),
                "ganancia_acumulada_referidos": float(monto),
            },
        )

    @staticmethod
    def registrar_referral_pagado(referidor_id: int, monto: float):
        return db.incrementar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": referidor_id},
            {
                "referral_available_balance": -float(monto),
                "referral_paid_total": float(monto),
            },
        )

    @staticmethod
    def actualizar_capital_snapshot(telegram_id: int, capital_total: float, capital_activo: float):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "capital_total": float(capital_total),
                "capital_activo": float(capital_activo),
            },
        )

    @staticmethod
    def incrementar_stats(telegram_id: int, incrementos: Dict[str, Any]):
        return db.incrementar_documento(
            UsuarioModel.COLECCION,
            {"telegram_id": telegram_id},
            {f"stats.{k}": v for k, v in incrementos.items()},
        )

    @staticmethod
    def aplicar_bloqueo_fee(telegram_id: int, invoice_id: str):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "trading_enabled": False,
                "trading_pause_reason": "fee_due",
                "trading_lock_pending": False,
                "fee_status": "locked",
                "pending_fee_invoice_id": invoice_id,
            },
        )

    @staticmethod
    def marcar_fee_due(telegram_id: int, due_total: float):
        fee_status = "due" if due_total > 0 else "clear"
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "fee_due_total": float(due_total),
                "fee_status": fee_status,
                "last_fee_generated_at": datetime.utcnow(),
            },
        )

    @staticmethod
    def marcar_fee_lock_pending(telegram_id: int):
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "trading_lock_pending": True,
                "fee_status": "due",
            },
        )

    @staticmethod
    def limpiar_bloqueo_fee(telegram_id: int, due_total: float, paid_total: float, credit_balance: float):
        fee_status = "clear" if due_total <= 0 else "due"
        trading_enabled = due_total <= 0
        trading_pause_reason = None if trading_enabled else "fee_due"
        return UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "fee_due_total": float(max(due_total, 0.0)),
                "fee_paid_total": float(max(paid_total, 0.0)),
                "fee_credit_balance": float(max(credit_balance, 0.0)),
                "fee_status": fee_status,
                "trading_enabled": trading_enabled,
                "trading_pause_reason": trading_pause_reason,
                "trading_lock_pending": False,
                "pending_fee_invoice_id": None if trading_enabled else None,
                "last_fee_paid_at": datetime.utcnow(),
            },
        )


class OperacionModel:
    COLECCION = "operaciones"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(OperacionModel.COLECCION, "telegram_id")
        db.crear_indice(OperacionModel.COLECCION, "status")
        db.crear_indice(OperacionModel.COLECCION, "opened_at", sparse=True)
        db.crear_indice(OperacionModel.COLECCION, "closed_at", sparse=True)
        db.crear_indice(OperacionModel.COLECCION, "order_number", sparse=True)

    @staticmethod
    def registrar_operacion(operacion_data: Dict[str, Any]):
        data = dict(operacion_data)
        data.setdefault("created_at", datetime.utcnow())
        return db.insertar_documento(OperacionModel.COLECCION, data)

    @staticmethod
    def obtener_operaciones(filtro: Dict[str, Any], limit: int = 50):
        return db.buscar_todos_documentos(
            OperacionModel.COLECCION,
            filtro,
            sort=[("created_at", DESCENDING)],
            limit=limit,
        )

    @staticmethod
    def actualizar_operacion(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        payload = dict(actualizacion)
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(OperacionModel.COLECCION, filtro, payload)

    @staticmethod
    def obtener_operacion(filtro: Dict[str, Any]):
        return db.buscar_documento(OperacionModel.COLECCION, filtro)


class ReferidoModel:
    COLECCION = "referidos"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(ReferidoModel.COLECCION, "referido_id", unique=True)
        db.crear_indice(ReferidoModel.COLECCION, "referidor_id")
        db.crear_indice(ReferidoModel.COLECCION, "status")

    @staticmethod
    def registrar_referido(referido_data: Dict[str, Any]):
        data = {
            "codigo_referido": None,
            "status": "linked",
            "ganancia_diaria": 0.0,
            "ganancia_acumulada": 0.0,
            "comision": 0.0,
            "total_pendiente": 0.0,
            "total_disponible": 0.0,
            "total_pagado": 0.0,
            "fecha_registro": datetime.utcnow(),
            "last_commission_at": None,
        }
        data.update(referido_data)
        return db.insertar_documento(ReferidoModel.COLECCION, data)

    @staticmethod
    def obtener_referidos(filtro: Dict[str, Any]):
        return db.buscar_todos_documentos(ReferidoModel.COLECCION, filtro)

    @staticmethod
    def obtener_referido(filtro: Dict[str, Any]):
        return db.buscar_documento(ReferidoModel.COLECCION, filtro)

    @staticmethod
    def vincular_referido(referidor_id: int, referido_id: int, codigo_referido: str):
        existente = ReferidoModel.obtener_referido({"referido_id": referido_id})
        if existente:
            return existente
        ReferidoModel.registrar_referido(
            {
                "referidor_id": int(referidor_id),
                "referido_id": int(referido_id),
                "codigo_referido": str(codigo_referido),
                "status": "linked",
            }
        )
        return ReferidoModel.obtener_referido({"referido_id": referido_id})

    @staticmethod
    def registrar_comision_pendiente(referido_id: int, monto: float):
        collection = db.obtener_coleccion(ReferidoModel.COLECCION)
        collection.update_one(
            {"referido_id": int(referido_id)},
            {
                "$inc": {
                    "total_pendiente": float(monto),
                    "comision": float(monto),
                },
                "$set": {"last_commission_at": datetime.utcnow()},
            },
        )

    @staticmethod
    def registrar_comision_disponible(referido_id: int, monto: float):
        collection = db.obtener_coleccion(ReferidoModel.COLECCION)
        collection.update_one(
            {"referido_id": int(referido_id)},
            {
                "$inc": {
                    "total_disponible": float(monto),
                    "ganancia_diaria": float(monto),
                    "ganancia_acumulada": float(monto),
                    "comision": float(monto),
                },
                "$set": {"last_commission_at": datetime.utcnow()},
            },
        )

    @staticmethod
    def liberar_comision_a_disponible(referido_id: int, monto: float):
        collection = db.obtener_coleccion(ReferidoModel.COLECCION)
        collection.update_one(
            {"referido_id": int(referido_id)},
            {
                "$inc": {
                    "total_pendiente": -float(monto),
                    "total_disponible": float(monto),
                    "ganancia_diaria": float(monto),
                    "ganancia_acumulada": float(monto),
                },
                "$set": {"last_commission_at": datetime.utcnow()},
            },
        )

    @staticmethod
    def registrar_comision_pagada(referido_id: int, monto: float):
        collection = db.obtener_coleccion(ReferidoModel.COLECCION)
        collection.update_one(
            {"referido_id": int(referido_id)},
            {
                "$inc": {
                    "total_disponible": -float(monto),
                    "total_pagado": float(monto),
                },
                "$set": {"last_commission_at": datetime.utcnow()},
            },
        )


class FeeModel:
    COLECCION = "fees"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(FeeModel.COLECCION, "telegram_id")
        db.crear_indice(FeeModel.COLECCION, "fecha")
        db.crear_indice(FeeModel.COLECCION, "invoice_id", sparse=True)
        db.crear_indice(FeeModel.COLECCION, "operation_order_number", sparse=True)
        db.crear_indice(FeeModel.COLECCION, "collection_status")

    @staticmethod
    def registrar_fee(fee_data: Dict[str, Any]):
        data = dict(fee_data)
        data.setdefault("fecha", datetime.utcnow())
        return db.insertar_documento(FeeModel.COLECCION, data)

    @staticmethod
    def obtener_fee(filtro: Dict[str, Any]):
        return db.buscar_documento(FeeModel.COLECCION, filtro)

    @staticmethod
    def obtener_fees(filtro: Dict[str, Any], limit: Optional[int] = None):
        return db.buscar_todos_documentos(
            FeeModel.COLECCION,
            filtro,
            sort=[("fecha", DESCENDING)],
            limit=limit,
        )

    @staticmethod
    def actualizar_fee(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        payload = dict(actualizacion)
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(FeeModel.COLECCION, filtro, payload)

    @staticmethod
    def obtener_fees_pendientes_cobro(telegram_id: int):
        return db.buscar_todos_documentos(
            FeeModel.COLECCION,
            {
                "telegram_id": int(telegram_id),
                "collection_status": {"$in": ["pending", "partial_collected"]},
                "total_fee": {"$gt": 0},
            },
            sort=[("fecha", 1)],
        )


class ReferralCommissionModel:
    COLECCION = "referral_commissions"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(ReferralCommissionModel.COLECCION, [("referido_id", 1), ("operation_order_number", 1)], unique=True)
        db.crear_indice(ReferralCommissionModel.COLECCION, "referidor_id")
        db.crear_indice(ReferralCommissionModel.COLECCION, "status")
        db.crear_indice(ReferralCommissionModel.COLECCION, "payout_status")
        db.crear_indice(ReferralCommissionModel.COLECCION, "created_at")

    @staticmethod
    def registrar_comision(data: Dict[str, Any]):
        payload = {
            "status": "pending_collection",
            "payout_status": "pending",
            "available_amount": 0.0,
            "paid_amount": 0.0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        payload.update(data)
        return db.insertar_documento(ReferralCommissionModel.COLECCION, payload)

    @staticmethod
    def obtener_comision(filtro: Dict[str, Any]):
        return db.buscar_documento(ReferralCommissionModel.COLECCION, filtro)

    @staticmethod
    def obtener_comisiones(filtro: Dict[str, Any], limit: Optional[int] = None):
        return db.buscar_todos_documentos(
            ReferralCommissionModel.COLECCION,
            filtro,
            sort=[("created_at", DESCENDING)],
            limit=limit,
        )

    @staticmethod
    def actualizar_comision(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        payload = dict(actualizacion)
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(ReferralCommissionModel.COLECCION, filtro, payload)


class PaymentInvoiceModel:
    COLECCION = "fee_invoices"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(PaymentInvoiceModel.COLECCION, "invoice_id", unique=True)
        db.crear_indice(PaymentInvoiceModel.COLECCION, "telegram_id")
        db.crear_indice(PaymentInvoiceModel.COLECCION, "status")
        db.crear_indice(PaymentInvoiceModel.COLECCION, "created_at")

    @staticmethod
    def registrar_factura(invoice_data: Dict[str, Any]):
        data = {
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        data.update(invoice_data)
        return db.insertar_documento(PaymentInvoiceModel.COLECCION, data)

    @staticmethod
    def obtener_factura(filtro: Dict[str, Any]):
        return db.buscar_documento(PaymentInvoiceModel.COLECCION, filtro)

    @staticmethod
    def obtener_facturas(filtro: Dict[str, Any], limit: int = 20):
        return db.buscar_todos_documentos(
            PaymentInvoiceModel.COLECCION,
            filtro,
            sort=[("created_at", DESCENDING)],
            limit=limit,
        )

    @staticmethod
    def actualizar_factura(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        payload = dict(actualizacion)
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(PaymentInvoiceModel.COLECCION, filtro, payload)

    @staticmethod
    def obtener_factura_pendiente_usuario(telegram_id: int):
        return db.buscar_documento(
            PaymentInvoiceModel.COLECCION,
            {"telegram_id": telegram_id, "status": {"$in": ["pending", "reported"]}},
        )



class TradeStateModel:
    COLECCION = "trade_states"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(TradeStateModel.COLECCION, "trade_id", unique=True)
        db.crear_indice(TradeStateModel.COLECCION, "telegram_id")
        db.crear_indice(TradeStateModel.COLECCION, "status")
        db.crear_indice(TradeStateModel.COLECCION, "symbol")
        db.crear_indice(TradeStateModel.COLECCION, "updated_at")

    @staticmethod
    def upsert_estado(trade_id: str, telegram_id: int, state: Dict[str, Any]):
        data = dict(state)
        data["trade_id"] = trade_id
        data["telegram_id"] = telegram_id
        data.setdefault("created_at", datetime.utcnow())
        data["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(
            TradeStateModel.COLECCION,
            {"trade_id": trade_id},
            data,
            upsert=True,
        )

    @staticmethod
    def obtener_estado(filtro: Dict[str, Any]):
        return db.buscar_documento(TradeStateModel.COLECCION, filtro)

    @staticmethod
    def obtener_estados(filtro: Optional[Dict[str, Any]] = None, limit: int = 100):
        return db.buscar_todos_documentos(
            TradeStateModel.COLECCION,
            filtro or {},
            sort=[("updated_at", DESCENDING)],
            limit=limit,
        )

    @staticmethod
    def actualizar_estado(filtro: Dict[str, Any], actualizacion: Dict[str, Any]):
        payload = dict(actualizacion)
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(TradeStateModel.COLECCION, filtro, payload)

    @staticmethod
    def cerrar_estado(trade_id: str, actualizacion: Optional[Dict[str, Any]] = None):
        payload = {"status": "CLOSED", "closed_at": datetime.utcnow()}
        payload.update(actualizacion or {})
        payload["updated_at"] = datetime.utcnow()
        return db.actualizar_documento(TradeStateModel.COLECCION, {"trade_id": trade_id}, payload)


class TradeEventModel:
    COLECCION = "trade_events"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(TradeEventModel.COLECCION, "trade_id")
        db.crear_indice(TradeEventModel.COLECCION, "telegram_id")
        db.crear_indice(TradeEventModel.COLECCION, "type")
        db.crear_indice(TradeEventModel.COLECCION, "created_at")

    @staticmethod
    def registrar_evento(trade_id: str, telegram_id: int, event_type: str, payload: Optional[Dict[str, Any]] = None):
        return db.insertar_documento(
            TradeEventModel.COLECCION,
            {
                "trade_id": trade_id,
                "telegram_id": telegram_id,
                "type": event_type,
                "payload": payload or {},
                "created_at": datetime.utcnow(),
            },
        )

    @staticmethod
    def obtener_eventos(filtro: Dict[str, Any], limit: int = 100):
        return db.buscar_todos_documentos(
            TradeEventModel.COLECCION,
            filtro,
            sort=[("created_at", DESCENDING)],
            limit=limit,
        )


def ensure_indexes() -> None:
    UsuarioModel.ensure_indexes()
    OperacionModel.ensure_indexes()
    ReferidoModel.ensure_indexes()
    FeeModel.ensure_indexes()
    ReferralCommissionModel.ensure_indexes()
    PaymentInvoiceModel.ensure_indexes()
    TradeStateModel.ensure_indexes()
    TradeEventModel.ensure_indexes()
