import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

from app.config import CAPITAL_ACTIVO_PORC, PAYMENT_ASSET, QUOTE_ASSET
from app.exchange import CoinWApiError, CoinWEmptySpotBalanceError, ExchangeClient
from app.fee_manager import FeeManager
from app.models import OperacionModel, ReferidoModel, TradeEventModel, TradeStateModel, UsuarioModel
from app.usuario import Usuario


logger = logging.getLogger(__name__)

REFERRAL_BOT_USERNAME = "TradeNeo_bot"
REFERRAL_BOT_URL = f"https://t.me/{REFERRAL_BOT_USERNAME}"


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


@dataclass
class ApiCredentialUpdateResult:
    status: str
    user: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass
class TradingToggleResult:
    status: str
    user: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    invoice: Optional[Dict[str, Any]] = None


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

    @staticmethod
    def mask_api_key(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        value = str(value)
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

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

    def ensure_web_session_user(self, telegram_id: int, first_name: Optional[str]) -> Dict[str, Any]:
        session = self.get_or_create_user(telegram_id, first_name)
        return session.user

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

    def pause_trading(self, telegram_id: int) -> TradingToggleResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return TradingToggleResult(status="user_not_found")
        if usuario.get("trading_pause_reason") == "fee_due":
            return TradingToggleResult(
                status="fee_locked",
                user=usuario,
                reason="El trading está bloqueado por fee pendiente",
                invoice=self.get_fee_invoice(telegram_id),
            )
        UsuarioModel.pausar_trading_manual(telegram_id)
        return TradingToggleResult(status="paused", user=self.get_user(telegram_id) or usuario)

    def resume_trading(self, telegram_id: int) -> TradingToggleResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return TradingToggleResult(status="user_not_found")
        if usuario.get("trading_pause_reason") == "fee_due" or float(usuario.get("fee_due_total", 0) or 0) > 0:
            return TradingToggleResult(
                status="fee_locked",
                user=usuario,
                reason="No puedes reanudar el trading mientras exista fee pendiente",
                invoice=self.get_fee_invoice(telegram_id),
            )
        UsuarioModel.reanudar_trading_manual(telegram_id)
        return TradingToggleResult(status="resumed", user=self.get_user(telegram_id) or usuario)

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

    def get_recent_trade_states(self, telegram_id: int, limit: int = 10):
        return TradeStateModel.obtener_estados({"telegram_id": telegram_id}, limit=limit)

    def get_recent_trade_events(self, telegram_id: int, limit: int = 20):
        return TradeEventModel.obtener_eventos({"telegram_id": telegram_id}, limit=limit)

    def begin_api_key_capture(self, telegram_id: int) -> None:
        UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_api_key"})

    def begin_fee_report(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        invoice = self.get_fee_invoice(telegram_id)
        if not invoice:
            return None
        UsuarioModel.actualizar_usuario({"telegram_id": telegram_id}, {"estado": "esperando_reporte_fee"})
        return invoice

    def set_api_credentials(self, telegram_id: int, api_key: str, api_secret: str) -> ApiCredentialUpdateResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return ApiCredentialUpdateResult(status="user_not_found")

        normalized_key = self.normalize_api_credential(api_key)
        normalized_secret = self.normalize_api_credential(api_secret)
        if not normalized_key or not normalized_secret:
            return ApiCredentialUpdateResult(status="missing_credentials", user=usuario, reason="API Key y API Secret son obligatorios")

        exito, error_msg = Usuario.validar_api(normalized_key, normalized_secret, return_error=True)
        if not exito:
            return ApiCredentialUpdateResult(status="api_invalid", user=usuario, reason=error_msg)

        UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {
                "api_key": normalized_key,
                "api_secret": normalized_secret,
                "estado": None,
                "api_key_temp": None,
            },
        )
        usuario_actualizado = self.get_user(telegram_id) or usuario
        return ApiCredentialUpdateResult(status="api_validated", user=usuario_actualizado)

    def get_referral_summary(self, telegram_id: int) -> Dict[str, Any]:
        usuario = self.get_user(telegram_id) or {}
        referidos = ReferidoModel.obtener_referidos({"referidor_id": telegram_id})
        codigo_referido = str(usuario.get("codigo_referido") or telegram_id)
        enlace_referido = f"{REFERRAL_BOT_URL}?start={quote(codigo_referido)}"
        return {
            "codigo_referido": codigo_referido,
            "enlace_referido": enlace_referido,
            "bot_username": REFERRAL_BOT_USERNAME,
            "ganancia_diaria": float(usuario.get("ganancia_diaria_referidos", 0) or 0),
            "ganancia_acumulada": float(usuario.get("ganancia_acumulada_referidos", 0) or 0),
            "referidos_activos": len(referidos),
            "referidos": referidos,
        }

    def get_dashboard_snapshot(
        self,
        telegram_id: int,
        operations_limit: int = 10,
        events_limit: int = 10,
        refresh_capital: bool = False,
    ) -> Dict[str, Any]:
        capital_result = self.refresh_capital(telegram_id) if refresh_capital else CapitalSnapshotResult(
            status="snapshot",
            user=self.get_user(telegram_id),
            reason=None,
        )
        usuario = capital_result.user or self.get_user(telegram_id) or {}
        return {
            "user": self.serialize_user_public(usuario),
            "capital_status": capital_result.status,
            "capital_reason": capital_result.reason,
            "fee_invoice": self.get_fee_invoice(telegram_id),
            "recent_operations": self.get_recent_operations(telegram_id, limit=operations_limit),
            "recent_trade_states": self.get_recent_trade_states(telegram_id, limit=operations_limit),
            "recent_trade_events": self.get_recent_trade_events(telegram_id, limit=events_limit),
            "referrals": self.get_referral_summary(telegram_id),
        }

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

    def serialize_user_public(self, usuario: Dict[str, Any]) -> Dict[str, Any]:
        if not usuario:
            return {}
        return {
            "telegram_id": usuario.get("telegram_id"),
            "nombre": usuario.get("nombre"),
            "codigo_referido": usuario.get("codigo_referido"),
            "bot_activo": bool(usuario.get("bot_activo")),
            "trading_enabled": bool(usuario.get("trading_enabled", True)),
            "trading_pause_reason": usuario.get("trading_pause_reason"),
            "fee_status": usuario.get("fee_status", "clear"),
            "fee_due_total": float(usuario.get("fee_due_total", 0) or 0),
            "fee_paid_total": float(usuario.get("fee_paid_total", 0) or 0),
            "fee_threshold": float(usuario.get("fee_threshold", 0) or 0),
            "fee_percent": float(usuario.get("fee_percent", 0) or 0),
            "payment_asset": usuario.get("payment_asset") or PAYMENT_ASSET,
            "payment_method": usuario.get("payment_method") or "coinw_internal",
            "capital_total": float(usuario.get("capital_total", 0) or 0),
            "capital_activo": float(usuario.get("capital_activo", 0) or 0),
            "active_position": usuario.get("active_position"),
            "last_engine_error": usuario.get("last_engine_error"),
            "stats": usuario.get("stats") or {},
            "has_api_credentials": bool(usuario.get("api_key") and usuario.get("api_secret")),
            "api_key_masked": self.mask_api_key(usuario.get("api_key")),
            "updated_at": usuario.get("updated_at"),
            "created_at": usuario.get("created_at"),
        }
