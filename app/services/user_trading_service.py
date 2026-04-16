import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.config import CAPITAL_ACTIVO_PORC, QUOTE_ASSET
from app.exchange import CoinWApiError, CoinWEmptySpotBalanceError, ExchangeClient
from app.fee_manager import FeeManager
from app.models import OperacionModel, UsuarioModel
from app.usuario import Usuario


logger = logging.getLogger(__name__)


@dataclass
class StartSessionResult:
    user: Dict[str, Any]
    created: bool


@dataclass
class BotActivationResult:
    status: str
    user: Optional[Dict[str, Any]] = None
    invoice: Optional[Dict[str, Any]] = None
    capital_total: float = 0.0
    available_quote: float = 0.0
    reason: Optional[str] = None


@dataclass
class CapitalSnapshotResult:
    status: str
    user: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass
class StatefulMessageResult:
    status: str
    invoice: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class UserTradingService:
    def __init__(self, fee_manager: Optional[FeeManager] = None):
        self.fee_manager = fee_manager or FeeManager()

    @staticmethod
    def normalize_api_credential(value: str) -> str:
        if value is None:
            return ""
        cleaned = str(value).strip()
        for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
            cleaned = cleaned.replace(ch, "")
        return cleaned.strip("`\"' ")

    @staticmethod
    def format_decimal(value: float) -> str:
        return f"{float(value):.8f}"

    def get_or_create_user(self, telegram_id: int, first_name: Optional[str]) -> StartSessionResult:
        nombre_usuario = first_name or "usuario"
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if usuario_data:
            return StartSessionResult(user=usuario_data, created=False)

        UsuarioModel.crear_usuario(
            {
                "telegram_id": telegram_id,
                "nombre": nombre_usuario,
                "codigo_referido": str(telegram_id),
            }
        )
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {
            "telegram_id": telegram_id,
            "nombre": nombre_usuario,
            "codigo_referido": str(telegram_id),
        }
        return StartSessionResult(user=usuario_data, created=True)

    def reset_navigation_state(self, telegram_id: int, clear_temp_api: bool = False) -> None:
        updates = {"estado": None}
        if clear_temp_api:
            updates["api_key_temp"] = None
        UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, updates)

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        return UsuarioModel.obtener_usuario({"telegram_id": telegram_id})

    def get_fee_invoice(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        return self.fee_manager.obtener_factura_usuario(telegram_id)

    def activate_bot(self, telegram_id: int) -> BotActivationResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return BotActivationResult(status="user_not_found")

        if not usuario.get("api_key") or not usuario.get("api_secret"):
            return BotActivationResult(status="missing_credentials", user=usuario)

        capital_total = 0.0
        available_quote = 0.0
        try:
            client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
            capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
            capital_total = float(capital["capital_total_estimated"])
            available_quote = float(capital["quote_available"])
            capital_activo = capital_total * CAPITAL_ACTIVO_PORC
            UsuarioModel.actualizar_capital_snapshot(telegram_id, capital_total, capital_activo)
            logger.info(
                "USUARIO_ACTIVADO | telegram_id=%s | quote_asset=%s | capital_estimado=%s | quote_disponible=%s | fee_due_total=%s | trading_pause_reason=%s",
                telegram_id,
                QUOTE_ASSET,
                self.format_decimal(capital_total),
                self.format_decimal(available_quote),
                self.format_decimal(float(usuario.get("fee_due_total") or 0.0)),
                usuario.get("trading_pause_reason") or "none",
            )
        except CoinWEmptySpotBalanceError as exc:
            logger.warning(
                "USUARIO_ACTIVACION_BALANCE_SPOT_VACIO | telegram_id=%s | motivo=%s",
                telegram_id,
                exc,
            )
            return BotActivationResult(status="empty_spot_balance", user=usuario, reason=str(exc))
        except CoinWApiError as exc:
            logger.warning(
                "USUARIO_ACTIVADO_SIN_SNAPSHOT | telegram_id=%s | motivo=%s",
                telegram_id,
                exc,
            )
        except Exception:
            logger.exception("No se pudo obtener snapshot de capital al activar usuario %s", telegram_id)

        UsuarioModel.set_bot_activo(telegram_id, True)
        updated_user = self.get_user(telegram_id) or usuario
        invoice = self.get_fee_invoice(telegram_id) if updated_user.get("trading_pause_reason") == "fee_due" else None
        return BotActivationResult(
            status="activated",
            user=updated_user,
            invoice=invoice,
            capital_total=capital_total,
            available_quote=available_quote,
        )

    def deactivate_bot(self, telegram_id: int) -> None:
        UsuarioModel.set_bot_activo(telegram_id, False)

    def refresh_capital(self, telegram_id: int) -> CapitalSnapshotResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return CapitalSnapshotResult(status="user_not_found")

        if usuario.get("api_key") and usuario.get("api_secret"):
            try:
                client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
                capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
                capital_total = float(capital["capital_total_estimated"])
                capital_activo = capital_total * CAPITAL_ACTIVO_PORC
                UsuarioModel.actualizar_capital_snapshot(telegram_id, capital_total, capital_activo)
                usuario = self.get_user(telegram_id) or usuario
            except CoinWEmptySpotBalanceError as exc:
                logger.warning("CAPITAL_SPOT_VACIO | telegram_id=%s | motivo=%s", telegram_id, exc)
                return CapitalSnapshotResult(status="empty_spot_balance", user=usuario, reason=str(exc))
            except Exception as exc:
                logger.warning("No se pudo refrescar el capital en vivo del usuario %s: %s", telegram_id, exc)
                return CapitalSnapshotResult(status="refresh_error", user=usuario, reason=str(exc))
        return CapitalSnapshotResult(status="ok", user=usuario)

    def get_recent_operations(self, telegram_id: int, limit: int = 10):
        return OperacionModel.obtener_operaciones({"telegram_id": telegram_id}, limit=limit)

    def begin_api_key_capture(self, telegram_id: int) -> None:
        UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_api_key"})

    def begin_fee_report(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        invoice = self.get_fee_invoice(telegram_id)
        if not invoice:
            return None
        UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_reporte_fee"})
        return invoice

    def process_stateful_message(self, telegram_id: int, text: str) -> StatefulMessageResult:
        usuario = self.get_user(telegram_id)
        if not usuario or not usuario.get("estado"):
            return StatefulMessageResult(status="ignored")

        estado = usuario.get("estado")
        logger.info("Mensaje de estado recibido telegram_id=%s estado=%s", telegram_id, estado)

        if estado == "esperando_api_key":
            api_key = self.normalize_api_credential(text)
            UsuarioModel.actualizar_usuario(
                {"telegram_id": telegram_id},
                {"api_key_temp": api_key, "estado": "esperando_api_secret"},
            )
            return StatefulMessageResult(status="awaiting_api_secret")

        if estado == "esperando_api_secret":
            api_key = self.normalize_api_credential(usuario.get("api_key_temp") or "")
            api_secret = self.normalize_api_credential(text)
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
                return StatefulMessageResult(status="api_validated")

            UsuarioModel.actualizar_usuario(
                {"telegram_id": telegram_id},
                {"estado": "esperando_api_key", "api_key_temp": None},
            )
            return StatefulMessageResult(status="api_invalid", reason=error_msg)

        if estado == "esperando_reporte_fee":
            invoice = self.fee_manager.reportar_pago(telegram_id, text)
            UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": None})
            if not invoice:
                return StatefulMessageResult(status="fee_report_missing_invoice")
            return StatefulMessageResult(status="fee_reported", invoice=invoice)

        return StatefulMessageResult(status="ignored")
