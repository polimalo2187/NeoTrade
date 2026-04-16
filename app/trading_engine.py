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
    TP1_PARTIAL_FRACTION,
    TP1_PARTIAL_MIN_QUOTE,
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

    @staticmethod
    def _format_reason_list(reasons: List[str], limit: int = 5) -> str:
        if not reasons:
            return "none"
        return ",".join(str(reason) for reason in reasons[:limit])

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
                capital_snapshot = self._refresh_user_capital_snapshot(usuario, client)
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
                    self._open_trade_from_market_scan(usuario, client, market_scan, capital_snapshot)
                UsuarioModel.actualizar_engine_error(telegram_id, None)
            except CoinWApiError as exc:
                logger.warning("Usuario %s | CoinW error: %s", telegram_id, exc)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))
            except Exception as exc:
                logger.exception("Usuario %s | error inesperado", telegram_id)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))

    def _refresh_user_capital_snapshot(self, usuario: Dict, client: ExchangeClient) -> Dict[str, Decimal]:
        capital = client.estimar_capital_total_en_quote(QUOTE_ASSET)
        capital_total = float(capital["capital_total_estimated"])
        capital_activo = capital_total * CAPITAL_ACTIVO_PORC
        UsuarioModel.actualizar_capital_snapshot(usuario["telegram_id"], capital_total, capital_activo)
        return capital

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

    def _serialize_execution_plan(self, plan: Dict[str, Any]) -> str:
        detail = {
            "requested_quote": self._fmt(plan.get("requested_quote")),
            "effective_quote": self._fmt(plan.get("effective_quote")),
            "min_quote_required": self._fmt(plan.get("min_quote_required")),
            "min_quote_by_amount": self._fmt(plan.get("min_quote_by_amount")),
            "min_quote_by_count": self._fmt(plan.get("min_quote_by_count")),
            "adjusted_amount": self._fmt(plan.get("adjusted_amount")),
            "reference_price": self._fmt(plan.get("reference_price")),
            "quote_capped": bool(plan.get("quote_capped")),
        }
        return self._serialize_scan_detail(detail)

    def _serialize_partial_sell_plan(self, plan: Dict[str, Any]) -> str:
        detail = {
            "requested_total_amount": self._fmt(plan.get("requested_total_amount")),
            "requested_partial_amount": self._fmt(plan.get("requested_partial_amount")),
            "adjusted_partial_amount": self._fmt(plan.get("adjusted_partial_amount")),
            "remaining_amount": self._fmt(plan.get("remaining_amount")),
            "partial_estimated_quote": self._fmt(plan.get("partial_estimated_quote")),
            "remaining_estimated_quote": self._fmt(plan.get("remaining_estimated_quote")),
            "min_quote_required": self._fmt(plan.get("min_quote_required")),
            "reference_price": self._fmt(plan.get("reference_price")),
        }
        return self._serialize_scan_detail(detail)

    def _select_signal_for_user(
        self,
        client: ExchangeClient,
        accepted_signals: List[Dict[str, Any]],
        requested_quote_to_use: Decimal,
    ) -> Dict[str, Any]:
        executable_signals: List[Dict[str, Any]] = []
        blocked_counts: Counter = Counter()
        blocked_samples: List[str] = []

        for signal in accepted_signals:
            symbol = signal.get("symbol")
            rule = self._symbol_rules.get(symbol)
            if not rule:
                blocked_counts["MISSING_RULE"] += 1
                if len(blocked_samples) < 8:
                    blocked_samples.append(f"{symbol}:MISSING_RULE[requested_quote={self._fmt(requested_quote_to_use)}]")
                continue

            execution_plan = client.evaluar_compra_mercado(
                symbol=symbol,
                funds=requested_quote_to_use,
                rule=rule,
                reference_price=Decimal(str(signal.get("entry_price") or 0)),
            )
            if not execution_plan.get("executable"):
                reason = execution_plan.get("reason") or "NOT_EXECUTABLE"
                blocked_counts[reason] += 1
                if len(blocked_samples) < 8:
                    blocked_samples.append(f"{symbol}:{reason}[{self._serialize_execution_plan(execution_plan)}]")
                continue

            enriched_signal = dict(signal)
            enriched_signal["execution_plan"] = execution_plan
            executable_signals.append(enriched_signal)

        best_signal = executable_signals[0] if executable_signals else None
        return {
            "best_signal": best_signal,
            "executable_count": len(executable_signals),
            "blocked_counts": dict(blocked_counts),
            "blocked_samples": blocked_samples,
        }

    def _open_trade_from_market_scan(self, usuario: Dict, client: ExchangeClient, market_scan: Dict[str, Any], capital_snapshot: Dict[str, Decimal]) -> None:
        telegram_id = usuario["telegram_id"]
        available_quote = capital_snapshot.get("quote_available", Decimal("0"))
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

        requested_quote_to_use = (available_quote * Decimal(str(CAPITAL_ACTIVO_PORC))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        selection = self._select_signal_for_user(client, accepted_signals, requested_quote_to_use)
        best_signal = selection.get("best_signal")

        if not best_signal:
            logger.warning(
                "SCAN_RESULT_GLOBAL_SIGNAL_BLOCKED_FOR_USER | telegram_id=%s | usuario=%s | global_candidates=%s | requested_quote_to_use=%s %s | blocked_summary=%s | blocked_samples=%s",
                telegram_id,
                self._user_name(usuario),
                len(accepted_signals),
                self._fmt(requested_quote_to_use),
                QUOTE_ASSET,
                self._format_reason_counts(selection.get("blocked_counts") or {}),
                self._format_scan_samples(selection.get("blocked_samples") or []),
            )
            return

        execution_plan = best_signal["execution_plan"]
        rule = self._symbol_rules[best_signal["symbol"]]
        effective_quote_to_use = execution_plan["effective_quote"]
        fallback_price = Decimal(str(best_signal["entry_price"]))

        logger.info(
            "SCAN_RESULT_CANDIDATE | telegram_id=%s | usuario=%s | symbols=%s | global_candidates=%s | executable_candidates=%s | best_symbol=%s | best_score=%s | best_entry=%s | requested_quote_to_use=%s %s | effective_quote_to_use=%s %s | blocked_for_user_summary=%s | rejection_summary=%s | samples=%s",
            telegram_id,
            self._user_name(usuario),
            len(symbols),
            len(accepted_signals),
            selection.get("executable_count") or 0,
            best_signal["symbol"],
            self._fmt(best_signal["score"], 2),
            self._fmt(best_signal["entry_price"]),
            self._fmt(requested_quote_to_use),
            rule.quote_asset,
            self._fmt(effective_quote_to_use),
            rule.quote_asset,
            self._format_reason_counts(selection.get("blocked_counts") or {}),
            self._format_reason_counts(reason_counts),
            self._format_scan_samples(samples),
        )

        if DRY_RUN:
            amount = execution_plan.get("adjusted_amount") or Decimal("0")
            if amount <= 0 and fallback_price > 0:
                amount = (effective_quote_to_use / fallback_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            order_number = f"dry-run-{int(time.time())}"
        else:
            order = client.crear_orden_mercado_buy(best_signal["symbol"], effective_quote_to_use, rule)
            order_number = str(order["orderNumber"])
            status = client.obtener_estado_orden(order_number)
            fill = client.estimar_fill_desde_estado(status, fallback_price=fallback_price)
            amount = fill["amount"]
            fallback_price = fill["avg_price"] or fallback_price
            if amount <= 0:
                amount = execution_plan.get("adjusted_amount") or Decimal("0")
            if amount <= 0 and fallback_price > 0:
                amount = (effective_quote_to_use / fallback_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        trade_id = f"{telegram_id}-{order_number}"
        position = self._build_new_position(usuario, rule, best_signal, order_number, fallback_price, amount, effective_quote_to_use, trade_id)
        self._persist_trade_state(telegram_id, position)
        TradeEventModel.registrar_evento(trade_id, telegram_id, "ENTRY_FILLED", {
            "symbol": best_signal["symbol"],
            "entry_price": float(fallback_price),
            "quantity": float(amount),
            "quote_used": float(effective_quote_to_use),
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
                "original_quantity": float(amount),
                "quote_amount": float(effective_quote_to_use),
                "tp1_partial_enabled": float(effective_quote_to_use) >= float((best_signal.get("manager_rules") or {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE) or 0.0) and float((best_signal.get("manager_rules") or {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION) or 0.0) > 0,
                "tp1_partial_fraction": float((best_signal.get("manager_rules") or {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION) or 0.0),
                "tp1_partial_min_quote": float((best_signal.get("manager_rules") or {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE) or 0.0),
                "tp1_partial_done": False,
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
            self._fmt(effective_quote_to_use),
            rule.quote_asset,
            self._fmt(amount),
            rule.base_asset,
            self._fmt(fallback_price),
            self._fmt(best_signal["initial_stop_loss"]),
            self._fmt(best_signal["dynamic_tp_activation_price"]),
            self._fmt(best_signal["score"], 2),
            DRY_RUN,
        )
        tp1_fraction = float((best_signal.get("manager_rules") or {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION) or 0.0)
        tp1_min_quote = float((best_signal.get("manager_rules") or {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE) or 0.0)
        tp1_enabled_for_trade = float(effective_quote_to_use) >= tp1_min_quote and tp1_fraction > 0
        self.notifier.send(
            telegram_id,
            (
                f"✅ Compra {'simulada' if DRY_RUN else 'ejecutada'}\n"
                f"Par: {best_signal['symbol']}\n"
                f"Entrada: {float(fallback_price):.8f}\n"
                f"SL mental inicial: {best_signal['initial_stop_loss']:.8f}\n"
                f"Activación TP dinámico: {best_signal['dynamic_tp_activation_price']:.8f}\n"
                f"TP1 parcial: {'habilitado' if tp1_enabled_for_trade else 'deshabilitado'}"
                + (f" ({tp1_fraction * 100:.0f}% al activarse el TP dinámico)" if tp1_enabled_for_trade else f" (< {tp1_min_quote:.2f} {rule.quote_asset} operativos)")
                + f"\nScore: {best_signal['score']}"
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
        tp1_fraction = float((signal.get("manager_rules") or {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION) or 0.0)
        tp1_min_quote = float((signal.get("manager_rules") or {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE) or 0.0)
        tp1_enabled = float(quote_to_use) >= tp1_min_quote and tp1_fraction > 0
        position = {
            "trade_id": trade_id,
            "symbol": signal["symbol"],
            "side": "LONG",
            "status": "OPEN",
            "order_number": order_number,
            "entry_price": entry_price_f,
            "quantity": float(amount),
            "original_quantity": float(amount),
            "quote_amount": float(quote_to_use),
            "quote_asset": rule.quote_asset,
            "base_asset": rule.base_asset,
            "score": float(signal["score"]),
            "opened_at": opened_at,
            "manager_version": 3,
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
            "realized_pnl_quote": 0.0,
            "last_processed_candle_ts": int(signal["entry_candle_ts"]),
            "last_processed_price": entry_price_f,
            "weakness_confirmations": 0,
            "weakness_last_score": 0,
            "weakness_last_reason": [],
            "tp1_partial_enabled": tp1_enabled,
            "tp1_partial_fraction": tp1_fraction,
            "tp1_partial_min_quote": tp1_min_quote,
            "tp1_partial_done": False,
            "tp1_partial_done_at": None,
            "tp1_partial_order_number": None,
            "tp1_partial_quantity": 0.0,
            "tp1_partial_price": None,
            "tp1_partial_quote_amount": 0.0,
            "tp1_partial_realized_pnl_quote": 0.0,
            "tp1_partial_skip_reason": None,
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
            "original_quantity": float(position.get("original_quantity") or position.get("quantity") or 0.0),
            "quote_amount": float(position.get("quote_amount") or 0.0),
            "quote_asset": position.get("quote_asset"),
            "base_asset": position.get("base_asset"),
            "score": float(position.get("score") or 0.0),
            "opened_at": position.get("opened_at") or self._iso_now(),
            "manager_version": int(position.get("manager_version") or 3),
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
            "realized_pnl_quote": float(position.get("realized_pnl_quote") or position.get("tp1_partial_realized_pnl_quote") or 0.0),
            "last_processed_candle_ts": int(position.get("last_processed_candle_ts") or opened_ms),
            "last_processed_price": float(position.get("last_processed_price") or entry_price),
            "weakness_confirmations": int(position.get("weakness_confirmations") or 0),
            "weakness_last_score": int(position.get("weakness_last_score") or 0),
            "weakness_last_reason": position.get("weakness_last_reason") or [],
            "tp1_partial_fraction": float(position.get("tp1_partial_fraction") or ((position.get("strategy") or {}).get("manager_rules", {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION)) or 0.0),
            "tp1_partial_min_quote": float(position.get("tp1_partial_min_quote") or ((position.get("strategy") or {}).get("manager_rules", {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE)) or 0.0),
            "tp1_partial_enabled": bool(position.get("tp1_partial_enabled")) if "tp1_partial_enabled" in position else (float(position.get("quote_amount") or 0.0) >= float(((position.get("strategy") or {}).get("manager_rules", {}).get("tp1_partial_min_quote", TP1_PARTIAL_MIN_QUOTE)) or 0.0) and float(((position.get("strategy") or {}).get("manager_rules", {}).get("tp1_partial_fraction", TP1_PARTIAL_FRACTION)) or 0.0) > 0),
            "tp1_partial_done": bool(position.get("tp1_partial_done")),
            "tp1_partial_done_at": position.get("tp1_partial_done_at"),
            "tp1_partial_order_number": position.get("tp1_partial_order_number"),
            "tp1_partial_quantity": float(position.get("tp1_partial_quantity") or 0.0),
            "tp1_partial_price": position.get("tp1_partial_price"),
            "tp1_partial_quote_amount": float(position.get("tp1_partial_quote_amount") or 0.0),
            "tp1_partial_realized_pnl_quote": float(position.get("tp1_partial_realized_pnl_quote") or 0.0),
            "tp1_partial_skip_reason": position.get("tp1_partial_skip_reason"),
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

    def _execute_tp1_partial(
        self,
        usuario: Dict,
        client: ExchangeClient,
        rule,
        state: Dict,
        available_base: Decimal,
        current_price: float,
    ) -> Decimal:
        telegram_id = usuario["telegram_id"]
        trade_id = state["trade_id"]
        symbol = state["symbol"]
        tp1_enabled = bool(state.get("tp1_partial_enabled"))
        tp1_done = bool(state.get("tp1_partial_done"))
        tp1_fraction = Decimal(str(state.get("tp1_partial_fraction") or 0.0))
        if not tp1_enabled or tp1_done or tp1_fraction <= 0:
            return available_base

        total_amount = min(available_base, Decimal(str(state.get("quantity") or 0.0))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        plan = client.evaluar_venta_parcial_mercado(
            symbol=symbol,
            total_amount=total_amount,
            fraction=tp1_fraction,
            rule=rule,
            reference_price=Decimal(str(current_price)),
        )
        if not plan.get("executable"):
            reason = plan.get("reason") or "TP1_PARTIAL_NOT_EXECUTABLE"
            state["tp1_partial_enabled"] = False
            state["tp1_partial_skip_reason"] = reason
            event = {
                "type": "TP1_PARTIAL_SKIPPED",
                "payload": {
                    "reason": reason,
                    "detail": self._serialize_partial_sell_plan(plan),
                },
            }
            self._record_events(trade_id, telegram_id, [event])
            self._log_manager_events(telegram_id, trade_id, symbol, [event])
            logger.warning(
                "TP1_PARTIAL_SKIPPED | telegram_id=%s | trade_id=%s | symbol=%s | reason=%s | plan=%s",
                telegram_id,
                trade_id,
                symbol,
                reason,
                self._serialize_partial_sell_plan(plan),
            )
            return available_base

        adjusted_partial_amount = Decimal(str(plan.get("adjusted_partial_amount") or 0)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        fallback_price = Decimal(str(current_price))
        try:
            if DRY_RUN:
                sell_order_number = f"dry-run-tp1-{int(time.time())}"
                sold_qty = adjusted_partial_amount
                fill_price = fallback_price
            else:
                sell_order = client.crear_orden_mercado_sell(symbol, adjusted_partial_amount, rule)
                sell_order_number = str(sell_order["orderNumber"])
                status = client.obtener_estado_orden(sell_order_number)
                fill = client.estimar_fill_desde_estado(status, fallback_price=fallback_price)
                sold_qty = fill["amount"] or adjusted_partial_amount
                fill_price = fill["avg_price"] or fallback_price
        except Exception as exc:
            state["tp1_partial_enabled"] = False
            state["tp1_partial_skip_reason"] = f"EXECUTION_ERROR:{exc}"
            event = {
                "type": "TP1_PARTIAL_EXECUTION_ERROR",
                "payload": {"error": str(exc)},
            }
            self._record_events(trade_id, telegram_id, [event])
            self._log_manager_events(telegram_id, trade_id, symbol, [event])
            logger.exception(
                "TP1_PARTIAL_EXECUTION_ERROR | telegram_id=%s | trade_id=%s | symbol=%s",
                telegram_id,
                trade_id,
                symbol,
            )
            return available_base

        sold_qty = min(available_base, Decimal(str(sold_qty or adjusted_partial_amount))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if sold_qty <= 0:
            state["tp1_partial_enabled"] = False
            state["tp1_partial_skip_reason"] = "ZERO_FILLED_PARTIAL"
            event = {"type": "TP1_PARTIAL_ZERO_FILL", "payload": {"planned_qty": float(adjusted_partial_amount)}}
            self._record_events(trade_id, telegram_id, [event])
            self._log_manager_events(telegram_id, trade_id, symbol, [event])
            return available_base

        entry_price = Decimal(str(state.get("entry_price") or 0.0))
        partial_quote_amount = (fill_price * sold_qty).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        realized_pnl = ((fill_price - entry_price) * sold_qty).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        remaining_qty = max(Decimal(str(state.get("quantity") or 0.0)) - sold_qty, Decimal("0")).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        new_available_base = max(available_base - sold_qty, Decimal("0")).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        state["quantity"] = float(remaining_qty)
        state["realized_pnl_quote"] = float(Decimal(str(state.get("realized_pnl_quote") or 0.0)) + realized_pnl)
        state["tp1_partial_done"] = True
        state["tp1_partial_done_at"] = self._iso_now()
        state["tp1_partial_order_number"] = sell_order_number
        state["tp1_partial_quantity"] = float(sold_qty)
        state["tp1_partial_price"] = float(fill_price)
        state["tp1_partial_quote_amount"] = float(partial_quote_amount)
        state["tp1_partial_realized_pnl_quote"] = float(realized_pnl)
        state["tp1_partial_skip_reason"] = None

        event = {
            "type": "TP1_PARTIAL_EXECUTED",
            "payload": {
                "order_number": sell_order_number,
                "sold_qty": float(sold_qty),
                "remaining_qty": float(remaining_qty),
                "fill_price": float(fill_price),
                "realized_pnl_quote": float(realized_pnl),
                "quote_amount": float(partial_quote_amount),
            },
        }
        self._record_events(trade_id, telegram_id, [event])
        self._log_manager_events(telegram_id, trade_id, symbol, [event])
        OperacionModel.actualizar_operacion(
            {"telegram_id": telegram_id, "order_number": state["order_number"]},
            {
                "tp1_partial_done": True,
                "tp1_partial_done_at": state["tp1_partial_done_at"],
                "tp1_partial_order_number": sell_order_number,
                "tp1_partial_quantity": float(sold_qty),
                "tp1_partial_price": float(fill_price),
                "tp1_partial_quote_amount": float(partial_quote_amount),
                "tp1_partial_realized_pnl_quote": float(realized_pnl),
                "quantity_remaining": float(remaining_qty),
                "realized_pnl_quote": float(state.get("realized_pnl_quote") or 0.0),
            },
        )
        self.notifier.send(
            telegram_id,
            (
                f"🟡 TP1 parcial {'simulado' if DRY_RUN else 'ejecutado'}\n"
                f"Par: {symbol}\n"
                f"Cantidad vendida: {float(sold_qty):.8f} {rule.base_asset}\n"
                f"Precio: {float(fill_price):.8f}\n"
                f"PnL realizada: {float(realized_pnl):.8f} {rule.quote_asset}\n"
                f"Cantidad restante: {float(remaining_qty):.8f} {rule.base_asset}"
            ),
        )
        logger.info(
            "TP1_PARTIAL_EXECUTED | telegram_id=%s | trade_id=%s | symbol=%s | qty_sold=%s %s | qty_remaining=%s %s | fill_price=%s | realized_pnl=%s %s | dry_run=%s",
            telegram_id,
            trade_id,
            symbol,
            self._fmt(sold_qty),
            rule.base_asset,
            self._fmt(remaining_qty),
            rule.base_asset,
            self._fmt(fill_price),
            self._fmt(realized_pnl),
            rule.quote_asset,
            DRY_RUN,
        )
        return new_available_base

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
        live_result = self.strategy.process_live_price(state, current_price)
        state.update(live_result["updates"])
        if replay["events"]:
            self._log_manager_events(telegram_id, trade_id, symbol, replay["events"])
        if live_result["events"]:
            self._record_events(trade_id, telegram_id, live_result["events"])
            self._log_manager_events(telegram_id, trade_id, symbol, live_result["events"])

        exit_signal = replay["exit_signal"] or live_result["exit_signal"]
        if not exit_signal and bool(state.get("dynamic_tp_active")) and not bool(state.get("tp1_partial_done")):
            available_base = self._execute_tp1_partial(usuario, client, rule, state, available_base, current_price)

        self._emit_manager_snapshot(usuario, state, current_price)

        if exit_signal:
            self._close_managed_position(usuario, client, rule, state, exit_signal)
            return

        self._persist_trade_state(telegram_id, state)

    def _log_manager_events(self, telegram_id: int, trade_id: str, symbol: str, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        for event in events:
            payload = event.get("payload") or {}
            logger.info(
                "MANAGER_EVENT | telegram_id=%s | trade_id=%s | symbol=%s | type=%s | payload=%s",
                telegram_id,
                trade_id,
                symbol,
                event.get("type"),
                self._serialize_scan_detail(payload),
            )

    def _emit_manager_snapshot(self, usuario: Dict, state: Dict, current_price: float) -> None:
        telegram_id = usuario["telegram_id"]
        trade_id = state["trade_id"]
        symbol = state["symbol"]
        entry_price = float(state.get("entry_price") or 0.0)
        quantity = float(state.get("quantity") or 0.0)
        original_quantity = float(state.get("original_quantity") or quantity)
        initial_stop = float(state.get("initial_stop_loss") or 0.0)
        effective_stop = float(state.get("effective_stop_loss") or initial_stop)
        activation_price = float(state.get("dynamic_tp_activation_price") or 0.0)
        dynamic_active = bool(state.get("dynamic_tp_active"))
        high_seen = float(state.get("highest_price_seen") or entry_price)
        risk_per_unit = max(float(state.get("risk_per_unit") or (entry_price - initial_stop)), 1e-12)
        quote_asset = state.get("quote_asset") or QUOTE_ASSET
        unrealized_pnl_quote = (current_price - entry_price) * quantity if quantity > 0 else 0.0
        unrealized_pnl_pct = ((current_price / entry_price) - 1.0) * 100.0 if entry_price > 0 else 0.0
        realized_pnl_quote = float(state.get("realized_pnl_quote") or 0.0)
        total_pnl_estimated = realized_pnl_quote + unrealized_pnl_quote
        invested_notional = (entry_price * original_quantity) if entry_price > 0 and original_quantity > 0 else float(state.get("quote_amount") or 0.0)
        total_pnl_estimated_pct = (total_pnl_estimated / invested_notional) * 100.0 if invested_notional > 0 else 0.0
        current_r_multiple = (current_price - entry_price) / risk_per_unit if risk_per_unit > 0 else 0.0
        distance_to_stop_pct = ((current_price - effective_stop) / current_price) * 100.0 if current_price > 0 else 0.0
        activation_gap = max(activation_price - current_price, 0.0) if activation_price > 0 else 0.0
        activation_progress_pct = 0.0
        if activation_price > entry_price > 0:
            activation_progress_pct = ((current_price - entry_price) / (activation_price - entry_price)) * 100.0
            activation_progress_pct = max(0.0, min(activation_progress_pct, 100.0))
        manager_rules = (state.get("strategy") or {}).get("manager_rules") or {}
        weakness_confirmations = int(state.get("weakness_confirmations") or 0)
        weakness_required = int(manager_rules.get("weakness_confirmations_required", 0) or 0)
        weakness_last_score = int(state.get("weakness_last_score") or 0)
        weakness_last_reason = state.get("weakness_last_reason") or []
        break_even_offset_r = float(manager_rules.get("break_even_offset_r", 0.0) or 0.0)
        trail_atr_mult = float(manager_rules.get("trail_stop_atr_multiplier", 0.0) or 0.0)
        weakness_min_score = int(manager_rules.get("weakness_min_score", 0) or 0)
        tp1_fraction = float(state.get("tp1_partial_fraction") or manager_rules.get("tp1_partial_fraction", 0.0) or 0.0)
        tp1_min_quote = float(state.get("tp1_partial_min_quote") or manager_rules.get("tp1_partial_min_quote", 0.0) or 0.0)
        tp1_enabled = bool(state.get("tp1_partial_enabled"))
        tp1_done = bool(state.get("tp1_partial_done"))
        tp1_qty = float(state.get("tp1_partial_quantity") or 0.0)
        tp1_price = state.get("tp1_partial_price")
        tp1_skip_reason = state.get("tp1_partial_skip_reason") or "none"

        logger.info(
            "MANAGER_TICK | telegram_id=%s | trade_id=%s | symbol=%s | entry=%s | current_price=%s | unrealized_pnl=%s %s | unrealized_pnl_pct=%s | realized_pnl=%s %s | total_pnl_estimated=%s %s | total_pnl_estimated_pct=%s | r_multiple=%s | initial_stop=%s | effective_stop=%s | stop_gap_pct=%s | dynamic_tp_activation=%s | dynamic_tp_active=%s | dynamic_tp_progress_pct=%s | dynamic_tp_gap=%s | high_seen=%s | qty=%s | original_qty=%s | tp1_enabled=%s | tp1_done=%s | tp1_fraction_pct=%s | tp1_min_quote=%s | tp1_qty=%s | tp1_price=%s | tp1_skip_reason=%s | weakness_score=%s | weakness_confirmations=%s/%s | weakness_reasons=%s | break_even_offset_r=%s | trail_atr_mult=%s | weakness_min_score=%s",
            telegram_id,
            trade_id,
            symbol,
            self._fmt(entry_price),
            self._fmt(current_price),
            self._fmt(unrealized_pnl_quote),
            quote_asset,
            self._fmt(unrealized_pnl_pct, 2),
            self._fmt(realized_pnl_quote),
            quote_asset,
            self._fmt(total_pnl_estimated),
            quote_asset,
            self._fmt(total_pnl_estimated_pct, 2),
            self._fmt(current_r_multiple, 2),
            self._fmt(initial_stop),
            self._fmt(effective_stop),
            self._fmt(distance_to_stop_pct, 2),
            self._fmt(activation_price),
            dynamic_active,
            self._fmt(activation_progress_pct, 2),
            self._fmt(activation_gap),
            self._fmt(high_seen),
            self._fmt(quantity),
            self._fmt(original_quantity),
            tp1_enabled,
            tp1_done,
            self._fmt(tp1_fraction * 100.0, 2),
            self._fmt(tp1_min_quote, 2),
            self._fmt(tp1_qty),
            self._fmt(tp1_price) if tp1_price is not None else "N/A",
            tp1_skip_reason,
            weakness_last_score,
            weakness_confirmations,
            weakness_required,
            self._format_reason_list(weakness_last_reason),
            self._fmt(break_even_offset_r, 3),
            self._fmt(trail_atr_mult, 3),
            weakness_min_score,
        )

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
        realized_pnl_quote = Decimal(str(state.get("realized_pnl_quote") or 0.0))
        leg_pnl_quote = (exit_price - entry_price) * quantity
        pnl_quote = realized_pnl_quote + leg_pnl_quote
        original_quantity = Decimal(str(state.get("original_quantity") or state.get("quantity") or 0.0))
        denominator = (entry_price * original_quantity) if entry_price > 0 and original_quantity > 0 else Decimal(str(state.get("quote_amount") or 0.0))
        pnl_pct = (pnl_quote / denominator * Decimal("100")) if denominator > 0 else Decimal("0")

        UsuarioModel.limpiar_posicion_activa(telegram_id)
        TradeStateModel.cerrar_estado(
            trade_id,
            {
                "exit_reason": trigger_reason,
                "exit_order_number": sell_order_number,
                "exit_price": float(exit_price),
                "quantity_closed": float(quantity),
                "quantity_closed_total": float(Decimal(str(state.get("tp1_partial_quantity") or 0.0)) + quantity),
                "pnl_quote": float(pnl_quote),
                "pnl_pct": float(pnl_pct),
                "realized_pnl_quote": float(realized_pnl_quote),
                "final_leg_pnl_quote": float(leg_pnl_quote),
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
                "realized_pnl_quote": float(realized_pnl_quote),
                "final_leg_pnl_quote": float(leg_pnl_quote),
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
                "quantity_closed_total": float(Decimal(str(state.get("tp1_partial_quantity") or 0.0)) + quantity),
                "realized_pnl_quote": float(realized_pnl_quote),
                "final_leg_pnl_quote": float(leg_pnl_quote),
                "tp1_partial_done": bool(state.get("tp1_partial_done")),
                "tp1_partial_done_at": state.get("tp1_partial_done_at"),
                "tp1_partial_order_number": state.get("tp1_partial_order_number"),
                "tp1_partial_quantity": float(state.get("tp1_partial_quantity") or 0.0),
                "tp1_partial_price": state.get("tp1_partial_price"),
                "tp1_partial_quote_amount": float(state.get("tp1_partial_quote_amount") or 0.0),
                "tp1_partial_realized_pnl_quote": float(state.get("tp1_partial_realized_pnl_quote") or 0.0),
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
            "OPERACION_CERRADA | telegram_id=%s | usuario=%s | symbol=%s | trade_id=%s | close_reason=%s | source=%s | entry=%s | exit=%s | cantidad_final=%s %s | cantidad_total_cerrada=%s %s | pnl=%s %s | pnl_pct=%s | pnl_realizada=%s %s | pnl_tramo_final=%s %s | fee_generada=%s %s | deuda_fee=%s %s | capital_posterior=%s %s | high_marca=%s | tp_dinamico_activo=%s | tp1_done=%s | invoice_id=%s",
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
            self._fmt(Decimal(str(state.get("tp1_partial_quantity") or 0.0)) + quantity),
            rule.base_asset,
            self._fmt(pnl_quote),
            rule.quote_asset,
            self._fmt(pnl_pct, 2),
            self._fmt(realized_pnl_quote),
            rule.quote_asset,
            self._fmt(leg_pnl_quote),
            rule.quote_asset,
            self._fmt(fee_generada),
            rule.quote_asset,
            self._fmt(float((UsuarioModel.obtener_usuario({"telegram_id": telegram_id}) or {}).get("fee_due_total") or 0.0)),
            rule.quote_asset,
            self._fmt(available_quote_after) if available_quote_after is not None else "N/A",
            rule.quote_asset,
            self._fmt(state.get("highest_price_seen")),
            bool(state.get("dynamic_tp_active")),
            bool(state.get("tp1_partial_done")),
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
            + (f"TP1 parcial realizada: {float(state.get('tp1_partial_realized_pnl_quote') or 0.0):.8f} {rule.quote_asset}\n" if state.get('tp1_partial_done') else "")
            + f"PnL total: {float(pnl_quote):.8f} {rule.quote_asset} ({float(pnl_pct):.2f}%)"
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
