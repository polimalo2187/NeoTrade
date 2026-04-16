import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from app.config import (
    ADMIN_TELEGRAM_IDS,
    MINI_APP_SESSION_SECRET,
    MINI_APP_SESSION_TTL_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
)


logger = logging.getLogger(__name__)


class TelegramInitDataError(ValueError):
    pass


class SessionTokenError(ValueError):
    pass


@dataclass
class TelegramWebAppIdentity:
    telegram_id: int
    first_name: str
    username: Optional[str]
    auth_date: int
    raw_user: Dict[str, Any]
    is_admin: bool


class TelegramWebAppAuthVerifier:
    @staticmethod
    def verify(init_data: str) -> TelegramWebAppIdentity:
        if not TELEGRAM_BOT_TOKEN:
            raise TelegramInitDataError(
                "TELEGRAM_BOT_TOKEN no está configurado. No se puede validar Telegram WebApp initData."
            )
        if not init_data or not init_data.strip():
            raise TelegramInitDataError("initData vacío")

        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise TelegramInitDataError("initData no contiene hash")

        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise TelegramInitDataError("hash inválido en initData")

        auth_date_raw = pairs.get("auth_date")
        if not auth_date_raw:
            raise TelegramInitDataError("initData no contiene auth_date")

        try:
            auth_date = int(auth_date_raw)
        except (TypeError, ValueError) as exc:
            raise TelegramInitDataError("auth_date inválido") from exc

        now = int(time.time())
        age = now - auth_date
        if age < 0:
            raise TelegramInitDataError("auth_date está en el futuro")
        if age > TELEGRAM_INIT_DATA_MAX_AGE_SECONDS:
            raise TelegramInitDataError("initData expirado")

        user_raw = pairs.get("user")
        if not user_raw:
            raise TelegramInitDataError("initData no contiene user")

        try:
            user = json.loads(user_raw)
        except json.JSONDecodeError as exc:
            raise TelegramInitDataError("user inválido en initData") from exc

        telegram_id = int(user.get("id") or 0)
        if telegram_id <= 0:
            raise TelegramInitDataError("ID de usuario inválido")

        return TelegramWebAppIdentity(
            telegram_id=telegram_id,
            first_name=(user.get("first_name") or "usuario").strip() or "usuario",
            username=user.get("username"),
            auth_date=auth_date,
            raw_user=user,
            is_admin=telegram_id in ADMIN_TELEGRAM_IDS,
        )


class MiniAppSessionManager:
    @staticmethod
    def _secret() -> str:
        secret = (MINI_APP_SESSION_SECRET or TELEGRAM_BOT_TOKEN or "").strip()
        if not secret:
            raise SessionTokenError(
                "Configure MINI_APP_SESSION_SECRET o TELEGRAM_BOT_TOKEN para firmar sesiones de Mini App."
            )
        return secret

    @staticmethod
    def issue(identity: TelegramWebAppIdentity) -> Dict[str, Any]:
        now = int(time.time())
        expires_at = now + MINI_APP_SESSION_TTL_SECONDS
        payload = {
            "telegram_id": identity.telegram_id,
            "first_name": identity.first_name,
            "username": identity.username,
            "is_admin": identity.is_admin,
            "iat": now,
            "exp": expires_at,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_json).rstrip(b"=")
        signature = hmac.new(
            MiniAppSessionManager._secret().encode("utf-8"),
            payload_b64,
            hashlib.sha256,
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
        token = payload_b64.decode("utf-8") + "." + signature_b64.decode("utf-8")
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": MINI_APP_SESSION_TTL_SECONDS,
            "expires_at": expires_at,
            "payload": payload,
        }

    @staticmethod
    def verify(token: str) -> Dict[str, Any]:
        if not token or "." not in token:
            raise SessionTokenError("Token inválido")
        payload_part, signature_part = token.split(".", 1)
        expected_signature = hmac.new(
            MiniAppSessionManager._secret().encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).rstrip(b"=").decode("utf-8")
        if not hmac.compare_digest(expected_signature_b64, signature_part):
            raise SessionTokenError("Firma de token inválida")

        padding = "=" * (-len(payload_part) % 4)
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_part + padding)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise SessionTokenError("No se pudo decodificar el token") from exc

        now = int(time.time())
        exp = int(payload.get("exp") or 0)
        if exp <= 0 or now >= exp:
            raise SessionTokenError("Token expirado")
        return payload
