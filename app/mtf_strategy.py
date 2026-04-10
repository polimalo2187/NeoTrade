from decimal import Decimal
from typing import Dict, Optional

import pandas as pd

from app.config import (
    DYNAMIC_TP_ACTIVATION_R,
    EMA_FAST,
    EMA_SLOW,
    MAX_SCORE,
    MIN_SIGNAL_SCORE,
    RECENT_SWING_LOOKBACK,
    RSI_PERIOD,
    RSI_PULLBACK_MAX,
    RSI_PULLBACK_MIN,
    RSI_TREND_MIN,
    STOP_LOSS_PORC,
    WEAKNESS_CONFIRMATIONS_REQUIRED,
    WEAKNESS_MIN_SCORE,
)


class MTFStrategy:
    """Estrategia MTF LONG para Spot con manager persistente.

    La estrategia decide:
    - entrada
    - SL mental inicial
    - precio de activación del TP dinámico
    - salida por pérdida de fuerza
    """

    @staticmethod
    def _rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        data["ema_fast"] = data["close"].ewm(span=EMA_FAST, adjust=False, min_periods=EMA_FAST).mean()
        data["ema_slow"] = data["close"].ewm(span=EMA_SLOW, adjust=False, min_periods=EMA_SLOW).mean()
        data["rsi"] = MTFStrategy._rsi(data["close"], RSI_PERIOD)
        data["volume_sma"] = data["volume"].rolling(20, min_periods=1).mean()
        data["date_ms"] = (pd.to_datetime(data["date"], utc=True).astype("int64") // 1_000_000).astype("int64")
        return data

    @staticmethod
    def is_trend_bullish(df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        return bool(last["ema_fast"] > last["ema_slow"] and last["rsi"] >= RSI_TREND_MIN)

    @staticmethod
    def pullback_confirmation(df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        return bool(last["close"] >= last["ema_fast"] and RSI_PULLBACK_MIN <= last["rsi"] <= RSI_PULLBACK_MAX)

    @staticmethod
    def entry_confirmation(df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        bullish_reclaim = prev["close"] <= prev["ema_fast"] and last["close"] > last["ema_fast"]
        return bool(last["ema_fast"] > last["ema_slow"] and last["rsi"] >= RSI_TREND_MIN and bullish_reclaim)

    @staticmethod
    def _calc_initial_stop(df_entry: pd.DataFrame, entry_price: float) -> float:
        recent_low = float(df_entry["low"].tail(RECENT_SWING_LOOKBACK).min())
        structural_stop = recent_low * 0.999
        fallback_stop = entry_price * (1 - STOP_LOSS_PORC)
        if structural_stop <= 0 or structural_stop >= entry_price:
            candidate_stop = fallback_stop
        else:
            candidate_stop = structural_stop
        return round(candidate_stop, 8)

    @staticmethod
    def _calc_dynamic_activation(entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        if risk <= 0:
            risk = entry_price * STOP_LOSS_PORC
        activation = entry_price + (risk * DYNAMIC_TP_ACTIVATION_R)
        return round(activation, 8)

    def analizar(
        self,
        df_trend: pd.DataFrame,
        df_pullback: pd.DataFrame,
        df_entry: pd.DataFrame,
    ) -> Optional[Dict]:
        if min(len(df_trend), len(df_pullback), len(df_entry)) < max(EMA_SLOW + 5, RSI_PERIOD + 5):
            return None

        df_trend = self.add_indicators(df_trend)
        df_pullback = self.add_indicators(df_pullback)
        df_entry = self.add_indicators(df_entry)

        score = 0.0
        components = []

        if not self.is_trend_bullish(df_trend):
            return None
        score += 35
        components.append(("trend", 35))

        if not self.pullback_confirmation(df_pullback):
            return None
        score += 25
        components.append(("pullback", 25))

        if not self.entry_confirmation(df_entry):
            return None
        score += 25
        components.append(("entry_confirm", 25))

        last = df_entry.iloc[-1]
        prev = df_entry.iloc[-2]

        if last["close"] > prev["high"]:
            score += 10
            components.append(("break_prev_high", 10))

        if last["volume"] > df_entry["volume"].tail(20).mean():
            score += 5
            components.append(("volume_bonus", 5))

        score = min(MAX_SCORE, round(score, 2))
        if score < MIN_SIGNAL_SCORE:
            return None

        entry_price = round(float(last["close"]), 8)
        initial_stop_loss = self._calc_initial_stop(df_entry, entry_price)
        dynamic_tp_activation_price = self._calc_dynamic_activation(entry_price, initial_stop_loss)
        risk_per_unit = round(entry_price - initial_stop_loss, 8)
        if risk_per_unit <= 0:
            return None

        return {
            "direction": "LONG",
            "entry_price": entry_price,
            "initial_stop_loss": initial_stop_loss,
            "dynamic_tp_activation_price": dynamic_tp_activation_price,
            "risk_per_unit": risk_per_unit,
            "score": score,
            "components": components,
            "entry_candle_ts": int(last["date_ms"]),
            "manager_rules": {
                "weakness_confirmations_required": WEAKNESS_CONFIRMATIONS_REQUIRED,
                "weakness_min_score": WEAKNESS_MIN_SCORE,
                "recent_swing_lookback": RECENT_SWING_LOOKBACK,
                "tp_activation_r": DYNAMIC_TP_ACTIVATION_R,
            },
        }

    def process_manager_candle(self, state: Dict, row: pd.Series, previous_row: Optional[pd.Series] = None) -> Dict:
        """Aplica una vela cerrada al manager persistente.

        Devuelve updates de estado y, si corresponde, una señal de salida.
        """
        updates: Dict = {}
        events = []
        exit_signal = None

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        candle_ts = int(row["date_ms"])
        candle_iso = pd.to_datetime(row["date"], utc=True).isoformat()

        highest_price_seen = max(float(state.get("highest_price_seen") or 0.0), high)
        highest_close_seen = max(float(state.get("highest_close_seen") or 0.0), close)
        updates["highest_price_seen"] = round(highest_price_seen, 8)
        updates["highest_close_seen"] = round(highest_close_seen, 8)
        if highest_price_seen > float(state.get("highest_price_seen") or 0.0):
            updates["highest_price_seen_at"] = candle_iso
            events.append({"type": "NEW_HIGH_SEEN", "payload": {"price": round(highest_price_seen, 8), "at": candle_iso}})

        entry_price = float(state["entry_price"])
        quantity = float(state.get("quantity") or 0.0)
        initial_stop_loss = float(state.get("initial_stop_loss") or state.get("effective_stop_loss") or 0.0)
        risk_per_unit = max(float(state.get("risk_per_unit") or (entry_price - initial_stop_loss)), 1e-12)
        max_unrealized_pnl = max(float(state.get("max_unrealized_pnl") or 0.0), max(0.0, (high - entry_price) * quantity))
        max_r_multiple = max(float(state.get("max_r_multiple") or 0.0), max(0.0, (high - entry_price) / risk_per_unit))
        updates["max_unrealized_pnl"] = round(max_unrealized_pnl, 8)
        updates["max_r_multiple"] = round(max_r_multiple, 8)
        updates["last_processed_candle_ts"] = candle_ts
        updates["last_processed_price"] = round(close, 8)

        effective_stop = float(state.get("effective_stop_loss") or initial_stop_loss)
        if low <= effective_stop:
            exit_signal = {
                "reason": "STOP_LOSS",
                "trigger_price": round(effective_stop, 8),
                "triggered_at": candle_iso,
                "source": "replay",
            }
            events.append({"type": "STOP_LOSS_TRIGGERED", "payload": exit_signal})
            return {"updates": updates, "events": events, "exit_signal": exit_signal}

        dynamic_active = bool(state.get("dynamic_tp_active"))
        activation_price = float(state.get("dynamic_tp_activation_price") or 0.0)
        if not dynamic_active and high >= activation_price > 0:
            dynamic_active = True
            updates["dynamic_tp_active"] = True
            updates["dynamic_tp_activated_at"] = candle_iso
            updates["weakness_confirmations"] = 0
            events.append(
                {
                    "type": "DYNAMIC_TP_ACTIVATED",
                    "payload": {"activation_price": round(activation_price, 8), "at": candle_iso},
                }
            )

        weakness_score = 0
        weakness_reasons = []
        if dynamic_active and previous_row is not None:
            if close < float(row.get("ema_fast", close)):
                weakness_score += 1
                weakness_reasons.append("close_below_ema_fast")
            if close < float(previous_row["close"]):
                weakness_score += 1
                weakness_reasons.append("lower_close")
            if high <= float(previous_row["high"]) and low <= float(previous_row["low"]):
                weakness_score += 1
                weakness_reasons.append("lower_high_low")
            if float(row.get("rsi", 50.0)) < max(RSI_TREND_MIN - 2, float(previous_row.get("rsi", 50.0)) - 1.5):
                weakness_score += 1
                weakness_reasons.append("rsi_weakness")
            if float(row.get("volume", 0.0)) < float(row.get("volume_sma", row.get("volume", 0.0))):
                weakness_score += 1
                weakness_reasons.append("volume_below_mean")

        updates["weakness_last_score"] = weakness_score
        updates["weakness_last_reason"] = weakness_reasons

        current_confirmations = int(state.get("weakness_confirmations") or 0)
        if dynamic_active:
            if weakness_score >= int(state.get("manager_rules", {}).get("weakness_min_score", WEAKNESS_MIN_SCORE)):
                current_confirmations += 1
            else:
                current_confirmations = 0
            updates["weakness_confirmations"] = current_confirmations

            required = int(
                state.get("manager_rules", {}).get(
                    "weakness_confirmations_required",
                    WEAKNESS_CONFIRMATIONS_REQUIRED,
                )
            )
            if current_confirmations >= required:
                exit_signal = {
                    "reason": "WEAKNESS_EXIT",
                    "trigger_price": round(close, 8),
                    "triggered_at": candle_iso,
                    "source": "replay",
                    "weakness_score": weakness_score,
                    "weakness_reasons": weakness_reasons,
                }
                events.append({"type": "WEAKNESS_EXIT_TRIGGERED", "payload": exit_signal})

        return {"updates": updates, "events": events, "exit_signal": exit_signal}

    @staticmethod
    def process_live_price(state: Dict, current_price: float) -> Dict:
        updates: Dict = {}
        events = []
        exit_signal = None

        highest_price_seen = max(float(state.get("highest_price_seen") or 0.0), current_price)
        updates["highest_price_seen"] = round(highest_price_seen, 8)
        if highest_price_seen > float(state.get("highest_price_seen") or 0.0):
            updates["highest_price_seen_at"] = pd.Timestamp.utcnow().isoformat()
            events.append({"type": "NEW_HIGH_LIVE", "payload": {"price": round(highest_price_seen, 8)}})

        entry_price = float(state["entry_price"])
        quantity = float(state.get("quantity") or 0.0)
        initial_stop_loss = float(state.get("initial_stop_loss") or state.get("effective_stop_loss") or 0.0)
        risk_per_unit = max(float(state.get("risk_per_unit") or (entry_price - initial_stop_loss)), 1e-12)
        max_unrealized_pnl = max(float(state.get("max_unrealized_pnl") or 0.0), max(0.0, (current_price - entry_price) * quantity))
        max_r_multiple = max(float(state.get("max_r_multiple") or 0.0), max(0.0, (current_price - entry_price) / risk_per_unit))
        updates["max_unrealized_pnl"] = round(max_unrealized_pnl, 8)
        updates["max_r_multiple"] = round(max_r_multiple, 8)
        updates["last_processed_price"] = round(current_price, 8)

        effective_stop = float(state.get("effective_stop_loss") or initial_stop_loss)
        if current_price <= effective_stop:
            exit_signal = {
                "reason": "STOP_LOSS",
                "trigger_price": round(effective_stop, 8),
                "triggered_at": None,
                "source": "live",
            }
            events.append({"type": "STOP_LOSS_LIVE", "payload": exit_signal})
            return {"updates": updates, "events": events, "exit_signal": exit_signal}

        if not bool(state.get("dynamic_tp_active")):
            activation_price = float(state.get("dynamic_tp_activation_price") or 0.0)
            if current_price >= activation_price > 0:
                updates["dynamic_tp_active"] = True
                updates["dynamic_tp_activated_at"] = pd.Timestamp.utcnow().isoformat()
                updates["weakness_confirmations"] = 0
                events.append({"type": "DYNAMIC_TP_ACTIVATED_LIVE", "payload": {"activation_price": round(activation_price, 8)}})

        return {"updates": updates, "events": events, "exit_signal": exit_signal}
