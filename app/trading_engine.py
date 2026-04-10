import logging
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional

import requests

from app.config import (
    CAPITAL_ACTIVO_PORC,
    CANDLE_LIMIT,
    DEFAULT_SYMBOLS,
    DRY_RUN,
    ENABLE_TRADING_ENGINE,
    ENTRY_PERIOD_SECONDS,
    MIN_24H_QUOTE_VOLUME,
    MIN_USDT_ORDER,
    MAX_SYMBOLS_TO_SCAN,
    PULLBACK_PERIOD_SECONDS,
    QUOTE_ASSET,
    SCAN_INTERVAL_SECONDS,
    SYMBOL_REFRESH_SECONDS,
    TAKE_PROFIT_PORC,
    TELEGRAM_BOT_TOKEN,
    TREND_PERIOD_SECONDS,
)
from app.exchange import CoinWApiError, ExchangeClient
from app.fee_manager import FeeManager
from app.models import OperacionModel, UsuarioModel
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

    def start(self):
        if not ENABLE_TRADING_ENGINE:
            logger.info("Motor de trading deshabilitado por configuración.")
            return
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="trading-engine")
        self._thread.start()
        logger.info("Motor de trading iniciado.")

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
        usuarios = UsuarioModel.obtener_usuarios_activos()
        if not usuarios:
            return

        candidate_symbols = self._get_candidate_symbols()
        for usuario in usuarios:
            telegram_id = usuario["telegram_id"]
            try:
                client = ExchangeClient(usuario.get("api_key"), usuario.get("api_secret"))
                self._refresh_user_capital_snapshot(usuario, client)
                active_position = usuario.get("active_position")
                if active_position:
                    self._manage_open_position(usuario, client)
                else:
                    existing_invoice = self.fee_manager.ensure_invoice_if_threshold_reached(telegram_id)
                    if existing_invoice:
                        continue
                    self._scan_and_open_trade(usuario, client, candidate_symbols)
                UsuarioModel.actualizar_engine_error(telegram_id, None)
            except CoinWApiError as exc:
                logger.warning("Usuario %s | CoinW error: %s", telegram_id, exc)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))
            except Exception as exc:
                logger.exception("Usuario %s | error inesperado", telegram_id)
                UsuarioModel.actualizar_engine_error(telegram_id, str(exc))

    def _refresh_user_capital_snapshot(self, usuario: Dict, client: ExchangeClient) -> None:
        quote_balance = client.obtener_balance_disponible(QUOTE_ASSET)
        capital_total = quote_balance
        active_position = usuario.get("active_position")
        if active_position:
            try:
                base_asset = active_position.get("base_asset")
                base_balance = client.obtener_balance_disponible(base_asset)
                last_price = Decimal(str(client.obtener_precio_actual(active_position["symbol"])))
                capital_total += base_balance * last_price
            except Exception:
                logger.debug("No se pudo valuar la posición activa del usuario %s", usuario["telegram_id"])
        capital_activo = float(capital_total) * CAPITAL_ACTIVO_PORC
        UsuarioModel.actualizar_capital_snapshot(usuario["telegram_id"], float(capital_total), capital_activo)

    def _get_candidate_symbols(self) -> List[str]:
        now = time.time()
        if self._cached_symbols and now - self._last_symbols_refresh < SYMBOL_REFRESH_SECONDS:
            return self._cached_symbols

        if DEFAULT_SYMBOLS:
            symbols = DEFAULT_SYMBOLS[:MAX_SYMBOLS_TO_SCAN]
        else:
            symbols = self._public_client.obtener_pares_disponibles(
                volumen_minimo=MIN_24H_QUOTE_VOLUME,
                quote_asset=QUOTE_ASSET,
                max_pairs=MAX_SYMBOLS_TO_SCAN,
            )

        self._symbol_rules = self._public_client.obtener_info_instrumentos()
        self._cached_symbols = [symbol for symbol in symbols if symbol in self._symbol_rules]
        self._last_symbols_refresh = now
        return self._cached_symbols

    def _scan_and_open_trade(self, usuario: Dict, client: ExchangeClient, symbols: List[str]) -> None:
        telegram_id = usuario["telegram_id"]
        available_quote = client.obtener_balance_disponible(QUOTE_ASSET)
        if available_quote < Decimal(str(MIN_USDT_ORDER)):
            return

        best_signal = None
        for symbol in symbols:
            signal = self._evaluate_symbol(symbol)
            if not signal:
                continue
            if not best_signal or signal["score"] > best_signal["score"]:
                best_signal = signal

        if not best_signal:
            return

        rule = self._symbol_rules[best_signal["symbol"]]
        quote_to_use = (available_quote * Decimal(str(CAPITAL_ACTIVO_PORC))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        min_required = max(rule.min_buy_amount, Decimal(str(MIN_USDT_ORDER)))
        if quote_to_use < min_required:
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

        position = {
            "symbol": best_signal["symbol"],
            "side": "LONG",
            "status": "OPEN",
            "order_number": order_number,
            "entry_price": float(fallback_price),
            "quantity": float(amount),
            "quote_asset": rule.quote_asset,
            "base_asset": rule.base_asset,
            "stop_loss": float(best_signal["stop_loss"]),
            "take_profit": float(best_signal["take_profit"]),
            "score": float(best_signal["score"]),
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "strategy": {
                "components": best_signal["components"],
                "timeframes": {
                    "trend": TREND_PERIOD_SECONDS,
                    "pullback": PULLBACK_PERIOD_SECONDS,
                    "entry": ENTRY_PERIOD_SECONDS,
                },
            },
        }
        UsuarioModel.guardar_posicion_activa(telegram_id, position)
        UsuarioModel.incrementar_stats(telegram_id, {"opened": 1})
        OperacionModel.registrar_operacion(
            {
                "telegram_id": telegram_id,
                "symbol": best_signal["symbol"],
                "side": "LONG",
                "status": "OPEN",
                "entry_price": float(fallback_price),
                "stop_loss": float(best_signal["stop_loss"]),
                "take_profit": float(best_signal["take_profit"]),
                "score": float(best_signal["score"]),
                "quantity": float(amount),
                "quote_amount": float(quote_to_use),
                "order_number": order_number,
                "opened_at": datetime.utcnow(),
                "quote_asset": rule.quote_asset,
                "base_asset": rule.base_asset,
                "components": best_signal["components"],
            }
        )
        self.notifier.send(
            telegram_id,
            (
                f"✅ Compra {'simulada' if DRY_RUN else 'ejecutada'}\n"
                f"Par: {best_signal['symbol']}\n"
                f"Entrada: {float(fallback_price):.8f}\n"
                f"SL: {best_signal['stop_loss']:.8f}\n"
                f"TP: {best_signal['take_profit']:.8f}\n"
                f"Score: {best_signal['score']}"
            ),
        )

    def _manage_open_position(self, usuario: Dict, client: ExchangeClient) -> None:
        telegram_id = usuario["telegram_id"]
        position = usuario.get("active_position")
        if not position:
            return

        symbol = position["symbol"]
        rule = self._symbol_rules.get(symbol) or self._public_client.obtener_info_instrumentos().get(symbol)
        if not rule:
            raise CoinWApiError(f"No hay reglas del instrumento para {symbol}")

        current_price = Decimal(str(client.obtener_precio_actual(symbol)))
        stop_loss = Decimal(str(position["stop_loss"]))
        take_profit = Decimal(str(position["take_profit"]))

        close_reason = None
        if current_price <= stop_loss:
            close_reason = "STOP_LOSS"
        elif current_price >= take_profit:
            close_reason = "TAKE_PROFIT"
        else:
            return

        available_base = client.obtener_balance_disponible(rule.base_asset)
        expected_qty = Decimal(str(position["quantity"]))
        quantity = min(expected_qty, available_base).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if quantity <= 0:
            UsuarioModel.limpiar_posicion_activa(telegram_id)
            OperacionModel.actualizar_operacion(
                {"telegram_id": telegram_id, "order_number": position["order_number"]},
                {"status": "EXTERNAL_CLOSE", "closed_at": datetime.utcnow()},
            )
            return

        if DRY_RUN:
            exit_price = current_price
            sell_order_number = f"dry-run-exit-{int(time.time())}"
        else:
            sell_order = client.crear_orden_mercado_sell(symbol, quantity, rule)
            sell_order_number = str(sell_order["orderNumber"])
            status = client.obtener_estado_orden(sell_order_number)
            fill = client.estimar_fill_desde_estado(status, fallback_price=current_price)
            exit_price = fill["avg_price"] or current_price
            quantity = fill["amount"] or quantity
            if quantity <= 0:
                quantity = min(expected_qty, available_base).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        entry_price = Decimal(str(position["entry_price"]))
        pnl_quote = (exit_price - entry_price) * quantity
        pnl_pct = (pnl_quote / (entry_price * quantity) * Decimal("100")) if entry_price > 0 and quantity > 0 else Decimal("0")

        UsuarioModel.limpiar_posicion_activa(telegram_id)
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
            {"telegram_id": telegram_id, "order_number": position["order_number"]},
            {
                "status": close_reason,
                "exit_price": float(exit_price),
                "exit_order_number": sell_order_number,
                "closed_at": datetime.utcnow(),
                "pnl_quote": float(pnl_quote),
                "pnl_pct": float(pnl_pct),
                "quantity_closed": float(quantity),
            },
        )

        operacion_cerrada = OperacionModel.obtener_operacion(
            {"telegram_id": telegram_id, "order_number": position["order_number"]}
        ) or {
            "telegram_id": telegram_id,
            "order_number": position["order_number"],
            "pnl_quote": float(pnl_quote),
        }
        fee_generada = self.fee_manager.registrar_fee_operacion(usuario, operacion_cerrada)
        invoice = self.fee_manager.ensure_invoice_if_threshold_reached(telegram_id)

        message = (
            f"{'🟢' if pnl_quote > 0 else '🔴'} Posición cerrada\n"
            f"Par: {symbol}\n"
            f"Motivo: {close_reason}\n"
            f"Entrada: {float(entry_price):.8f}\n"
            f"Salida: {float(exit_price):.8f}\n"
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

    def _evaluate_symbol(self, symbol: str) -> Optional[Dict]:
        try:
            df_trend = self._public_client.obtener_klines(symbol, TREND_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            df_pullback = self._public_client.obtener_klines(symbol, PULLBACK_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            df_entry = self._public_client.obtener_klines(symbol, ENTRY_PERIOD_SECONDS, limit=CANDLE_LIMIT)
            signal = self.strategy.analizar(df_trend, df_pullback, df_entry)
            if not signal:
                return None
            signal["symbol"] = symbol
            return signal
        except Exception as exc:
            logger.debug("No hubo señal en %s: %s", symbol, exc)
            return None
