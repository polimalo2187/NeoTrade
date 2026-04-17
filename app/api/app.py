import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import API_PREFIX, ADMIN_TELEGRAM_IDS, ENABLE_API_SERVER, MINI_APP_URL
from app.mensajes import mensaje_fee
from app.models import OperacionModel, PaymentInvoiceModel, UsuarioModel
from app.services.user_trading_service import TradingToggleResult, UserTradingService
from .security import (
    MiniAppSessionManager,
    SessionTokenError,
    TelegramInitDataError,
    TelegramWebAppAuthVerifier,
)


logger = logging.getLogger(__name__)
service = UserTradingService()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
WEB_ASSETS_DIR = WEB_DIR / "assets"
WEB_INDEX_FILE = WEB_DIR / "index.html"


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            data,
            custom_encoder={
                ObjectId: str,
                datetime: lambda value: value.isoformat(),
            },
        ),
    )


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(..., description="Cadena raw initData enviada por Telegram WebApp")


class ApiCredentialsRequest(BaseModel):
    api_key: str
    api_secret: str


class FeeReportRequest(BaseModel):
    report_text: str = Field(..., min_length=3, max_length=4000)


class AuthenticatedUser(BaseModel):
    telegram_id: int
    first_name: str
    username: Optional[str] = None
    is_admin: bool = False


class AppInfoResponse(BaseModel):
    api_enabled: bool
    mini_app_url: str
    api_prefix: str
    admin_ids_configured: int


class RootResponse(BaseModel):
    service: str
    status: str
    docs: str
    api_prefix: str
    mini_app_url: str


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta encabezado Authorization")
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization debe ser Bearer <token>")
    return parts[1].strip()


def get_current_user(authorization: Optional[str] = Header(default=None)) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    try:
        payload = MiniAppSessionManager.verify(token)
        return AuthenticatedUser(**payload)
    except SessionTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def get_admin_user(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requieren permisos de administrador")
    return current_user


def _web_index_response() -> FileResponse:
    if not WEB_INDEX_FILE.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se encontró index.html de Mini App")
    return FileResponse(
        WEB_INDEX_FILE,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def create_api_app() -> FastAPI:
    app = FastAPI(
        title="NeoTrade Mini App API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    if WEB_ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(WEB_ASSETS_DIR)), name="assets")
    else:
        logger.warning("No se encontró directorio de assets web: %s", WEB_ASSETS_DIR)

    @app.get("/", include_in_schema=False)
    def root():
        return _web_index_response()

    @app.get("/app", include_in_schema=False)
    def mini_app_shell():
        return _web_index_response()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon_path = WEB_ASSETS_DIR / "logo-mark.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
        return Response(status_code=204)

    @app.get(f"{API_PREFIX}/root", response_model=RootResponse)
    def root_info():
        return RootResponse(
            service="NeoTrade Mini App API",
            status="ok",
            docs="/docs",
            api_prefix=API_PREFIX,
            mini_app_url=MINI_APP_URL,
        )

    @app.get(f"{API_PREFIX}/health")
    def health():
        return _json({"status": "ok", "service": "api", "api_enabled": ENABLE_API_SERVER})

    @app.get(f"{API_PREFIX}/app-info", response_model=AppInfoResponse)
    def app_info():
        return AppInfoResponse(
            api_enabled=ENABLE_API_SERVER,
            mini_app_url=MINI_APP_URL,
            api_prefix=API_PREFIX,
            admin_ids_configured=len(ADMIN_TELEGRAM_IDS),
        )

    @app.post(f"{API_PREFIX}/auth/telegram")
    def auth_telegram(payload: TelegramAuthRequest):
        try:
            identity = TelegramWebAppAuthVerifier.verify(payload.init_data)
        except TelegramInitDataError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

        service.ensure_web_session_user(identity.telegram_id, identity.first_name)
        session = MiniAppSessionManager.issue(identity)
        return _json(
            {
                "access_token": session["access_token"],
                "token_type": session["token_type"],
                "expires_in": session["expires_in"],
                "expires_at": session["expires_at"],
                "user": session["payload"],
            }
        )

    @app.get(f"{API_PREFIX}/me")
    def me(current_user: AuthenticatedUser = Depends(get_current_user)):
        user = service.get_user(current_user.telegram_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        return _json({"user": service.serialize_user_public(user)})

    @app.get(f"{API_PREFIX}/me/dashboard")
    def me_dashboard(
        operations_limit: int = 10,
        events_limit: int = 10,
        refresh_capital: bool = False,
        current_user: AuthenticatedUser = Depends(get_current_user),
    ):
        operations_limit = max(1, min(operations_limit, 50))
        events_limit = max(1, min(events_limit, 50))
        snapshot = service.get_dashboard_snapshot(
            current_user.telegram_id,
            operations_limit=operations_limit,
            events_limit=events_limit,
            refresh_capital=refresh_capital,
        )
        return _json(snapshot)

    @app.get(f"{API_PREFIX}/me/capital")
    def me_capital(current_user: AuthenticatedUser = Depends(get_current_user)):
        result = service.refresh_capital(current_user.telegram_id)
        if result.status == "user_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        return _json(
            {
                "status": result.status,
                "reason": result.reason,
                "user": service.serialize_user_public(result.user or {}),
            }
        )

    @app.get(f"{API_PREFIX}/me/history")
    def me_history(limit: int = 10, current_user: AuthenticatedUser = Depends(get_current_user)):
        limit = max(1, min(limit, 50))
        return _json(
            {
                "operations": service.get_recent_operations(current_user.telegram_id, limit=limit),
                "trade_states": service.get_recent_trade_states(current_user.telegram_id, limit=limit),
                "trade_events": service.get_recent_trade_events(current_user.telegram_id, limit=limit),
            }
        )

    @app.get(f"{API_PREFIX}/me/referrals")
    def me_referrals(current_user: AuthenticatedUser = Depends(get_current_user)):
        return _json(service.get_referral_summary(current_user.telegram_id))

    @app.get(f"{API_PREFIX}/me/fee")
    def me_fee(current_user: AuthenticatedUser = Depends(get_current_user)):
        user = service.get_user(current_user.telegram_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        invoice = service.get_fee_invoice(current_user.telegram_id)
        return _json(
            {
                "invoice": invoice,
                "message": mensaje_fee(user, invoice),
                "user": service.serialize_user_public(user),
            }
        )

    @app.post(f"{API_PREFIX}/me/fee/report")
    def me_fee_report(payload: FeeReportRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
        invoice = service.get_fee_invoice(current_user.telegram_id)
        if not invoice:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay factura activa para reportar")
        service.begin_fee_report(current_user.telegram_id)
        result = service.process_stateful_message(current_user.telegram_id, payload.report_text)
        if result.status != "fee_reported":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason or result.status)
        return _json({"status": result.status, "invoice": result.invoice})

    @app.post(f"{API_PREFIX}/me/credentials")
    def me_credentials(payload: ApiCredentialsRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
        result = service.set_api_credentials(current_user.telegram_id, payload.api_key, payload.api_secret)
        if result.status == "user_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        if result.status in {"missing_credentials", "api_invalid"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason or result.status)
        return _json({"status": result.status, "user": service.serialize_user_public(result.user or {})})

    @app.post(f"{API_PREFIX}/me/bot/activate")
    def me_bot_activate(current_user: AuthenticatedUser = Depends(get_current_user)):
        result = service.activate_bot(current_user.telegram_id)
        if result.status == "user_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        if result.status == "missing_credentials":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Faltan API Key y API Secret")
        if result.status == "empty_spot_balance":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason or "Cuenta Spot vacía")
        return _json(
            {
                "status": result.status,
                "capital_total": result.capital_total,
                "available_quote": result.available_quote,
                "invoice": result.invoice,
                "user": service.serialize_user_public(result.user or {}),
            }
        )

    @app.post(f"{API_PREFIX}/me/bot/deactivate")
    def me_bot_deactivate(current_user: AuthenticatedUser = Depends(get_current_user)):
        user = service.get_user(current_user.telegram_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        service.deactivate_bot(current_user.telegram_id)
        return _json({"status": "deactivated"})

    @app.post(f"{API_PREFIX}/me/trading/pause")
    def me_trading_pause(current_user: AuthenticatedUser = Depends(get_current_user)):
        result = service.pause_trading(current_user.telegram_id)
        if result.status == "user_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        if result.status == "fee_locked":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason or "Trading bloqueado por fee pendiente")
        return _json({"status": result.status, "user": service.serialize_user_public(result.user or {})})

    @app.post(f"{API_PREFIX}/me/trading/resume")
    def me_trading_resume(current_user: AuthenticatedUser = Depends(get_current_user)):
        result = service.resume_trading(current_user.telegram_id)
        if result.status == "user_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        if result.status == "fee_locked":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason or "Trading bloqueado por fee pendiente")
        return _json({
            "status": result.status,
            "invoice": result.invoice,
            "user": service.serialize_user_public(result.user or {}),
        })

    @app.get(f"{API_PREFIX}/admin/summary")
    def admin_summary(current_admin: AuthenticatedUser = Depends(get_admin_user)):
        usuarios = UsuarioModel.obtener_todos_usuarios()
        activos = [u for u in usuarios if u.get("bot_activo")]
        bloqueados_fee = [u for u in usuarios if u.get("trading_pause_reason") == "fee_due"]
        capital_total = sum(float(u.get("capital_total", 0) or 0) for u in usuarios)
        pending_invoices = PaymentInvoiceModel.obtener_facturas({"status": {"$in": ["pending", "reported"]}}, limit=20)
        recent_operations = OperacionModel.obtener_operaciones({}, limit=10)
        return _json(
            {
                "admin": current_admin.model_dump(),
                "users": {
                    "total": len(usuarios),
                    "active_bot": len(activos),
                    "blocked_fee": len(bloqueados_fee),
                    "capital_total_estimated": capital_total,
                },
                "pending_invoices": pending_invoices,
                "recent_operations": recent_operations,
            }
        )

    return app
