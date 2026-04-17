import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.config import (
    CAPITAL_ACTIVO_PORC,
    PAYMENT_ASSET,
    QUOTE_ASSET,
    REFERRAL_PAYOUT_COOLDOWN_HOURS,
    REFERRAL_PAYOUT_MIN_USDT,
)
from app.exchange import CoinWApiError, CoinWEmptySpotBalanceError, ExchangeClient
from app.fee_manager import FeeManager
from app.models import (
    OperacionModel,
    ReferidoModel,
    ReferralCommissionModel,
    ReferralPayoutRequestModel,
    TradeEventModel,
    TradeStateModel,
    UsuarioModel,
)
from app.usuario import Usuario


logger = logging.getLogger(__name__)

REFERRAL_BOT_USERNAME = "TradeNeo_bot"
REFERRAL_BOT_URL = f"https://t.me/{REFERRAL_BOT_USERNAME}"


@dataclass
class StartSessionResult:
    user: Dict[str, Any]
    created: bool
    referral_linked: bool = False


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


@dataclass
class ReferralPayoutResult:
    status: str
    user: Optional[Dict[str, Any]] = None
    request: Optional[Dict[str, Any]] = None
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
    def normalize_referral_code(value: Optional[str]) -> str:
        if value is None:
            return ""
        cleaned = str(value).strip()
        if cleaned.lower().startswith("ref_"):
            cleaned = cleaned[4:]
        return cleaned.strip()

    @staticmethod
    def normalize_coinw_uid(value: Optional[str]) -> str:
        if value is None:
            return ""
        return "".join(ch for ch in str(value).strip() if ch.isdigit())

    @staticmethod
    def is_valid_coinw_uid(value: Optional[str]) -> bool:
        normalized = UserTradingService.normalize_coinw_uid(value)
        return normalized.isdigit() and 4 <= len(normalized) <= 32

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

    def get_or_create_user(
        self,
        telegram_id: int,
        first_name: Optional[str],
        referral_code: Optional[str] = None,
    ) -> StartSessionResult:
        nombre_usuario = first_name or "usuario"
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id})
        if usuario_data:
            return StartSessionResult(user=usuario_data, created=False, referral_linked=False)

        UsuarioModel.crear_usuario(
            {
                "telegram_id": telegram_id,
                "nombre": nombre_usuario,
                "codigo_referido": str(telegram_id),
            }
        )
        referral_linked = self._link_referral_if_possible(telegram_id, referral_code)
        usuario_data = UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {
            "telegram_id": telegram_id,
            "nombre": nombre_usuario,
            "codigo_referido": str(telegram_id),
        }
        return StartSessionResult(user=usuario_data, created=True, referral_linked=referral_linked)

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

    def _link_referral_if_possible(self, telegram_id: int, referral_code: Optional[str]) -> bool:
        referral_code = self.normalize_referral_code(referral_code)
        if not referral_code:
            return False

        usuario = self.get_user(telegram_id)
        if not usuario or usuario.get("referidor_id"):
            return False

        if referral_code in {str(telegram_id), str(usuario.get("codigo_referido") or telegram_id)}:
            return False

        referrer = UsuarioModel.obtener_usuario({"codigo_referido": referral_code})
        if not referrer and referral_code.isdigit():
            referrer = UsuarioModel.obtener_usuario({"telegram_id": int(referral_code)})
        if not referrer:
            return False

        referidor_id = int(referrer.get("telegram_id"))
        if referidor_id == int(telegram_id):
            return False

        UsuarioModel.vincular_referidor(telegram_id, referidor_id, referral_code)
        ReferidoModel.vincular_referido(referidor_id, telegram_id, referral_code)
        logger.info(
            "REFERRAL_LINKED | referido_id=%s | referidor_id=%s | referral_code=%s",
            telegram_id,
            referidor_id,
            referral_code,
        )
        return True

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

    @staticmethod
    def _user_sort_datetime(usuario: Dict[str, Any]) -> datetime:
        return usuario.get("updated_at") or usuario.get("created_at") or datetime(1970, 1, 1)

    def _serialize_admin_user_summary(self, usuario: Dict[str, Any]) -> Dict[str, Any]:
        public = self.serialize_user_public(usuario)
        telegram_id = int(public.get("telegram_id") or 0)
        referidos = ReferidoModel.obtener_referidos({"referidor_id": telegram_id}) if telegram_id else []
        active_payout = self.get_active_referral_payout_request(telegram_id) if telegram_id else None
        return {
            "telegram_id": public.get("telegram_id"),
            "nombre": public.get("nombre"),
            "bot_activo": public.get("bot_activo"),
            "trading_enabled": public.get("trading_enabled"),
            "trading_pause_reason": public.get("trading_pause_reason"),
            "fee_status": public.get("fee_status"),
            "has_api_credentials": public.get("has_api_credentials"),
            "capital_total": public.get("capital_total"),
            "capital_activo": public.get("capital_activo"),
            "active_position": bool(public.get("active_position")),
            "last_engine_error": public.get("last_engine_error"),
            "referral_total": len(referidos),
            "referral_available_balance": public.get("referral_available_balance"),
            "referral_coinw_uid": public.get("referral_coinw_uid"),
            "has_active_payout_request": bool(active_payout),
            "updated_at": public.get("updated_at"),
            "created_at": public.get("created_at"),
        }

    def admin_search_users(self, query: Optional[str], limit: int = 20) -> List[Dict[str, Any]]:
        users = UsuarioModel.obtener_todos_usuarios()
        limit = max(1, min(int(limit or 20), 50))
        needle = (query or "").strip()
        if not needle:
            ordered = sorted(users, key=self._user_sort_datetime, reverse=True)[:limit]
            return [self._serialize_admin_user_summary(item) for item in ordered]

        lowered = needle.lower()
        matches = []
        for usuario in users:
            telegram_id = str(usuario.get("telegram_id") or "")
            nombre = str(usuario.get("nombre") or "")
            referral_code = str(usuario.get("codigo_referido") or "")
            referral_uid = str(usuario.get("referral_coinw_uid") or "")
            referred_by = str(usuario.get("referred_by_code") or "")
            score = None
            if telegram_id == needle:
                score = 120
            elif referral_code == needle:
                score = 110
            elif referral_uid == needle:
                score = 100
            elif telegram_id.startswith(needle):
                score = 90
            elif lowered in nombre.lower():
                score = 80
            elif needle in referral_code or needle in referral_uid or needle in referred_by:
                score = 70

            if score is None:
                continue
            matches.append((score, self._user_sort_datetime(usuario), usuario))

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [self._serialize_admin_user_summary(item[2]) for item in matches[:limit]]

    def admin_get_user_detail(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return None

        public = self.serialize_user_public(usuario)
        referrals = self.get_referral_summary(telegram_id)
        fee_invoice = self.get_fee_invoice(telegram_id)
        active_payout = self.get_active_referral_payout_request(telegram_id)
        referrer = None
        if public.get("referidor_id"):
            parent = self.get_user(int(public.get("referidor_id")))
            if parent:
                referrer = {
                    "telegram_id": parent.get("telegram_id"),
                    "nombre": parent.get("nombre"),
                    "codigo_referido": parent.get("codigo_referido"),
                }

        referred_users = []
        for relation in ReferidoModel.obtener_referidos({"referidor_id": telegram_id})[:10]:
            invited_user = self.get_user(int(relation.get("referido_id")))
            referred_users.append({
                "telegram_id": relation.get("referido_id"),
                "nombre": invited_user.get("nombre") if invited_user else f"Usuario {relation.get('referido_id')}",
                "status": relation.get("status"),
                "ganancia_diaria": float(relation.get("ganancia_diaria", 0) or 0),
                "ganancia_acumulada": float(relation.get("ganancia_acumulada", 0) or 0),
                "total_disponible": float(relation.get("total_disponible", 0) or 0),
                "total_pagado": float(relation.get("total_pagado", 0) or 0),
                "last_commission_at": relation.get("last_commission_at"),
                "fecha_registro": relation.get("fecha_registro"),
                "bot_activo": bool(invited_user.get("bot_activo")) if invited_user else False,
                "has_api_credentials": bool(invited_user.get("api_key") and invited_user.get("api_secret")) if invited_user else False,
            })

        payout_requests = []
        for request in ReferralPayoutRequestModel.obtener_requests({"referidor_id": telegram_id}, limit=10):
            payout_requests.append({
                "request_id": request.get("request_id"),
                "status": request.get("status"),
                "amount_requested": float(request.get("amount_requested") or request.get("amount_reserved") or 0),
                "asset": request.get("asset") or PAYMENT_ASSET,
                "coinw_uid": request.get("coinw_uid"),
                "created_at": request.get("created_at"),
                "processed_at": request.get("processed_at"),
                "admin_note": request.get("admin_note"),
            })

        return {
            "user": public,
            "referrals": referrals,
            "referrer": referrer,
            "fee_invoice": fee_invoice,
            "active_payout_request": active_payout,
            "recent_payout_requests": payout_requests,
            "referred_users": referred_users,
            "recent_operations": self.get_recent_operations(telegram_id, limit=5),
            "recent_trade_states": self.get_recent_trade_states(telegram_id, limit=5),
            "recent_trade_events": self.get_recent_trade_events(telegram_id, limit=5),
        }

    def admin_refresh_user_capital(self, telegram_id: int) -> CapitalSnapshotResult:
        return self.refresh_capital(telegram_id)

    def admin_activate_user_bot(self, telegram_id: int) -> BotActivationResult:
        return self.activate_bot(telegram_id)

    def admin_deactivate_user_bot(self, telegram_id: int) -> TradingToggleResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return TradingToggleResult(status="user_not_found")
        self.deactivate_bot(telegram_id)
        return TradingToggleResult(status="deactivated", user=self.get_user(telegram_id) or usuario)

    def admin_pause_user_trading(self, telegram_id: int) -> TradingToggleResult:
        return self.pause_trading(telegram_id)

    def admin_resume_user_trading(self, telegram_id: int) -> TradingToggleResult:
        return self.resume_trading(telegram_id)

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

    def get_active_referral_payout_request(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        return ReferralPayoutRequestModel.obtener_request_activo(telegram_id)

    def save_referral_coinw_uid(self, telegram_id: int, coinw_uid: str) -> ReferralPayoutResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return ReferralPayoutResult(status="user_not_found")

        normalized_uid = self.normalize_coinw_uid(coinw_uid)
        if not self.is_valid_coinw_uid(normalized_uid):
            return ReferralPayoutResult(
                status="invalid_coinw_uid",
                user=usuario,
                reason="Debes introducir un UID válido de CoinW.",
            )

        UsuarioModel.guardar_coinw_uid_referidos(telegram_id, normalized_uid)
        return ReferralPayoutResult(status="coinw_uid_saved", user=self.get_user(telegram_id) or usuario)

    def _payout_request_status(self, usuario: Dict[str, Any]) -> Dict[str, Any]:
        available = float(usuario.get("referral_available_balance", 0) or 0)
        reserved = float(usuario.get("referral_reserved_balance", 0) or 0)
        coinw_uid = usuario.get("referral_coinw_uid")
        active_request = self.get_active_referral_payout_request(int(usuario.get("telegram_id")))
        last_requested_at = usuario.get("referral_last_payout_requested_at")
        can_request = True
        reason = None

        if not self.is_valid_coinw_uid(coinw_uid):
            can_request = False
            reason = "Guarda primero tu UID de CoinW."
        elif active_request:
            can_request = False
            reason = "Ya tienes una solicitud activa en proceso."
        elif available < float(REFERRAL_PAYOUT_MIN_USDT):
            can_request = False
            reason = f"Necesitas al menos {REFERRAL_PAYOUT_MIN_USDT:.2f} {PAYMENT_ASSET} disponibles."
        elif last_requested_at:
            next_allowed_at = last_requested_at + timedelta(hours=REFERRAL_PAYOUT_COOLDOWN_HOURS)
            if datetime.utcnow() < next_allowed_at:
                can_request = False
                reason = f"Debes esperar {REFERRAL_PAYOUT_COOLDOWN_HOURS}h entre solicitudes."

        return {
            "coinw_uid": coinw_uid,
            "minimum_amount": float(REFERRAL_PAYOUT_MIN_USDT),
            "cooldown_hours": int(REFERRAL_PAYOUT_COOLDOWN_HOURS),
            "active_request": active_request,
            "can_request": can_request and reserved <= 0,
            "reason": reason,
            "last_requested_at": last_requested_at,
        }

    def _generate_referral_payout_request_id(self, telegram_id: int) -> str:
        return f"RFP-{telegram_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    def request_referral_payout(self, telegram_id: int) -> ReferralPayoutResult:
        usuario = self.get_user(telegram_id)
        if not usuario:
            return ReferralPayoutResult(status="user_not_found")

        payout_state = self._payout_request_status(usuario)
        if not payout_state["can_request"]:
            return ReferralPayoutResult(
                status="payout_request_blocked",
                user=usuario,
                request=payout_state.get("active_request"),
                reason=payout_state.get("reason") or "No puedes solicitar payout todavía.",
            )

        amount = round(float(usuario.get("referral_available_balance", 0) or 0), 8)
        available_commissions = ReferralCommissionModel.obtener_comisiones_disponibles_referidor(telegram_id)
        if not available_commissions:
            return ReferralPayoutResult(
                status="payout_request_blocked",
                user=usuario,
                reason="No hay comisiones disponibles para reservar.",
            )

        request_id = self._generate_referral_payout_request_id(telegram_id)
        remaining = amount
        reserved_total = 0.0
        reserved_commissions = []
        for commission in available_commissions:
            if remaining <= 0:
                break
            commission_amount = round(float(commission.get("available_amount") or commission.get("commission_amount") or 0.0), 8)
            if commission_amount <= 0:
                continue
            reserve_amount = round(min(commission_amount, remaining), 8)
            ReferralCommissionModel.actualizar_comision(
                {"_id": commission.get("_id")},
                {
                    "payout_status": "reserved",
                    "reserved_amount": reserve_amount,
                    "available_amount": max(commission_amount - reserve_amount, 0.0),
                    "payout_request_id": request_id,
                    "reserved_at": datetime.utcnow(),
                },
            )
            reserved_total = round(reserved_total + reserve_amount, 8)
            remaining = round(remaining - reserve_amount, 8)
            reserved_commissions.append(str(commission.get("_id")))

        if reserved_total <= 0:
            return ReferralPayoutResult(
                status="payout_request_blocked",
                user=usuario,
                reason="No se pudo reservar saldo para el payout.",
            )

        UsuarioModel.reservar_referral_para_payout(telegram_id, reserved_total)
        UsuarioModel.actualizar_usuario(
            {"telegram_id": telegram_id},
            {"referral_last_payout_requested_at": datetime.utcnow()},
        )

        ReferralPayoutRequestModel.registrar_request(
            {
                "request_id": request_id,
                "referidor_id": telegram_id,
                "amount_requested": reserved_total,
                "amount_reserved": reserved_total,
                "coinw_uid": payout_state.get("coinw_uid"),
                "commission_ids": reserved_commissions,
            }
        )
        request = ReferralPayoutRequestModel.obtener_request({"request_id": request_id})
        self.fee_manager.notifier.send(
            telegram_id,
            (
                "💸 Solicitud de payout creada\n\n"
                f"Monto reservado: {reserved_total:.2f} {PAYMENT_ASSET}\n"
                f"UID CoinW: {payout_state.get('coinw_uid')}\n"
                f"Solicitud: {request_id}\n\n"
                "Administración la revisará manualmente."
            ),
        )
        return ReferralPayoutResult(status="payout_requested", user=self.get_user(telegram_id) or usuario, request=request)

    def admin_confirm_referral_payout(self, request_id: str, admin_id: int) -> ReferralPayoutResult:
        request = ReferralPayoutRequestModel.obtener_request({"request_id": request_id})
        if not request or request.get("status") not in {"requested", "processing"}:
            return ReferralPayoutResult(status="request_not_found")

        referidor_id = int(request.get("referidor_id"))
        amount = round(float(request.get("amount_reserved") or request.get("amount_requested") or 0.0), 8)
        commissions = ReferralCommissionModel.obtener_comisiones({"payout_request_id": request_id}, limit=500)
        for commission in commissions:
            reserved_amount = round(float(commission.get("reserved_amount") or commission.get("commission_amount") or 0.0), 8)
            ReferralCommissionModel.actualizar_comision(
                {"_id": commission.get("_id")},
                {
                    "payout_status": "paid",
                    "paid_amount": reserved_amount,
                    "reserved_amount": 0.0,
                    "paid_at": datetime.utcnow(),
                },
            )

        UsuarioModel.confirmar_referral_pagado(referidor_id, amount)
        ReferralPayoutRequestModel.actualizar_request(
            {"request_id": request_id},
            {
                "status": "paid",
                "processed_by": admin_id,
                "processed_at": datetime.utcnow(),
            },
        )
        self.fee_manager.notifier.send(
            referidor_id,
            (
                "✅ Payout de referidos confirmado\n\n"
                f"Monto pagado: {amount:.2f} {PAYMENT_ASSET}\n"
                f"Solicitud: {request_id}\n\n"
                "El saldo ya fue marcado como pagado."
            ),
        )
        return ReferralPayoutResult(
            status="payout_paid",
            user=self.get_user(referidor_id),
            request=ReferralPayoutRequestModel.obtener_request({"request_id": request_id}),
        )

    def admin_reject_referral_payout(self, request_id: str, admin_id: int, reason: Optional[str] = None) -> ReferralPayoutResult:
        request = ReferralPayoutRequestModel.obtener_request({"request_id": request_id})
        if not request or request.get("status") not in {"requested", "processing"}:
            return ReferralPayoutResult(status="request_not_found")

        referidor_id = int(request.get("referidor_id"))
        amount = round(float(request.get("amount_reserved") or request.get("amount_requested") or 0.0), 8)
        commissions = ReferralCommissionModel.obtener_comisiones({"payout_request_id": request_id}, limit=500)
        for commission in commissions:
            reserved_amount = round(float(commission.get("reserved_amount") or commission.get("commission_amount") or 0.0), 8)
            ReferralCommissionModel.actualizar_comision(
                {"_id": commission.get("_id")},
                {
                    "payout_status": "available",
                    "available_amount": reserved_amount,
                    "reserved_amount": 0.0,
                    "payout_request_id": None,
                    "rejected_at": datetime.utcnow(),
                },
            )

        UsuarioModel.revertir_reserva_referral(referidor_id, amount)
        ReferralPayoutRequestModel.actualizar_request(
            {"request_id": request_id},
            {
                "status": "rejected",
                "processed_by": admin_id,
                "processed_at": datetime.utcnow(),
                "admin_note": reason or "Solicitud rechazada por administración",
            },
        )
        self.fee_manager.notifier.send(
            referidor_id,
            (
                "❌ Payout de referidos rechazado\n\n"
                f"Solicitud: {request_id}\n"
                f"Motivo: {reason or 'Solicitud rechazada por administración'}\n\n"
                "El saldo reservado volvió a estar disponible."
            ),
        )
        return ReferralPayoutResult(
            status="payout_rejected",
            user=self.get_user(referidor_id),
            request=ReferralPayoutRequestModel.obtener_request({"request_id": request_id}),
        )

    def get_referral_summary(self, telegram_id: int) -> Dict[str, Any]:
        usuario = self.get_user(telegram_id) or {}
        referidos = ReferidoModel.obtener_referidos({"referidor_id": telegram_id})
        referidos_activos = [item for item in referidos if item.get("status") == "linked"]
        codigo_referido = str(usuario.get("codigo_referido") or telegram_id)
        enlace_referido = f"{REFERRAL_BOT_URL}?start={quote(codigo_referido)}"
        payout_state = self._payout_request_status(usuario) if usuario else {
            "coinw_uid": None,
            "minimum_amount": float(REFERRAL_PAYOUT_MIN_USDT),
            "cooldown_hours": int(REFERRAL_PAYOUT_COOLDOWN_HOURS),
            "active_request": None,
            "can_request": False,
            "reason": "Usuario no encontrado",
            "last_requested_at": None,
        }
        return {
            "codigo_referido": codigo_referido,
            "enlace_referido": enlace_referido,
            "bot_username": REFERRAL_BOT_USERNAME,
            "ganancia_diaria": float(usuario.get("ganancia_diaria_referidos", 0) or 0),
            "ganancia_acumulada": float(usuario.get("ganancia_acumulada_referidos", 0) or 0),
            "saldo_pendiente": float(usuario.get("referral_pending_balance", 0) or 0),
            "saldo_disponible": float(usuario.get("referral_available_balance", 0) or 0),
            "saldo_reservado": float(usuario.get("referral_reserved_balance", 0) or 0),
            "saldo_pagado": float(usuario.get("referral_paid_total", 0) or 0),
            "referidos_activos": len(referidos_activos),
            "referidos_totales": len(referidos),
            "referidos": referidos,
            "coinw_uid": payout_state.get("coinw_uid"),
            "minimum_amount": payout_state.get("minimum_amount"),
            "cooldown_hours": payout_state.get("cooldown_hours"),
            "active_payout_request": payout_state.get("active_request"),
            "has_active_payout_request": bool(payout_state.get("active_request")),
            "can_request_payout": payout_state.get("can_request"),
            "payout_request_reason": payout_state.get("reason"),
            "last_requested_at": payout_state.get("last_requested_at"),
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
            "referidor_id": usuario.get("referidor_id"),
            "referred_by_code": usuario.get("referred_by_code"),
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
            "referral_pending_balance": float(usuario.get("referral_pending_balance", 0) or 0),
            "referral_available_balance": float(usuario.get("referral_available_balance", 0) or 0),
            "referral_reserved_balance": float(usuario.get("referral_reserved_balance", 0) or 0),
            "referral_paid_total": float(usuario.get("referral_paid_total", 0) or 0),
            "referral_coinw_uid": usuario.get("referral_coinw_uid"),
            "referral_last_payout_requested_at": usuario.get("referral_last_payout_requested_at"),
            "ganancia_diaria_referidos": float(usuario.get("ganancia_diaria_referidos", 0) or 0),
            "ganancia_acumulada_referidos": float(usuario.get("ganancia_acumulada_referidos", 0) or 0),
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
