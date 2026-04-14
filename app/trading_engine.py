import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from app.config import (
    CAPITAL_ACTIVO_PORC,
    CANDLE_LIMIT,
    DEFAULT_SYMBOLS,
    DRY_RUN,
    ENABLE_TRADING_ENGINE,
    ENTRY_PERIOD_SECONDS,
    MANAGER_REPLAY_MAX_CANDLES,
    MIN_24H_QUOTE_VOLUME,
    MIN_USDT_ORDER,
    MAX_SYMBOLS_TO_SCAN,
    PARALLEL_SCAN_WORKERS,
    PULLBACK_PERIOD_SECONDS,
    QUOTE_ASSET,
    SCAN_INTERVAL_SECONDS,
    SYMBOL_REFRESH_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TREND_PERIOD_SECONDS,
)
from app.exchange import CoinWApiError, ExchangeClient
from app.fee_manager import FeeManager
from app.models import OperacionModel, TradeEventModel, TradeStateModel, UsuarioModel
from app.mtf_strategy import MTFStrategy


logger = logging.getLogger(__name__)


class TelegramNotifier:
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


class TradingEngine:
    @staticmethod
    def _fmt(value: object, decimals: int = 8) -> str:
        try:
            return f"{float(value):.{decimals}f}"
        except Exception:
            return str(value)

    @staticmethod
    def _user_name(usuario: Dict) -> str:
        return str(usuario.get("nombre") or usuario.get("telegram_id"))

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso_now() -> str:
        return TradingEngine._utc_now().isoformat()

    @staticmethod
    def _iso_to_ms(value: Optional[str], fallback_ms: int) -> int:
        if not value:
            return fallback_ms
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return fallback_ms

    @staticmethod
    def _format_reason_counts(reason_counts: Dict[str, int]) -> str:
        if not reason_counts:
            return "none"
        ordered = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(f"{reason}:{count}" for reason, count in ordered)

    @staticmethod
    def _serialize_scan_detail(detail: Dict[str, Any]) -> str:
        if not detail:
            return "none"
        parts = []
        for key, value in list(detail.items())[:6]:
            if isinstance(value, dict):
                nested_parts = []
                for nested_key, nested_value in list(value.items())[:4]:
                    nested_parts.append(f"{nested_key}={nested_value}")
                parts.append(f"{key}({'; '.join(nested_parts)})")
            elif isinstance(value, list):
                preview = ",".join(str(item) for item in value[:4])
                parts.append(f"{key}=[{preview}]")
            else:
                parts.append(f"{key}={value}")
        return "; ".join(parts) if parts else "none"

    @staticmethod
    def _format_scan_samples(samples: List[str], limit: int = 5) -> str:
        if not samples:
            return "none"
        return " | ".join(samples[:limit])

    def __init__(self):
        self.strategy = MTFStrategy()
        self.notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN)
        self.fee_manager = FeeManager()
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._last_symbols_refresh = 0.0
        self._cached_symbols: List[str] = []
        self._symbol_rules: Dict[str, object] = {}
        self._public_client = ExchangeClient()
        self._thread_local = threading.local()
        self._kline_cache_lock = threading.Lock()
        self._kline_cache: Dict[tuple, Dict[str, Any]] = {}
        self._market_scan_cache: Optional[Dict[str, Any]] = None

    def start(self):
        if not ENABLE_TRADING_ENGINE:
            logger.info("Motor de trading deshabilitado por configuración.")
            return
        if self.running:
            return
        recovered = TradeStateModel.obtener_estados({"status": "OPEN"}, limit=200)
        if recovered:
            logger.info("RECOVERY_INIT | estados_abiertos_recuperados=%s", len(recovered))
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="trading-engine")
        self._thread.start()
        logger.info(
            "Motor de trading iniciado. | dry_run=%s | scan_interval=%ss | quote_asset=%s | min_usdt_order=%s | max_symbols=%s | parallel_scan_workers=%s",
            DRY_RUN,
            SCAN_INTERVAL_SECONDS,
            QUOTE_ASSET,
            MIN_USDT_ORDER,
            MAX_SYMBOLS_TO_SCAN,
            PARALLEL_SCAN_WORKERS,
        )

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            started = time.time()
            try:
                self._cycle()
            except Exception:
                logger.exception("Fallo no controlado en motor de trading")
            elapsed = time.time() - started
            sleep_seconds = max(2, SCAN_INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_seconds)

    def _cycle(self):
        usuarios = UsuarioModel.obtener_usuarios_para_engine()
        if not usuarios:
            logger.info("ENGINE_CYCLE_IDLE | motivo=no_active_users")
            return

        candidate_symbols = self._get_candidate_symbols()
        idle_users = [usuario for usuario in usuarios if not usuario.get("active_position")]
        market_scan = self._get_market_scan(candidate_symbols) if idle_users else self._empty_market_scan(candidate_symbols)
        logger.info(
            "ENGINE_CYCLE_START | usuarios=%s | symbols=%s | dry_run=%s | idle_users=%s | accepted_signals=%s",
            len(usuarios),
            len(candidate_symbols),
            DRY_RUN,
            len(idle_users),
            len(market_scan.get("accepted_signals") or []),
        )
        for usuario in usuarios:
            telegram_id = usuario["telegram_id"]
            try:
                client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
                self._refresh_user_capital_snapshot(usuario, client)
                active_position = usuario.get("active_position")
                if active_position:
                    logger.info(
                        "ENGINE_USER_MANAGE | telegram_id=%s | symbol=%s | trade_id=%s",
                        telegram_id,
                        active_position.get("symbol"),
                        active_position.get("trade_id") or active_position.get("order_number"),
                    )
                    self._manage_open_position(usuario, client)
                else:
                    existing_invoice = self.fee_manager.ensure_invoice_if_threshold_reached(telegram_id)
                    if existing_invoice:
                        logger.warning(
                            "SCAN_SKIPPED_FEE_LOCK | telegram_id=%s | invoice_id=%s | amount=%s %s",
                            telegram_id,
                            existing_invoice.get("invoice_id"),
                            self._fmt(existing_invoice.get("invoice_amount"), 2),
                            existing_invoice.get("asset") or QUOTE_ASSET,
                        )
                        continue
                    self._open_trade_from_market_scan(usuario, client, market_scan)
                UsuarioModel.actualizar_engine_error(telegram_id, None)
            except CoinWApiError as exc:
                logger.warning("Usuario %s | CoinW error: %s", telegram_id, exc)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))
            except Exception as exc:
                logger.exception("Usuario %s | error inesperado", telegram_id)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))

    def _refresh_user_capital_snapshot(self, usuario: Dict, client: ExchangeClient) -> None:
        capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
        capital_total = float(capital["capital_total_estimated"])
        capital_activo = capital_total * CAPITAL_ACTIVO_PORC
        UsuarioModel.actualizar_capital_snapshot(usuario["telegram_id"], capital_total, capital_activo)

    def _get_candidate_symbols(self) -> List[str]:
        now = time.time()
        if self._cached_symbols and now - self._last_symbols_refresh < SYMBOL_REFRESH_SECONDS:
            return self._cached_symbols

        self._symbol_rules = self._public_client.obtener_info_instrumentos()
        if DEFAULT_SYMBOLS:
            requested_symbols = [symbol.upper() for symbol in DEFAULT_SYMBOLS]
            if MAX_SYMBOLS_TO_SCAN > 0:
                requested_symbols = requested_symbols[:MAX_SYMBOLS_TO_SCAN]
        else:
            requested_symbols = self._public_client.obtener_pares_disponibles(
                volumen_minimo=MIN_24H_QUOTE_VOLUME,
                quote_asset=QUOTE_ASSET,
                max_pairs=MAX_SYMBOLS_TO_SCAN if MAX_SYMBOLS_TO_SCAN > 0 else None,
            )

        self._cached_symbols = [
            symbol for symbol in requested_symbols
            if symbol in self._symbol_rules and self._symbol_rules[symbol].state == 1
        ]
        self._last_symbols_refresh = now
        self._market_scan_cache = None
        logger.info(
            "SYMBOLS_REFRESH | requested=%s | available_with_rules=%s | top_symbols=%s",
            len(requested_symbols),
            len(self._cached_symbols),
            self._cached_symbols[:12],
        )
        return self._cached_symbols

    def _empty_market_scan(self, symbols: List[str]) -> Dict[str, Any]:
        return {
            "accepted_signals": [],
            "accepted_count": 0,
            "reason_counts": {},
            "samples": [],
            "symbols": list(symbols),
            "generated_at": self._iso_now(),
            "duration_seconds": 0.0,
            "cache": False,
        }

    def _market_scan_cache_key(self, symbols: List[str]) -> tuple:
        now_ms = int(time.time() * 1000)
        period_ms = ENTRY_PERIOD_SECONDS * 1000
        last_closed_candle_ms = now_ms - (now_ms % period_ms) - period_ms
        return (tuple(symbols), last_closed_candle_ms)

    def _get_market_scan(self, symbols: List[str]) -> Dict[str, Any]:
        if not symbols:
            return self._empty_market_scan(symbols)

        cache_key = self._market_scan_cache_key(symbols)
        cached = self._market_scan_cache
        if cached and cached.get("cache_key") == cache_key:
            return cached["payload"]

        payload = self._scan_market(symbols)
        self._market_scan_cache = {"cache_key": cache_key, "payload": payload}
        return payload

    def _scan_market(self, symbols: List[str]) -> Dict[str, Any]:
        started = time.time()
        logger.info(
            "MARKET_SCAN_START | symbols=%s | parallel_scan_workers=%s",
            len(symbols),
            PARALLEL_SCAN_WORKERS,
        )
        accepted_signals: List[Dict[str, Any]] = []
        reason_counts: Counter = Counter()
        samples: List[str] = []

        max_workers = max(1, min(PARALLEL_SCAN_WORKERS, len(symbols)))
        if max_workers == 1:
            evaluations = ((symbol, self._evaluate_symbol(symbol)) for symbol in symbols)
            for symbol, evaluation in evaluations:
                self._consume_market_evaluation(symbol, evaluation, accepted_signals, reason_counts, samples)
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scan") as pool:
                future_to_symbol = {pool.submit(self._evaluate_symbol, symbol): symbol for symbol in symbols}
                for future in as_completed(future_to_symbol):
                    symbol = future_to_symbol[future]
                    try:
                        evaluation = future.result()
                    except Exception as exc:
                        evaluation = {
                            "accepted": False,
                            "reason": "DATA_OR_EVAL_ERROR",
                            "detail": {"error": str(exc)},
                            "signal": None,
                        }
                    self._consume_market_evaluation(symbol, evaluation, accepted_signals, reason_counts, samples)

        accepted_signals.sort(key=lambda item: (-float(item.get("score") or 0.0), item.get("symbol") or ""))
        duration_seconds = round(time.time() - started, 3)
        logger.info(
            "MARKET_SCAN_RESULT | symbols=%s | accepted_signals=%s | rejection_summary=%s | top_candidates=%s | duration_seconds=%s",
            len(symbols),
            len(accepted_signals),
            self._format_reason_counts(dict(reason_counts)),
            self._format_scan_samples([f"{signal['symbol']}:OK[score={signal.get('score')}; entry={signal.get('entry_price')}]" for signal in accepted_signals], limit=5),
            duration_seconds,
        )
        return {
            "accepted_signals": accepted_signals,
            "accepted_count": len(accepted_signals),
            "reason_counts": dict(reason_counts),
            "samples": samples,
            "symbols": list(symbols),
            "generated_at": self._iso_now(),
            "duration_seconds": duration_seconds,
            "cache": False,
        }

    def _consume_market_evaluation(
        self,
        symbol: str,
        evaluation: Dict[str, Any],
        accepted_signals: List[Dict[str, Any]],
        reason_counts: Counter,
        samples: List[str],
    ) -> None:
        if not evaluation.get("accepted"):
            reason = evaluation.get("reason") or "UNKNOWN"
            reason_counts[reason] += 1
            if len(samples) < 8:
                samples.append(f"{symbol}:{reason}[{self._serialize_scan_detail(evaluation.get('detail') or {})}]")
            return

        signal = evaluation["signal"]
        accepted_signals.append(signal)
        if len(samples) < 8:
            samples.append(f"{symbol}:OK[score={signal.get('score')}; entry={signal.get('entry_price')}]")

    def _open_trade_from_market_scan(self, usuario: Dict, client: ExchangeClient, market_scan: Dict[str, Any]) -> None:
        telegram_id = usuario["telegram_id"]
        available_quote = client.obtener_balance_disponible(QUOTE_ASSET)
        symbols = market_scan.get("symbols") or []
        accepted_signals = market_scan.get("accepted_signals") or []
        reason_counts = market_scan.get("reason_counts") or {}
        samples = market_scan.get("samples") or []

        logger.info(
            "SCAN_START | telegram_id=%s | usuario=%s | symbols=%s | balance_disponible=%s %s | min_usdt_order=%s | capital_activo_porc=%s | market_scan_age=%s",
            telegram_id,
            self._user_name(usuario),
            len(symbols),
            self._fmt(available_quote),
            QUOTE_ASSET,
            self._fmt(MIN_USDT_ORDER, 2),
            CAPITAL_ACTIVO_PORC,
            market_scan.get("generated_at"),
        )
        if available_quote < Decimal(str(MIN_USDT_ORDER)):
            logger.warning(
                "SCAN_SKIPPED_LOW_BALANCE | telegram_id=%s | balance_disponible=%s %s | min_usdt_order=%s",
                telegram_id,
                self._fmt(available_quote),
                QUOTE_ASSET,
                self._fmt(MIN_USDT_ORDER, 2),
            )
            return

        if not accepted_signals:
            logger.info(
                "SCAN_RESULT_NO_ENTRY | telegram_id=%s | usuario=%s | symbols=%s | accepted_signals=%s | rejection_summary=%s | samples=%s",
                telegram_id,
                self._user_name(usuario),
                len(symbols),
                0,
                self._format_reason_counts(reason_counts),
                self._format_scan_samples(samples),
            )
            return

        quote_to_use = (available_quote * Decimal(str(CAPITAL_ACTIVO_PORC))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        best_signal = None
        blocked_symbols: List[str] = []
        for signal in accepted_signals:
            rule = self._symbol_rules.get(signal["symbol"])
            if not rule:
                continue
            min_required = max(rule.min_buy_amount, Decimal(str(MIN_USDT_ORDER)))
            if quote_to_use < min_required:
                blocked_symbols.append(f"{signal['symbol']}[required={self._fmt(min_required)}]")
                continue
            best_signal = signal
            break

        if not best_signal:
            logger.warning(
                "SCAN_BLOCKED_MIN_NOTIONAL | telegram_id=%s | usuario=%s | quote_to_use=%s %s | accepted_signals=%s | blocked_symbols=%s",
                telegram_id,
                self._user_name(usuario),
                self._fmt(quote_to_use),
                QUOTE_ASSET,
                len(accepted_signals),
                " | ".join(blocked_symbols[:5]) if blocked_symbols else "none",
            )
            return

        logger.info(
            "SCAN_RESULT_CANDIDATE | telegram_id=%s | usuario=%s | symbols=%s | accepted_signals=%s | best_symbol=%s | best_score=%s | best_entry=%s | rejection_summary=%s | samples=%s",
            telegram_id,
            self._user_name(usuario),
            len(symbols),
            len(accepted_signals),
            best_signal["symbol"],
            self._fmt(best_signal["score"], 2),
            self._fmt(best_signal["entry_price"]),
            self._format_reason_counts(reason_counts),
            self._format_scan_samples(samples),
        )

        rule = self._symbol_rules[best_signal["symbol"]]
        quote_to_use = (available_quote * Decimal(str(CAPITAL_ACTIVO_PORC))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        min_required = max(rule.min_buy_amount, Decimal(str(MIN_USDT_ORDER)))
        if quote_to_use < min_required:
            logger.warning(
                "SCAN_BLOCKED_MIN_NOTIONAL | telegram_id=%s | symbol=%s | quote_to_use=%s %s | min_required=%s %s | exchange_min_buy_amount=%s",
                telegram_id,
                best_signal["symbol"],
                self._fmt(quote_to_use),
                rule.quote_asset,
                self._fmt(min_required),
                rule.quote_asset,
                self._fmt(rule.min_buy_amount),
            )
            return

        fallback_price = Decimal(str(best_signal["entry_price"]))
        if DRY_RUN:
            amount = (quote_to_use / fallback_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            order_number = f"dry-run-{int(time.time())}"
        else:
            order = client.crear_orden_mercado_buy(best_signal["symbol"], quote_to_use, rule)
            order_number = str(order["orderNumber"])
            status = client.obtener_estado_orden(order_number)
            fill = client.estimar_fill_desde_estado(status, fallback_price=fallback_price)
            amount = fill["amount"]
            fallback_price = fill["avg_price"] or fallback_price
            if amount <= 0 and fallback_price > 0:
                amount = (quote_to_use / fallback_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        trade_id = f"{telegram_id}-{order_number}"
        position = self._build_new_position(usuario, rule, best_signal, order_number, fallback_price, amount, quote_to_use, trade_id)
        self._persist_trade_state(telegram_id, position)
        TradeEventModel.registrar_evento(trade_id, telegram_id, "ENTRY_FILLED", {
            "symbol": best_signal["symbol"],
            "entry_price": float(fallback_price),
            "quantity": float(amount),
            "quote_used": float(quote_to_use),
        })
        UsuarioModel.incrementar_stats(telegram_id, {"opened": 1})
        OperacionModel.registrar_operacion(
            {
                "telegram_id": telegram_id,
                "trade_id": trade_id,
                "symbol": best_signal["symbol"],
                "side": "LONG",
                "status": "OPEN",
                "entry_price": float(fallback_price),
                "initial_stop_loss": float(best_signal["initial_stop_loss"]),
                "dynamic_tp_activation_price": float(best_signal["dynamic_tp_activation_price"]),
                "score": float(best_signal["score"]),
                "quantity": float(amount),
                "quote_amount": float(quote_to_use),
                "order_number": order_number,
                "opened_at": datetime.utcnow(),
                "quote_asset": rule.quote_asset,
                "base_asset": rule.base_asset,
                "components": best_signal["components"],
                "manager_rules": best_signal["manager_rules"],
                "strategy_meta": best_signal.get("strategy_meta") or {},
            }
        )
        logger.info(
            "OPERACION_ABIERTA | telegram_id=%s | usuario=%s | symbol=%s | trade_id=%s | order_number=%s | capital_disponible=%s %s | capital_usado=%s %s | cantidad=%s %s | entry=%s | sl_inicial=%s | tp_dinamico_activa=%s | score=%s | dry_run=%s",
            telegram_id,
            self._user_name(usuario),
            best_signal["symbol"],
            trade_id,
            order_number,
            self._fmt(available_quote),
            rule.quote_asset,
            self._fmt(quote_to_use),
            rule.quote_asset,
            self._fmt(amount),
            rule.base_asset,
            self._fmt(fallback_price),
            self._fmt(best_signal["initial_stop_loss"]),
            self._fmt(best_signal["dynamic_tp_activation_price"]),
            self._fmt(best_signal["score"], 2),
            DRY_RUN,
        )
        self.notifier.send(
            telegram_id,
            (
                f"✅ Compra {'simulada' if DRY_RUN else 'ejecutada'}\n"
                f"Par: {best_signal['symbol']}\n"
                f"Entrada: {float(fallback_price):.8f}\n"
                f"SL mental inicial: {best_signal['initial_stop_loss']:.8f}\n"
                f"Activación TP dinámico: {best_signal['dynamic_tp_activation_price']:.8f}\n"
                f"Score: {best_signal['score']}"
            ),
        )

    def _build_new_position(
        self,
        usuario: Dict,
        rule,
        signal: Dict,
        order_number: str,
        entry_price: Decimal,
        amount: Decimal,
        quote_to_use: Decimal,
        trade_id: str,
    ) -> Dict:
        opened_at = self._iso_now()
        entry_price_f = float(entry_price)
        position = {
            "trade_id": trade_id,
            "symbol": signal["symbol"],
            "side": "LONG",
            "status": "OPEN",
            "order_number": order_number,
            "entry_price": entry_price_f,
            "quantity": float(amount),
            "quote_amount": float(quote_to_use),
            "quote_asset": rule.quote_asset,
            "base_asset": rule.base_asset,
            "score": float(signal["score"]),
            "opened_at": opened_at,
            "manager_version": 2,
            "initial_stop_loss": float(signal["initial_stop_loss"]),
            "effective_stop_loss": float(signal["initial_stop_loss"]),
            "dynamic_tp_activation_price": float(signal["dynamic_tp_activation_price"]),
            "dynamic_tp_active": False,
            "dynamic_tp_activated_at": None,
            "highest_price_seen": entry_price_f,
            "highest_close_seen": entry_price_f,
            "highest_price_seen_at": opened_at,
            "max_unrealized_pnl": 0.0,
            "max_r_multiple": 0.0,
            "risk_per_unit": float(signal["risk_per_unit"]),
            "last_processed_candle_ts": int(signal["entry_candle_ts"]),
            "last_processed_price": entry_price_f,
            "weakness_confirmations": 0,
            "weakness_last_score": 0,
            "weakness_last_reason": [],
            "pending_exit_reason": None,
            "pending_exit_source": None,
            "pending_exit_trigger_price": None,
            "pending_exit_triggered_at": None,
            "strategy": {
                "components": signal["components"],
                "timeframes": {
                    "trend": TREND_PERIOD_SECONDS,
                    "pullback": PULLBACK_PERIOD_SECONDS,
                    "entry": ENTRY_PERIOD_SECONDS,
                },
                "manager_rules": signal["manager_rules"],
                "meta": signal.get("strategy_meta") or {},
            },
        }
        return position

    def _bootstrap_state_from_position(self, usuario: Dict, position: Dict) -> Dict:
        telegram_id = usuario["telegram_id"]
        opened_ms = self._iso_to_ms(position.get("opened_at"), int(time.time() * 1000) - ENTRY_PERIOD_SECONDS * 1000)
        initial_sl = float(position.get("initial_stop_loss") or position.get("stop_loss") or 0.0)
        entry_price = float(position.get("entry_price") or 0.0)
        risk_per_unit = float(position.get("risk_per_unit") or max(entry_price - initial_sl, entry_price * 0.02, 1e-12))
        activation_price = float(position.get("dynamic_tp_activation_price") or position.get("take_profit") or (entry_price + risk_per_unit))
        trade_id = position.get("trade_id") or f"{telegram_id}-{position['order_number']}"
        state = {
            "trade_id": trade_id,
            "symbol": position["symbol"],
            "side": position.get("side", "LONG"),
            "status": "OPEN",
            "order_number": position["order_number"],
            "entry_price": entry_price,
            "quantity": float(position.get("quantity") or 0.0),
            "quote_amount": float(position.get("quote_amount") or 0.0),
            "quote_asset": position.get("quote_asset"),
            "base_asset": position.get("base_asset"),
            "score": float(position.get("score") or 0.0),
            "opened_at": position.get("opened_at") or self._iso_now(),
            "manager_version": 2,
            "initial_stop_loss": initial_sl,
            "effective_stop_loss": float(position.get("effective_stop_loss") or initial_sl),
            "dynamic_tp_activation_price": activation_price,
            "dynamic_tp_active": bool(position.get("dynamic_tp_active")),
            "dynamic_tp_activated_at": position.get("dynamic_tp_activated_at"),
            "highest_price_seen": float(position.get("highest_price_seen") or entry_price),
            "highest_close_seen": float(position.get("highest_close_seen") or entry_price),
            "highest_price_seen_at": position.get("highest_price_seen_at") or position.get("opened_at") or self._iso_now(),
            "max_unrealized_pnl": float(position.get("max_unrealized_pnl") or 0.0),
            "max_r_multiple": float(position.get("max_r_multiple") or 0.0),
            "risk_per_unit": risk_per_unit,
            "last_processed_candle_ts": int(position.get("last_processed_candle_ts") or opened_ms),
            "last_processed_price": float(position.get("last_processed_price") or entry_price),
            "weakness_confirmations": int(position.get("weakness_confirmations") or 0),
            "weakness_last_score": int(position.get("weakness_last_score") or 0),
            "weakness_last_reason": position.get("weakness_last_reason") or [],
            "pending_exit_reason": position.get("pending_exit_reason"),
            "pending_exit_source": position.get("pending_exit_source"),
            "pending_exit_trigger_price": position.get("pending_exit_trigger_price"),
            "pending_exit_triggered_at": position.get("pending_exit_triggered_at"),
            "strategy": position.get("strategy") or {
                "components": [],
                "timeframes": {"trend": TREND_PERIOD_SECONDS, "pullback": PULLBACK_PERIOD_SECONDS, "entry": ENTRY_PERIOD_SECONDS},
                "manager_rules": {},
                "meta": position.get("strategy", {}).get("meta") or {},
            },
        }
        self._persist_trade_state(telegram_id, state)
        TradeEventModel.registrar_evento(trade_id, telegram_id, "RECOVERY_BOOTSTRAP", {"source": "legacy_active_position"})
        logger.warning("RECOVERY_BOOTSTRAP | telegram_id=%s | trade_id=%s | symbol=%s", telegram_id, trade_id, state["symbol"])
        return state

    def _persist_trade_state(self, telegram_id: int, state: Dict) -> None:
        snapshot = dict(state)
        snapshot.setdefault("status", "OPEN")
        UsuarioModel.guardar_posicion_activa(telegram_id, snapshot)
        TradeStateModel.upsert_estado(snapshot["trade_id"], telegram_id, snapshot)

    def _record_events(self, trade_id: str, telegram_id: int, events: List[Dict]) -> None:
        for event in events:
            TradeEventModel.registrar_evento(trade_id, telegram_id, event["type"], event.get("payload") or {})

    def _replay_trade_state(self, state: Dict) -> Dict:
        symbol = state["symbol"]
        entry_period = int((state.get("strategy") or {}).get("timeframes", {}).get("entry") or ENTRY_PERIOD_SECONDS)
        now_ms = int(time.time() * 1000)
        period_ms = entry_period * 1000
        last_closed_candle_ms = now_ms - (now_ms % period_ms) - period_ms
        last_processed = int(state.get("last_processed_candle_ts") or 0)
        if last_closed_candle_ms <= last_processed:
            return {"state": state, "events": [], "exit_signal": None}

        start_ms = max(last_processed - (2 * period_ms), self._iso_to_ms(state.get("opened_at"), last_processed))
        end_ms = min(last_closed_candle_ms, start_ms + (MANAGER_REPLAY_MAX_CANDLES + 2) * period_ms)
        df = self._public_client.obtener_klines_rango(symbol, entry_period, start_ms, end_ms)
        if df.empty:
            return {"state": state, "events": [], "exit_signal": None}

        df = self.strategy.add_indicators(df)
        rows = df[df["date_ms"] > last_processed].copy()
        if rows.empty:
            return {"state": state, "events": [], "exit_signal": None}

        working_state = dict(state)
        events: List[Dict] = []
        exit_signal = None
        for idx in rows.index:
            row = rows.loc[idx]
            prev_row = df.loc[idx - 1] if idx - 1 in df.index else None
            result = self.strategy.process_manager_candle(working_state, row, prev_row)
            working_state.update(result["updates"])
            events.extend(result["events"])
            if result["exit_signal"]:
                exit_signal = result["exit_signal"]
                working_state["pending_exit_reason"] = exit_signal["reason"]
                working_state["pending_exit_source"] = exit_signal.get("source")
                working_state["pending_exit_trigger_price"] = exit_signal.get("trigger_price")
                working_state["pending_exit_triggered_at"] = exit_signal.get("triggered_at")
                break
        return {"state": working_state, "events": events, "exit_signal": exit_signal}

    def _manage_open_position(self, usuario: Dict, client: ExchangeClient) -> None:
        telegram_id = usuario["telegram_id"]
        position = usuario.get("active_position")
        if not position:
            return

        symbol = position["symbol"]
        rule = self._symbol_rules.get(symbol) or self._public_client.obtener_info_instrumentos().get(symbol)
        if not rule:
            raise CoinWApiError(f"No hay reglas del instrumento para {symbol}")

        trade_id = position.get("trade_id") or f"{telegram_id}-{position['order_number']}"
        state = TradeStateModel.obtener_estado({"trade_id": trade_id, "status": {"$ne": "CLOSED"}})
        if not state:
            state = self._bootstrap_state_from_position(usuario, position)

        expected_qty = Decimal(str(state.get("quantity") or position.get("quantity") or 0.0))
        available_base = client.obtener_balance_disponible(rule.base_asset)
        if expected_qty > 0 and available_base <= Decimal("0.00000001"):
            self._handle_external_close(usuario, state)
            return

        replay = self._replay_trade_state(state)
        state = replay["state"]
        if replay["events"]:
            self._record_events(trade_id, telegram_id, replay["events"])
            logger.info(
                "RECOVERY_REPLAY | telegram_id=%s | trade_id=%s | symbol=%s | eventos=%s | ultimo_ts=%s",
                telegram_id,
                trade_id,
                symbol,
                len(replay["events"]),
                state.get("last_processed_candle_ts"),
            )

        current_price = float(client.obtener_precio_actual(symbol))
        logger.info(
            "MANAGER_TICK | telegram_id=%s | trade_id=%s | symbol=%s | current_price=%s | effective_stop=%s | dynamic_tp_active=%s | high_seen=%s",
            telegram_id,
            trade_id,
            symbol,
            self._fmt(current_price),
            self._fmt(state.get("effective_stop_loss")),
            bool(state.get("dynamic_tp_active")),
            self._fmt(state.get("highest_price_seen")),
        )
        live_result = self.strategy.process_live_price(state, current_price)
        state.update(live_result["updates"])
        if live_result["events"]:
            self._record_events(trade_id, telegram_id, live_result["events"])

        exit_signal = replay["exit_signal"] or live_result["exit_signal"]
        if exit_signal:
            self._close_managed_position(usuario, client, rule, state, exit_signal)
            return

        self._persist_trade_state(telegram_id, state)

    def _close_managed_position(self, usuario: Dict, client: ExchangeClient, rule, state: Dict, exit_signal: Dict) -> None:
        telegram_id = usuario["telegram_id"]
        trade_id = state["trade_id"]
        symbol = state["symbol"]
        available_base = client.obtener_balance_disponible(rule.base_asset)
        expected_qty = Decimal(str(state.get("quantity") or 0.0))
        quantity = min(expected_qty, available_base).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if quantity <= 0:
            self._handle_external_close(usuario, state)
            return

        trigger_reason = exit_signal["reason"]
        if DRY_RUN:
            exit_price = Decimal(str(client.obtener_precio_actual(symbol)))
            sell_order_number = f"dry-run-exit-{int(time.time())}"
        else:
            sell_order = client.crear_orden_mercado_sell(symbol, quantity, rule)
            sell_order_number = str(sell_order["orderNumber"])
            status = client.obtener_estado_orden(sell_order_number)
            fill = client.estimar_fill_desde_estado(status, fallback_price=Decimal(str(client.obtener_precio_actual(symbol))))
            exit_price = fill["avg_price"] or Decimal(str(client.obtener_precio_actual(symbol)))
            quantity = fill["amount"] or quantity
            if quantity <= 0:
                quantity = min(expected_qty, available_base).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        entry_price = Decimal(str(state["entry_price"]))
        pnl_quote = (exit_price - entry_price) * quantity
        pnl_pct = (pnl_quote / (entry_price * quantity) * Decimal("100")) if entry_price > 0 and quantity > 0 else Decimal("0")

        UsuarioModel.limpiar_posicion_activa(telegram_id)
        TradeStateModel.cerrar_estado(
            trade_id,
            {
                "exit_reason": trigger_reason,
                "exit_order_number": sell_order_number,
                "exit_price": float(exit_price),
                "quantity_closed": float(quantity),
                "pnl_quote": float(pnl_quote),
                "pnl_pct": float(pnl_pct),
                "pending_exit_reason": trigger_reason,
                "pending_exit_source": exit_signal.get("source"),
                "pending_exit_trigger_price": exit_signal.get("trigger_price"),
                "pending_exit_triggered_at": exit_signal.get("triggered_at"),
            },
        )
        TradeEventModel.registrar_evento(
            trade_id,
            telegram_id,
            "EXIT_FILLED",
            {
                "reason": trigger_reason,
                "exit_price": float(exit_price),
                "pnl_quote": float(pnl_quote),
                "source": exit_signal.get("source"),
                "triggered_at": exit_signal.get("triggered_at"),
            },
        )
        UsuarioModel.incrementar_stats(
            telegram_id,
            {
                "closed": 1,
                "wins": 1 if pnl_quote > 0 else 0,
                "losses": 1 if pnl_quote <= 0 else 0,
                "pnl_quote": float(pnl_quote),
            },
        )
        OperacionModel.actualizar_operacion(
            {"telegram_id": telegram_id, "order_number": state["order_number"]},
            {
                "status": trigger_reason,
                "exit_price": float(exit_price),
                "exit_order_number": sell_order_number,
                "closed_at": datetime.utcnow(),
                "pnl_quote": float(pnl_quote),
                "pnl_pct": float(pnl_pct),
                "quantity_closed": float(quantity),
                "highest_price_seen": float(state.get("highest_price_seen") or 0.0),
                "dynamic_tp_active": bool(state.get("dynamic_tp_active")),
                "dynamic_tp_activated_at": state.get("dynamic_tp_activated_at"),
                "max_unrealized_pnl": float(state.get("max_unrealized_pnl") or 0.0),
                "max_r_multiple": float(state.get("max_r_multiple") or 0.0),
                "weakness_last_score": int(state.get("weakness_last_score") or 0),
                "weakness_last_reason": state.get("weakness_last_reason") or [],
                "manager_exit_source": exit_signal.get("source"),
                "manager_exit_trigger_price": exit_signal.get("trigger_price"),
                "manager_exit_triggered_at": exit_signal.get("triggered_at"),
            },
        )

        operacion_cerrada = OperacionModel.obtener_operacion(
            {"telegram_id": telegram_id, "order_number": state["order_number"]}
        ) or {
            "telegram_id": telegram_id,
            "order_number": state["order_number"],
            "pnl_quote": float(pnl_quote),
        }
        fee_generada = self.fee_manager.registrar_fee_operacion(usuario, operacion_cerrada)
        invoice = self.fee_manager.ensure_invoice_if_threshold_reached(telegram_id)

        available_quote_after = None
        try:
            available_quote_after = client.obtener_balance_disponible(rule.quote_asset)
        except Exception:
            logger.debug("No se pudo obtener balance posterior al cierre para usuario %s", telegram_id)

        logger.info(
            "OPERACION_CERRADA | telegram_id=%s | usuario=%s | symbol=%s | trade_id=%s | close_reason=%s | source=%s | entry=%s | exit=%s | cantidad=%s %s | pnl=%s %s | pnl_pct=%s | fee_generada=%s %s | deuda_fee=%s %s | capital_posterior=%s %s | high_marca=%s | tp_dinamico_activo=%s | invoice_id=%s",
            telegram_id,
            self._user_name(usuario),
            symbol,
            trade_id,
            trigger_reason,
            exit_signal.get("source"),
            self._fmt(entry_price),
            self._fmt(exit_price),
            self._fmt(quantity),
            rule.base_asset,
            self._fmt(pnl_quote),
            rule.quote_asset,
            self._fmt(pnl_pct, 2),
            self._fmt(fee_generada),
            rule.quote_asset,
            self._fmt(float((UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {}).get("fee_due_total") or 0.0)),
            rule.quote_asset,
            self._fmt(available_quote_after) if available_quote_after is not None else "N/A",
            rule.quote_asset,
            self._fmt(state.get("highest_price_seen")),
            bool(state.get("dynamic_tp_active")),
            invoice.get("invoice_id") if invoice else "none",
        )
        if invoice:
            logger.warning(
                "TRADING_BLOQUEADO_FEE | telegram_id=%s | usuario=%s | invoice_id=%s | amount=%s %s",
                telegram_id,
                self._user_name(usuario),
                invoice["invoice_id"],
                self._fmt(invoice["invoice_amount"], 2),
                invoice["asset"],
            )

        message = (
            f"{'🟢' if pnl_quote > 0 else '🔴'} Posición cerrada\n"
            f"Par: {symbol}\n"
            f"Motivo: {trigger_reason}\n"
            f"Motor: {exit_signal.get('source', 'live')}\n"
            f"Entrada: {float(entry_price):.8f}\n"
            f"Salida: {float(exit_price):.8f}\n"
            f"Máximo visto: {float(state.get('highest_price_seen') or 0.0):.8f}\n"
            f"PnL: {float(pnl_quote):.8f} {rule.quote_asset} ({float(pnl_pct):.2f}%)"
        )
        if fee_generada > 0:
            message += f"\nFee admin generada: {fee_generada:.8f} {rule.quote_asset}"
        if invoice:
            message += (
                f"\n\n⛔ Trading pausado por fee acumulada."
                f"\nFactura: {invoice['invoice_id']}"
                f"\nMonto: {float(invoice['invoice_amount']):.2f} {invoice['asset']}"
            )
        self.notifier.send(telegram_id, message)

    def _handle_external_close(self, usuario: Dict, state: Dict) -> None:
        telegram_id = usuario["telegram_id"]
        trade_id = state["trade_id"]
        UsuarioModel.limpiar_posicion_activa(telegram_id)
        TradeStateModel.cerrar_estado(trade_id, {"exit_reason": "EXTERNAL_CLOSE"})
        TradeEventModel.registrar_evento(trade_id, telegram_id, "EXTERNAL_CLOSE", {"symbol": state.get("symbol")})
        OperacionModel.actualizar_operacion(
            {"telegram_id": telegram_id, "order_number": state["order_number"]},
            {"status": "EXTERNAL_CLOSE", "closed_at": datetime.utcnow()},
        )
        logger.warning(
            "OPERACION_CERRADA_EXTERNA | telegram_id=%s | trade_id=%s | symbol=%s",
            telegram_id,
            trade_id,
            state.get("symbol"),
        )

    def _get_thread_public_client(self) -> ExchangeClient:
        client = getattr(self._thread_local, "public_client", None)
        if client is None:
            client = ExchangeClient()
            self._thread_local.public_client = client
        return client

    def _get_klines_cached(self, symbol: str, period_seconds: int, limit: int = CANDLE_LIMIT) -> pd.DataFrame:
        now_ms = int(time.time() * 1000)
        period_ms = period_seconds * 1000
        last_closed_candle_ms = now_ms - (now_ms % period_ms) - period_ms
        cache_key = (symbol.upper(), period_seconds, limit)

        with self._kline_cache_lock:
            cached = self._kline_cache.get(cache_key)
            if cached and cached.get("last_closed_candle_ms") == last_closed_candle_ms:
                return cached["df"].copy()

        client = self._get_thread_public_client()
        df = client.obtener_klines(symbol, period_seconds, limit=limit)

        with self._kline_cache_lock:
            self._kline_cache[cache_key] = {
                "last_closed_candle_ms": last_closed_candle_ms,
                "df": df.copy(),
            }
        return df.copy()

    def _evaluate_symbol(self, symbol: str) -> Dict[str, Any]:
        try:
            df_trend = self._get_klines_cached(symbol, TREND_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            df_pullback = self._get_klines_cached(symbol, PULLBACK_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            df_entry = self._get_klines_cached(symbol, ENTRY_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            diagnostic = self.strategy.analizar_detallado(df_trend, df_pullback, df_entry)
            if diagnostic.get("signal"):
                diagnostic["signal"]["symbol"] = symbol
            return diagnostic
        except Exception as exc:
            logger.warning("SCAN_SYMBOL_ERROR | symbol=%s | error=%s", symbol, exc)
            return {
                "accepted": False,
                "reason": "DATA_OR_EVAL_ERROR",
                "detail": {"error": str(exc)},
                "signal": None,
            }
