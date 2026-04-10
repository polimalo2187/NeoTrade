from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import DESCENDING

from app.db import Database


db = Database()


class UsuarioModel:
    COLECCION = "usuarios"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(UsuarioModel.COLECCION, "telegram_id", unique=True)
        db.crear_indice(UsuarioModel.COLECCION, "bot_activo")

    @staticmethod
    def defaults(usuario_data: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        defaults = {
            "capital_total": 0.0,
            "capital_activo": 0.0,
            "codigo_referido": str(usuario_data.get("telegram_id")),
            "estado": None,
            "api_key": None,
            "api_secret": None,
            "api_key_temp": None,
            "bot_activo": False,
            "active_position": None,
            "last_engine_error": None,
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
            {"bot_activo": True, "api_key": {"$ne": None}, "api_secret": {"$ne": None}},
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


class ReferidoModel:
    COLECCION = "referidos"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(ReferidoModel.COLECCION, "referido_id", unique=True)
        db.crear_indice(ReferidoModel.COLECCION, "referidor_id")

    @staticmethod
    def registrar_referido(referido_data: Dict[str, Any]):
        data = {
            "ganancia_diaria": 0.0,
            "ganancia_acumulada": 0.0,
            "comision": 0.0,
            "fecha_registro": datetime.utcnow(),
        }
        data.update(referido_data)
        return db.insertar_documento(ReferidoModel.COLECCION, data)

    @staticmethod
    def obtener_referidos(filtro: Dict[str, Any]):
        return db.buscar_todos_documentos(ReferidoModel.COLECCION, filtro)

    @staticmethod
    def actualizar_ganancia_diaria(referido_id: int, monto: float):
        return db.incrementar_documento(
            ReferidoModel.COLECCION,
            {"referido_id": referido_id},
            {"ganancia_diaria": float(monto), "comision": float(monto)},
        )

    @staticmethod
    def actualizar_ganancia_acumulada(referido_id: int, monto: float):
        return db.incrementar_documento(
            ReferidoModel.COLECCION,
            {"referido_id": referido_id},
            {"ganancia_acumulada": float(monto)},
        )

    @staticmethod
    def actualizar_ganancia_referido(referidor_id: int, monto: float):
        return db.incrementar_documento(
            ReferidoModel.COLECCION,
            {"referidor_id": referidor_id},
            {"ganancia_diaria": float(monto), "comision": float(monto)},
            upsert=False,
        )


class FeeModel:
    COLECCION = "fees"

    @staticmethod
    def ensure_indexes() -> None:
        db.crear_indice(FeeModel.COLECCION, "telegram_id")
        db.crear_indice(FeeModel.COLECCION, "fecha")

    @staticmethod
    def registrar_fee(fee_data: Dict[str, Any]):
        data = dict(fee_data)
        data.setdefault("fecha", datetime.utcnow())
        return db.insertar_documento(FeeModel.COLECCION, data)

    @staticmethod
    def obtener_fees(filtro: Dict[str, Any]):
        return db.buscar_todos_documentos(FeeModel.COLECCION, filtro)


def ensure_indexes() -> None:
    UsuarioModel.ensure_indexes()
    OperacionModel.ensure_indexes()
    ReferidoModel.ensure_indexes()
    FeeModel.ensure_indexes()
