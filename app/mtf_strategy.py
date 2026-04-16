from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.config import (
    ATR_PERIOD,
    BREAK_EVEN_OFFSET_R,
    DYNAMIC_TP_ACTIVATION_R,
    EMA_FAST,
    EMA_SLOW,
    ENTRY_MIN_BODY_RATIO,
    ENTRY_MIN_CLOSE_POSITION,
    ENTRY_MIN_VOLUME_RATIO,
    MAX_ATR_PCT,
    MAX_SCORE,
    MAX_STOP_DISTANCE_PCT,
    MIN_ATR_PCT,
    MIN_SIGNAL_SCORE,
    PULLBACK_LOOKBACK,
    PULLBACK_MAX_DEPTH_PCT,
    PULLBACK_MIN_DEPTH_PCT,
    RECENT_SWING_LOOKBACK,
    RSI_PERIOD,
    RSI_PULLBACK_MAX,
    RSI_PULLBACK_MIN,
    RSI_TREND_MIN,
    STOP_LOSS_PORC,
    TRAIL_STOP_ATR_MULTIPLIER,
    TP1_PARTIAL_FRACTION,
    TP1_PARTIAL_MIN_QUOTE,
    TREND_EMA_FAST_SLOPE_MIN,
    TREND_EMA_SLOW_SLOPE_MIN,
    WEAKNESS_CONFIRMATIONS_REQUIRED,
    WEAKNESS_MIN_SCORE,
    WEAKNESS_RSI_DELTA,
)


class MTFStrategy:
    """Estrategia MTF LONG endurecida para Spot con manager persistente.

    Filosofía:
    - detectar tendencia sana, no solo cruces de EMA
    - exigir pullback real y no mera lateralidad
    - entrar solo con reclaim/continuación de calidad
    - rechazar stops demasiado anchos si se usa casi todo el capital
    - gestionar la salida con activación dinámica + trailing mental + pérdida de fuerza
    """

    @staticmethod
    def _rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss_safe = avg_loss.mask(avg_loss == 0)
        rs = avg_gain / avg_loss_safe
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(avg_loss != 0, 100.0)
        rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
        return pd.to_numeric(rsi, errors="coerce").fillna(50.0)

    @staticmethod
    def _atr(df: pd.DataFrame, period: int) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                (df["high"] - df["low"]).abs(),
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().bfill()

    @staticmethod
    def _body_ratio(row: pd.Series) -> float:
        candle_range = max(float(row["high"] - row["low"]), 1e-12)
        body = abs(float(row["close"] - row["open"]))
        return body / candle_range

    @staticmethod
    def _close_position(row: pd.Series) -> float:
        candle_range = max(float(row["high"] - row["low"]), 1e-12)
        return (float(row["close"]) - float(row["low"])) / candle_range

    @staticmethod
    def _slope_pct(series: pd.Series, lookback: int = 3) -> float:
        if len(series) <= lookback:
            return 0.0
        base = float(series.iloc[-1 - lookback])
        if abs(base) < 1e-12:
            return 0.0
        return (float(series.iloc[-1]) - base) / base

    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        data["ema_fast"] = data["close"].ewm(span=EMA_FAST, adjust=False, min_periods=EMA_FAST).mean()
        data["ema_slow"] = data["close"].ewm(span=EMA_SLOW, adjust=False, min_periods=EMA_SLOW).mean()
        data["rsi"] = MTFStrategy._rsi(data["close"], RSI_PERIOD)
        data["atr"] = MTFStrategy._atr(data, ATR_PERIOD)
        data["atr_pct"] = (data["atr"] / data["close"].replace(0, pd.NA)).fillna(0.0)
        data["volume_sma"] = data["volume"].rolling(20, min_periods=1).mean()
        volume_sma = pd.to_numeric(data["volume_sma"], errors="coerce")
        volume_denom = volume_sma.where(volume_sma != 0)
        data["volume_ratio"] = (pd.to_numeric(data["volume"], errors="coerce") / volume_denom).fillna(1.0)
        data["date_ms"] = (pd.to_datetime(data["date"], utc=True).astype("int64") // 1_000_000).astype("int64")
        return data.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr"]).reset_index(drop=True)

    def _trend_filter(self, df: pd.DataFrame) -> Tuple[bool, float, List[Tuple[str, float]], Dict]:
        last = df.iloc[-1]
        fast_slope = self._slope_pct(df["ema_fast"], 3)
        slow_slope = self._slope_pct(df["ema_slow"], 3)
        atr_pct = float(last["atr_pct"])

        fast_slope_gate = TREND_EMA_FAST_SLOPE_MIN * 0.5
        slow_slope_gate = TREND_EMA_SLOW_SLOPE_MIN * 0.5
        rsi_gate = max(RSI_TREND_MIN - 2, 45)

        bullish_stack = float(last["ema_fast"]) > float(last["ema_slow"]) and float(last["close"]) >= float(last["ema_fast"]) * 0.998
        slope_ok = fast_slope >= fast_slope_gate and slow_slope >= slow_slope_gate
        rsi_ok = float(last["rsi"]) >= rsi_gate
        vol_ok = MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT
        higher_close = float(last["close"]) >= float(df.iloc[-4]["close"]) * 0.997 if len(df) >= 4 else True

        passed = bullish_stack and slope_ok and rsi_ok and vol_ok and higher_close
        score = 0.0
        components: List[Tuple[str, float]] = []
        if passed:
            score += 20
            components.append(("trend_context", 20))
            if fast_slope >= TREND_EMA_FAST_SLOPE_MIN * 1.25:
                score += 8
                components.append(("trend_fast_slope", 8))
            if slow_slope >= TREND_EMA_SLOW_SLOPE_MIN * 1.2:
                score += 5
                components.append(("trend_slow_slope", 5))
            if float(last["rsi"]) >= RSI_TREND_MIN + 2:
                score += 4
                components.append(("trend_rsi_strength", 4))
            if atr_pct >= max(MIN_ATR_PCT * 1.1, 0.0) and atr_pct <= MAX_ATR_PCT * 0.85:
                score += 3
                components.append(("trend_volatility_ok", 3))
        info = {
            "fast_slope": round(fast_slope, 6),
            "slow_slope": round(slow_slope, 6),
            "atr_pct": round(atr_pct, 6),
            "rsi": round(float(last["rsi"]), 2),
            "bullish_stack": bullish_stack,
            "slope_ok": slope_ok,
            "rsi_ok": rsi_ok,
            "vol_ok": vol_ok,
            "higher_close": higher_close,
            "fast_slope_gate": round(fast_slope_gate, 6),
            "slow_slope_gate": round(slow_slope_gate, 6),
            "rsi_gate": round(rsi_gate, 2),
        }
        return passed, score, components, info

    def _pullback_filter(self, df: pd.DataFrame) -> Tuple[bool, float, List[Tuple[str, float]], Dict]:
        last = df.iloc[-1]
        window = df.tail(PULLBACK_LOOKBACK)
        recent_high = float(window["high"].max())
        recent_low = float(window["low"].min())
        last_close = float(last["close"])
        depth_pct = 0.0 if recent_high <= 0 else max(0.0, (recent_high - last_close) / recent_high)

        low_below_fast = int((window["low"] < window["ema_fast"]).sum())
        close_below_fast = int((window["close"] < window["ema_fast"]).sum())
        real_pullback = low_below_fast >= 1 or close_below_fast >= 1
        trend_intact = recent_low > float(last["ema_slow"]) * 0.99
        rsi_min_gate = max(RSI_PULLBACK_MIN - 2, 35)
        rsi_max_gate = min(RSI_PULLBACK_MAX + 4, 75)
        rsi_ok = rsi_min_gate <= float(last["rsi"]) <= rsi_max_gate
        reclaim_fast = last_close >= float(last["ema_fast"]) * 0.997
        min_depth_gate = max(PULLBACK_MIN_DEPTH_PCT * 0.5, 0.0005)
        max_depth_gate = max(PULLBACK_MAX_DEPTH_PCT * 1.15, min_depth_gate)
        depth_ok = min_depth_gate <= depth_pct <= max_depth_gate
        passed = real_pullback and trend_intact and rsi_ok and reclaim_fast and depth_ok

        score = 0.0
        components: List[Tuple[str, float]] = []
        if passed:
            score += 15
            components.append(("pullback_valid", 15))
            ideal_mid = (min_depth_gate + max_depth_gate) / 2
            if abs(depth_pct - ideal_mid) <= (max_depth_gate - min_depth_gate) * 0.22:
                score += 8
                components.append(("pullback_depth_ideal", 8))
            if float(last["rsi"]) <= (rsi_min_gate + rsi_max_gate) / 2:
                score += 4
                components.append(("pullback_rsi_cooldown", 4))
            if int((window["close"] < window["open"]).sum()) >= 1:
                score += 3
                components.append(("pullback_bearish_sequence", 3))
        info = {
            "depth_pct": round(depth_pct, 6),
            "recent_high": round(recent_high, 8),
            "recent_low": round(recent_low, 8),
            "rsi": round(float(last["rsi"]), 2),
            "real_pullback": real_pullback,
            "trend_intact": trend_intact,
            "rsi_ok": rsi_ok,
            "reclaim_fast": reclaim_fast,
            "depth_ok": depth_ok,
            "low_below_fast": low_below_fast,
            "close_below_fast": close_below_fast,
            "min_depth_gate": round(min_depth_gate, 6),
            "max_depth_gate": round(max_depth_gate, 6),
            "rsi_min_gate": round(rsi_min_gate, 2),
            "rsi_max_gate": round(rsi_max_gate, 2),
        }
        return passed, score, components, info

    def _entry_filter(self, df: pd.DataFrame) -> Tuple[bool, float, List[Tuple[str, float]], Dict]:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3] if len(df) >= 3 else prev

        body_ratio_gate = max(ENTRY_MIN_BODY_RATIO * 0.85, 0.22)
        close_position_gate = max(ENTRY_MIN_CLOSE_POSITION - 0.08, 0.45)
        volume_ratio_gate = max(ENTRY_MIN_VOLUME_RATIO - 0.1, 0.75)

        bullish_reclaim = (
            float(prev["low"]) <= float(prev["ema_fast"]) * 1.003 and
            float(last["close"]) >= float(last["ema_fast"]) * 0.998 and
            float(last["close"]) >= float(prev["high"]) * 0.998
        )
        bullish_body = float(last["close"]) > float(last["open"])
        body_ratio = self._body_ratio(last)
        close_position = self._close_position(last)
        volume_ratio = float(last.get("volume_ratio", 1.0))
        rsi_reaccel = float(last["rsi"]) >= float(prev["rsi"]) - 0.5 and float(prev["rsi"]) >= float(prev2["rsi"]) - 1.0
        extension_vs_ema = (float(last["close"]) - float(last["ema_fast"])) / max(float(last["close"]), 1e-12)
        extension_ok = extension_vs_ema <= max(float(last["atr_pct"]) * 1.5, 0.018)

        passed = (
            bullish_reclaim
            and bullish_body
            and body_ratio >= body_ratio_gate
            and close_position >= close_position_gate
            and volume_ratio >= volume_ratio_gate
            and rsi_reaccel
            and extension_ok
        )

        score = 0.0
        components: List[Tuple[str, float]] = []
        if passed:
            score += 20
            components.append(("entry_reclaim", 20))
            if body_ratio >= body_ratio_gate + 0.10:
                score += 8
                components.append(("entry_body_quality", 8))
            if close_position >= close_position_gate + 0.10:
                score += 6
                components.append(("entry_close_strength", 6))
            if volume_ratio >= volume_ratio_gate + 0.12:
                score += 6
                components.append(("entry_volume_confirm", 6))
            if float(last["close"]) >= float(df.tail(5)["high"].max()) * 0.997:
                score += 5
                components.append(("entry_micro_breakout", 5))
        info = {
            "body_ratio": round(body_ratio, 6),
            "close_position": round(close_position, 6),
            "volume_ratio": round(volume_ratio, 6),
            "extension_vs_ema": round(extension_vs_ema, 6),
            "rsi": round(float(last["rsi"]), 2),
            "bullish_reclaim": bullish_reclaim,
            "bullish_body": bullish_body,
            "rsi_reaccel": rsi_reaccel,
            "extension_ok": extension_ok,
            "body_ratio_gate": round(body_ratio_gate, 6),
            "close_position_gate": round(close_position_gate, 6),
            "volume_ratio_gate": round(volume_ratio_gate, 6),
        }
        return passed, score, components, info

    @staticmethod
    def _calc_initial_stop(df_entry: pd.DataFrame, entry_price: float) -> float:
        recent = df_entry.tail(RECENT_SWING_LOOKBACK)
        recent_low = float(recent["low"].min())
        atr = float(df_entry.iloc[-1].get("atr", 0.0) or 0.0)
        structural_stop = recent_low - (atr * 0.25)
        fallback_stop = entry_price * (1 - STOP_LOSS_PORC)
        if structural_stop <= 0 or structural_stop >= entry_price:
            candidate_stop = fallback_stop
        else:
            candidate_stop = min(structural_stop, fallback_stop)
        return round(candidate_stop, 8)

    @staticmethod
    def _calc_dynamic_activation(entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        if risk <= 0:
            risk = entry_price * STOP_LOSS_PORC
        activation = entry_price + (risk * DYNAMIC_TP_ACTIVATION_R)
        return round(activation, 8)

    def analizar_detallado(
        self,
        df_trend: pd.DataFrame,
        df_pullback: pd.DataFrame,
        df_entry: pd.DataFrame,
    ) -> Dict[str, Any]:
        required_len = max(EMA_SLOW + 8, ATR_PERIOD + 8, RSI_PERIOD + 8)
        raw_lengths = {
            "trend_len": len(df_trend),
            "pullback_len": len(df_pullback),
            "entry_len": len(df_entry),
            "required_len": required_len,
        }
        if min(len(df_trend), len(df_pullback), len(df_entry)) < required_len:
            return {
                "accepted": False,
                "reason": "INSUFFICIENT_RAW_CANDLES",
                "detail": raw_lengths,
                "signal": None,
            }

        df_trend = self.add_indicators(df_trend)
        df_pullback = self.add_indicators(df_pullback)
        df_entry = self.add_indicators(df_entry)
        indicator_lengths = {
            "trend_len": len(df_trend),
            "pullback_len": len(df_pullback),
            "entry_len": len(df_entry),
        }
        if min(len(df_trend), len(df_pullback), len(df_entry)) < 10:
            return {
                "accepted": False,
                "reason": "INSUFFICIENT_INDICATOR_CANDLES",
                "detail": indicator_lengths,
                "signal": None,
            }

        score = 0.0
        components: List[Tuple[str, float]] = []

        trend_ok, trend_score, trend_components, trend_info = self._trend_filter(df_trend)
        if not trend_ok:
            return {
                "accepted": False,
                "reason": "TREND_FILTER_REJECTED",
                "detail": {**trend_info, "score_partial": round(score, 2)},
                "signal": None,
            }
        score += trend_score
        components.extend(trend_components)

        pullback_ok, pullback_score, pullback_components, pullback_info = self._pullback_filter(df_pullback)
        if not pullback_ok:
            return {
                "accepted": False,
                "reason": "PULLBACK_FILTER_REJECTED",
                "detail": {**pullback_info, "score_partial": round(score, 2)},
                "signal": None,
            }
        score += pullback_score
        components.extend(pullback_components)

        entry_ok, entry_score, entry_components, entry_info = self._entry_filter(df_entry)
        if not entry_ok:
            return {
                "accepted": False,
                "reason": "ENTRY_FILTER_REJECTED",
                "detail": {**entry_info, "score_partial": round(score, 2)},
                "signal": None,
            }
        score += entry_score
        components.extend(entry_components)

        last = df_entry.iloc[-1]
        entry_price = round(float(last["close"]), 8)
        initial_stop_loss = self._calc_initial_stop(df_entry, entry_price)
        risk_per_unit = round(entry_price - initial_stop_loss, 8)
        if risk_per_unit <= 0:
            return {
                "accepted": False,
                "reason": "INVALID_RISK_PER_UNIT",
                "detail": {
                    "entry_price": entry_price,
                    "initial_stop_loss": initial_stop_loss,
                    "risk_per_unit": risk_per_unit,
                },
                "signal": None,
            }

        stop_distance_pct = risk_per_unit / max(entry_price, 1e-12)
        if stop_distance_pct > MAX_STOP_DISTANCE_PCT:
            return {
                "accepted": False,
                "reason": "STOP_DISTANCE_TOO_WIDE",
                "detail": {
                    "entry_price": entry_price,
                    "initial_stop_loss": initial_stop_loss,
                    "stop_distance_pct": round(stop_distance_pct, 6),
                    "max_stop_distance_pct": round(MAX_STOP_DISTANCE_PCT, 6),
                },
                "signal": None,
            }

        dynamic_tp_activation_price = self._calc_dynamic_activation(entry_price, initial_stop_loss)
        if dynamic_tp_activation_price <= entry_price:
            return {
                "accepted": False,
                "reason": "INVALID_DYNAMIC_TP",
                "detail": {
                    "entry_price": entry_price,
                    "initial_stop_loss": initial_stop_loss,
                    "dynamic_tp_activation_price": dynamic_tp_activation_price,
                },
                "signal": None,
            }

        if stop_distance_pct <= MAX_STOP_DISTANCE_PCT * 0.55:
            score += 5
            components.append(("risk_distance_compact", 5))
        if float(last["atr_pct"]) >= MIN_ATR_PCT * 1.4:
            score += 3
            components.append(("entry_volatility_supported", 3))

        score = min(MAX_SCORE, round(score, 2))
        if score < MIN_SIGNAL_SCORE:
            return {
                "accepted": False,
                "reason": "SCORE_TOO_LOW",
                "detail": {
                    "score": score,
                    "min_signal_score": MIN_SIGNAL_SCORE,
                    "trend": trend_info,
                    "pullback": pullback_info,
                    "entry": entry_info,
                    "components": components,
                    "stop_distance_pct": round(stop_distance_pct, 6),
                },
                "signal": None,
            }

        signal = {
            "direction": "LONG",
            "entry_price": entry_price,
            "initial_stop_loss": initial_stop_loss,
            "dynamic_tp_activation_price": dynamic_tp_activation_price,
            "risk_per_unit": risk_per_unit,
            "score": score,
            "components": components,
            "entry_candle_ts": int(last["date_ms"]),
            "strategy_meta": {
                "trend": trend_info,
                "pullback": pullback_info,
                "entry": entry_info,
                "stop_distance_pct": round(stop_distance_pct, 6),
                "atr_pct": round(float(last["atr_pct"]), 6),
            },
            "manager_rules": {
                "weakness_confirmations_required": WEAKNESS_CONFIRMATIONS_REQUIRED,
                "weakness_min_score": WEAKNESS_MIN_SCORE,
                "recent_swing_lookback": RECENT_SWING_LOOKBACK,
                "tp_activation_r": DYNAMIC_TP_ACTIVATION_R,
                "break_even_offset_r": BREAK_EVEN_OFFSET_R,
                "trail_stop_atr_multiplier": TRAIL_STOP_ATR_MULTIPLIER,
                "weakness_rsi_delta": WEAKNESS_RSI_DELTA,
                "tp1_partial_min_quote": TP1_PARTIAL_MIN_QUOTE,
                "tp1_partial_fraction": TP1_PARTIAL_FRACTION,
            },
        }
        return {
            "accepted": True,
            "reason": "OK",
            "detail": {
                "score": score,
                "entry_price": entry_price,
                "stop_distance_pct": round(stop_distance_pct, 6),
            },
            "signal": signal,
        }

    def analizar(
        self,
        df_trend: pd.DataFrame,
        df_pullback: pd.DataFrame,
        df_entry: pd.DataFrame,
    ) -> Optional[Dict]:
        diagnostic = self.analizar_detallado(df_trend, df_pullback, df_entry)
        return diagnostic.get("signal")

    def process_manager_candle(self, state: Dict, row: pd.Series, previous_row: Optional[pd.Series] = None) -> Dict:
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

        manager_rules = state.get("strategy", {}).get("manager_rules") or state.get("manager_rules") or {}
        dynamic_active = bool(state.get("dynamic_tp_active"))
        activation_price = float(state.get("dynamic_tp_activation_price") or 0.0)
        if not dynamic_active and high >= activation_price > 0:
            dynamic_active = True
            updates["dynamic_tp_active"] = True
            updates["dynamic_tp_activated_at"] = candle_iso
            updates["weakness_confirmations"] = 0
            events.append({
                "type": "DYNAMIC_TP_ACTIVATED",
                "payload": {"activation_price": round(activation_price, 8), "at": candle_iso},
            })

        if dynamic_active:
            break_even_offset_r = float(manager_rules.get("break_even_offset_r", BREAK_EVEN_OFFSET_R))
            trail_atr_mult = float(manager_rules.get("trail_stop_atr_multiplier", TRAIL_STOP_ATR_MULTIPLIER))
            atr = float(row.get("atr", 0.0) or 0.0)
            break_even_stop = entry_price + (risk_per_unit * break_even_offset_r)
            ema_trail = float(row.get("ema_fast", close)) - (atr * trail_atr_mult)
            prev_low_anchor = float(previous_row["low"]) if previous_row is not None else close
            structure_trail = prev_low_anchor - (atr * 0.25)
            trail_candidate = max(effective_stop, break_even_stop, ema_trail, structure_trail)
            trail_candidate = min(trail_candidate, close)
            if trail_candidate > effective_stop:
                updates["effective_stop_loss"] = round(trail_candidate, 8)
                effective_stop = float(updates["effective_stop_loss"])
                events.append({
                    "type": "TRAIL_STOP_RAISED",
                    "payload": {"new_stop": round(trail_candidate, 8), "at": candle_iso},
                })

        weakness_score = 0
        weakness_reasons: List[str] = []
        if dynamic_active and previous_row is not None:
            if close < float(row.get("ema_fast", close)):
                weakness_score += 1
                weakness_reasons.append("close_below_ema_fast")
            if close < float(previous_row["close"]):
                weakness_score += 1
                weakness_reasons.append("lower_close")
            if close < float(previous_row["low"]):
                weakness_score += 1
                weakness_reasons.append("close_below_prev_low")
            if high <= float(previous_row["high"]) and low <= float(previous_row["low"]):
                weakness_score += 1
                weakness_reasons.append("lower_high_low")
            if self._close_position(row) < 0.45:
                weakness_score += 1
                weakness_reasons.append("weak_close_position")
            prev_rsi = float(previous_row.get("rsi", 50.0))
            current_rsi = float(row.get("rsi", 50.0))
            weakness_rsi_delta = float(manager_rules.get("weakness_rsi_delta", WEAKNESS_RSI_DELTA))
            if current_rsi <= prev_rsi - weakness_rsi_delta:
                weakness_score += 1
                weakness_reasons.append("rsi_rollover")
            if float(row.get("volume_ratio", 1.0)) < 0.9:
                weakness_score += 1
                weakness_reasons.append("volume_fade")

        updates["weakness_last_score"] = weakness_score
        updates["weakness_last_reason"] = weakness_reasons

        current_confirmations = int(state.get("weakness_confirmations") or 0)
        if dynamic_active:
            if weakness_score >= int(manager_rules.get("weakness_min_score", WEAKNESS_MIN_SCORE)):
                current_confirmations += 1
            else:
                current_confirmations = 0
            updates["weakness_confirmations"] = current_confirmations

            required = int(manager_rules.get("weakness_confirmations_required", WEAKNESS_CONFIRMATIONS_REQUIRED))
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
                break_even_offset_r = float((state.get("strategy", {}).get("manager_rules") or {}).get("break_even_offset_r", BREAK_EVEN_OFFSET_R))
                break_even_stop = entry_price + (risk_per_unit * break_even_offset_r)
                updates["effective_stop_loss"] = round(max(effective_stop, break_even_stop), 8)
                events.append({"type": "DYNAMIC_TP_ACTIVATED_LIVE", "payload": {"activation_price": round(activation_price, 8)}})

        return {"updates": updates, "events": events, "exit_signal": exit_signal}
