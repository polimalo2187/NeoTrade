from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.config import (
    ATR_PERIOD,
    CANDLE_LIMIT,
    ENABLE_MARKET_REGIME_FILTER,
    MAX_ATR_PCT,
    MIN_ATR_PCT,
    QUOTE_ASSET,
    REGIME_BREADTH_CONTINUATION_MIN,
    REGIME_BREADTH_RISK_OFF_MAX,
    REGIME_BREADTH_SAMPLE_SIZE,
    REGIME_BREADTH_WARNING_MIN,
    REGIME_BTC_ATR_SPIKE_MULTIPLIER,
    REGIME_BTC_BELOW_SLOW_HARD_PCT,
    REGIME_BTC_BELOW_SLOW_SOFT_PCT,
    REGIME_BTC_CONTEXT_SCORE_CONTINUATION_MIN,
    REGIME_BTC_CONTEXT_SCORE_RECOVERY_MIN,
    REGIME_BTC_LAST_CANDLE_DROP_PCT,
    REGIME_BTC_LAST_CANDLE_RISK_OFF_PCT,
    REGIME_BTC_SYMBOL,
    REGIME_COOLDOWN_CYCLES_AFTER_EXIT,
    REGIME_CONFIRM_CONTINUATION_CYCLES,
    REGIME_CONFIRM_EXIT_CYCLES,
    REGIME_STALE_DECISION_MAX_SECONDS,
    RSI_TREND_MIN,
    TREND_EMA_FAST_SLOPE_MIN,
    TREND_EMA_SLOW_SLOPE_MIN,
    TREND_PERIOD_SECONDS,
)
from app.mtf_strategy import MTFStrategy


logger = logging.getLogger(__name__)

STATE_CONTINUATION_OK = "CONTINUATION_OK"
STATE_RECOVERY_WAIT = "RECOVERY_WAIT"
STATE_RISK_OFF_NO_TRADE = "RISK_OFF_NO_TRADE"


@dataclass
class MarketRegimeDecision:
    state: str
    raw_state: str
    allow_new_entries: bool
    changed: bool
    reasons: List[str]
    detail: Dict[str, Any]


class MarketRegimeDetector:
    """Detector global de régimen para bots spot LONG-only.

    Filosofía:
    - no sustituye a la estrategia local por símbolo
    - decide únicamente si se permiten nuevas entradas
    - mantiene histeresis para evitar flip-flop entre estados
    - nunca afecta la gestión de posiciones abiertas
    """

    def __init__(self, kline_fetcher: Callable[[str, int, int], pd.DataFrame]):
        self._kline_fetcher = kline_fetcher
        self._stable_state = STATE_CONTINUATION_OK if not ENABLE_MARKET_REGIME_FILTER else STATE_RECOVERY_WAIT
        self._pending_state: Optional[str] = None
        self._pending_count = 0
        self._continuation_cooldown_remaining = 0
        self._last_decision: Optional[MarketRegimeDecision] = None
        self._last_successful_decision: Optional[MarketRegimeDecision] = None
        self._last_successful_ts: Optional[float] = None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _slope_pct(series: pd.Series, lookback: int = 3) -> float:
        if len(series) <= lookback:
            return 0.0
        base = float(series.iloc[-1 - lookback])
        if abs(base) < 1e-12:
            return 0.0
        return (float(series.iloc[-1]) - base) / base

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> str:
        normalized = str(symbol or "").upper().strip().replace("-", "_").replace("/", "_")
        return normalized

    def _resolve_btc_symbol(self, candidate_symbols: List[str]) -> str:
        normalized_candidates = {self._normalize_symbol(symbol) for symbol in candidate_symbols if symbol}
        configured = self._normalize_symbol(REGIME_BTC_SYMBOL)

        preferred: List[str] = []
        if configured:
            preferred.append(configured)
            if "_" not in configured and configured.endswith(QUOTE_ASSET):
                base = configured[: -len(QUOTE_ASSET)]
                if base:
                    preferred.append(f"{base}_{QUOTE_ASSET}")
        preferred.extend([
            f"BTC_{QUOTE_ASSET}",
            "BTC_USDT",
        ])

        seen = set()
        deduped_preferred: List[str] = []
        for symbol in preferred:
            normalized = self._normalize_symbol(symbol)
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped_preferred.append(normalized)

        for symbol in deduped_preferred:
            if symbol in normalized_candidates:
                return symbol
        return deduped_preferred[0] if deduped_preferred else f"BTC_{QUOTE_ASSET}"

    def _load_indicators(self, symbol: str, period_seconds: int) -> pd.DataFrame:
        raw = self._kline_fetcher(symbol, period_seconds, CANDLE_LIMIT)
        return MTFStrategy.add_indicators(raw)

    def _evaluate_context(self, df: pd.DataFrame) -> Dict[str, Any]:
        min_rows = max(52, ATR_PERIOD + 5)
        if df.empty or len(df) < min_rows:
            raise ValueError("INSUFFICIENT_INDICATOR_ROWS")

        last = df.iloc[-1]
        prev = df.iloc[-2]
        last_close = self._safe_float(last["close"])
        prev_close = self._safe_float(prev["close"])
        last_open = self._safe_float(last["open"])
        ema_fast = self._safe_float(last["ema_fast"])
        ema_slow = self._safe_float(last["ema_slow"])
        rsi = self._safe_float(last["rsi"])
        atr_pct = self._safe_float(last["atr_pct"])
        fast_slope = self._slope_pct(df["ema_fast"], 3)
        slow_slope = self._slope_pct(df["ema_slow"], 3)
        atr_mean = self._safe_float(df["atr_pct"].tail(12).mean(), atr_pct)
        last_candle_pct = 0.0
        if prev_close > 0:
            last_candle_pct = (last_close - prev_close) / prev_close
        intrabar_pct = 0.0
        if last_open > 0:
            intrabar_pct = (last_close - last_open) / last_open

        bullish_stack = ema_fast > ema_slow and last_close >= ema_fast * 0.998
        slope_ok = fast_slope >= max(TREND_EMA_FAST_SLOPE_MIN * 0.5, 0.0) and slow_slope >= max(TREND_EMA_SLOW_SLOPE_MIN * 0.5, 0.0)
        rsi_ok = rsi >= max(RSI_TREND_MIN - 2, 45)
        vol_ok = MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT
        higher_close = last_close >= self._safe_float(df.iloc[-4]["close"], last_close) * 0.997 if len(df) >= 4 else True
        context_ok = bullish_stack and slope_ok and rsi_ok and vol_ok and higher_close

        atr_spike = atr_mean > 0 and atr_pct >= atr_mean * REGIME_BTC_ATR_SPIKE_MULTIPLIER
        last_candle_shock = last_candle_pct <= -abs(REGIME_BTC_LAST_CANDLE_DROP_PCT)
        risk_off_candle = last_candle_pct <= -abs(REGIME_BTC_LAST_CANDLE_RISK_OFF_PCT) or intrabar_pct <= -abs(REGIME_BTC_LAST_CANDLE_RISK_OFF_PCT)
        below_slow_pct = 0.0
        if ema_slow > 0 and last_close < ema_slow:
            below_slow_pct = (ema_slow - last_close) / ema_slow
        below_slow_soft = below_slow_pct >= REGIME_BTC_BELOW_SLOW_SOFT_PCT
        below_slow_hard = below_slow_pct >= REGIME_BTC_BELOW_SLOW_HARD_PCT
        slow_slope_negative = slow_slope < 0

        context_score = int(sum(1 for passed in (bullish_stack, slope_ok, rsi_ok, vol_ok, higher_close) if passed))
        context_score_ok = context_score >= REGIME_BTC_CONTEXT_SCORE_CONTINUATION_MIN
        recovery_context_ok = context_score >= REGIME_BTC_CONTEXT_SCORE_RECOVERY_MIN
        context_gate_failures = [
            name
            for name, passed in (
                ("bullish_stack", bullish_stack),
                ("slope_ok", slope_ok),
                ("rsi_ok", rsi_ok),
                ("vol_ok", vol_ok),
                ("higher_close", higher_close),
            )
            if not passed
        ]

        return {
            "context_ok": context_ok,
            "context_score_ok": context_score_ok,
            "recovery_context_ok": recovery_context_ok,
            "context_score": context_score,
            "context_gate_failures": context_gate_failures,
            "bullish_stack": bullish_stack,
            "slope_ok": slope_ok,
            "rsi_ok": rsi_ok,
            "vol_ok": vol_ok,
            "higher_close": higher_close,
            "fast_slope": round(fast_slope, 6),
            "slow_slope": round(slow_slope, 6),
            "rsi": round(rsi, 2),
            "atr_pct": round(atr_pct, 6),
            "atr_pct_mean": round(atr_mean, 6),
            "last_candle_pct": round(last_candle_pct, 6),
            "intrabar_pct": round(intrabar_pct, 6),
            "close": round(last_close, 8),
            "ema_fast": round(ema_fast, 8),
            "ema_slow": round(ema_slow, 8),
            "atr_spike": atr_spike,
            "last_candle_shock": last_candle_shock,
            "risk_off_candle": risk_off_candle,
            "below_slow_soft": below_slow_soft,
            "below_slow_hard": below_slow_hard,
            "below_slow_pct": round(below_slow_pct, 6),
            "slow_slope_negative": slow_slope_negative,
        }

    def _evaluate_breadth_symbol(self, symbol: str) -> Dict[str, Any]:
        df = self._load_indicators(symbol, TREND_PERIOD_SECONDS)
        info = self._evaluate_context(df)

        # El breadth no debe exigir el mismo nivel de dureza que una señal lista
        # para ejecutar. Aquí medimos acompañamiento del mercado, no readiness de entrada.
        fast_slope = self._safe_float(info["fast_slope"])
        slow_slope = self._safe_float(info["slow_slope"])
        rsi = self._safe_float(info["rsi"])
        close_price = self._safe_float(info["close"])
        ema_fast = self._safe_float(info["ema_fast"])
        ema_slow = self._safe_float(info["ema_slow"])
        atr_pct = self._safe_float(info["atr_pct"])
        last_candle_pct = self._safe_float(info["last_candle_pct"])

        breadth_bullish_stack = ema_fast > ema_slow and close_price >= ema_slow * 0.998
        breadth_momentum_ok = fast_slope >= -0.0003 and slow_slope >= -0.0002
        breadth_rsi_ok = rsi >= 46
        breadth_vol_ok = atr_pct >= max(MIN_ATR_PCT * 0.5, 0.0) and atr_pct <= MAX_ATR_PCT * 1.25
        breadth_damage = close_price < ema_slow * 0.992 or last_candle_pct <= -0.025
        passed = bool(breadth_bullish_stack and breadth_momentum_ok and breadth_rsi_ok and breadth_vol_ok and not breadth_damage)

        return {
            "symbol": symbol,
            "passed": passed,
            "detail": {
                "rsi": info["rsi"],
                "atr_pct": info["atr_pct"],
                "fast_slope": info["fast_slope"],
                "slow_slope": info["slow_slope"],
                "bullish_stack": breadth_bullish_stack,
                "momentum_ok": breadth_momentum_ok,
                "damage": breadth_damage,
            },
        }

    def _compute_breadth(self, candidate_symbols: List[str], btc_symbol: str) -> Dict[str, Any]:
        sample_symbols: List[str] = []
        seen = set()
        normalized_btc = self._normalize_symbol(btc_symbol)
        for symbol in candidate_symbols:
            normalized = self._normalize_symbol(symbol)
            if not normalized or normalized == normalized_btc or normalized in seen:
                continue
            seen.add(normalized)
            sample_symbols.append(normalized)
            if len(sample_symbols) >= REGIME_BREADTH_SAMPLE_SIZE:
                break

        passed = 0
        evaluated = 0
        accepted_symbols: List[str] = []
        rejected_symbols: List[str] = []
        errors: List[str] = []

        for symbol in sample_symbols:
            try:
                result = self._evaluate_breadth_symbol(symbol)
                evaluated += 1
                if result["passed"]:
                    passed += 1
                    if len(accepted_symbols) < 6:
                        accepted_symbols.append(symbol)
                else:
                    if len(rejected_symbols) < 6:
                        rejected_symbols.append(symbol)
            except Exception as exc:
                errors.append(f"{symbol}:{exc}")

        ratio = float(passed / evaluated) if evaluated > 0 else 0.0
        return {
            "sample_symbols": sample_symbols,
            "evaluated": evaluated,
            "passed": passed,
            "ratio": round(ratio, 4),
            "accepted_symbols": accepted_symbols,
            "rejected_symbols": rejected_symbols,
            "errors": errors[:6],
        }

    def _raw_state_from_metrics(self, btc: Dict[str, Any], breadth: Dict[str, Any]) -> Tuple[str, List[str], bool]:
        reasons: List[str] = []
        immediate_risk_off = False
        breadth_ratio = float(breadth.get("ratio") or 0.0)
        breadth_evaluated = int(breadth.get("evaluated") or 0)

        if breadth_evaluated == 0:
            reasons.append("breadth_insufficient_data")
            return STATE_RECOVERY_WAIT, reasons, False

        if btc.get("risk_off_candle"):
            reasons.append("btc_risk_off_candle")
            immediate_risk_off = True
        if btc.get("atr_spike"):
            reasons.append("btc_atr_spike")
        if btc.get("below_slow_soft"):
            reasons.append("btc_below_ema_slow")
        if btc.get("below_slow_hard"):
            reasons.append("btc_deep_below_ema_slow")
        if breadth_ratio <= REGIME_BREADTH_RISK_OFF_MAX:
            reasons.append("breadth_collapsed")

        btc_structure_damaged = bool(
            btc.get("below_slow_hard") and (btc.get("slow_slope_negative") or not btc.get("bullish_stack"))
        )
        btc_structure_weak = bool(
            btc.get("below_slow_soft") or btc.get("atr_spike") or not btc.get("bullish_stack")
        )

        # Breadth por sí solo no debe mandar el sistema a RISK_OFF de inmediato.
        # Solo bloqueamos duro cuando BTC muestra daño estructural real o shock claro.
        if immediate_risk_off or (
            breadth_ratio <= REGIME_BREADTH_RISK_OFF_MAX and (btc_structure_damaged or btc.get("atr_spike"))
        ) or (btc_structure_damaged and breadth_ratio < REGIME_BREADTH_WARNING_MIN):
            return STATE_RISK_OFF_NO_TRADE, reasons, immediate_risk_off

        btc_continuation_ready = bool(
            breadth_ratio >= REGIME_BREADTH_CONTINUATION_MIN
            and btc.get("context_score_ok")
            and btc.get("recovery_context_ok")
            and btc.get("vol_ok")
            and btc.get("rsi_ok")
            and not btc.get("below_slow_soft")
            and not btc.get("below_slow_hard")
            and not btc.get("risk_off_candle")
            and not btc.get("atr_spike")
            and not btc_structure_damaged
        )
        if btc_continuation_ready:
            reasons.append("btc_trend_ok")
            reasons.append("breadth_continuation_ok")
            if not btc.get("context_ok"):
                reasons.append("btc_trend_score_override")
            return STATE_CONTINUATION_OK, reasons, False

        if breadth_ratio < REGIME_BREADTH_WARNING_MIN:
            reasons.append("breadth_weak")
        if btc_structure_weak and not btc_structure_damaged:
            reasons.append("btc_structure_soft_weakness")
        if not btc.get("recovery_context_ok"):
            reasons.append("btc_recovery_context_not_confirmed")
        if not btc.get("context_score_ok"):
            reasons.append("btc_context_score_below_continuation")
        if not btc.get("context_ok"):
            failures = list(btc.get("context_gate_failures") or [])[:3]
            if failures:
                reasons.append("btc_trend_not_confirmed:" + "+".join(failures))
            else:
                reasons.append("btc_trend_not_confirmed")
        return STATE_RECOVERY_WAIT, reasons, False

    def _apply_hysteresis(self, raw_state: str, immediate_risk_off: bool) -> Tuple[str, bool, Dict[str, Any]]:
        previous_state = self._stable_state
        changed = False
        transition_detail: Dict[str, Any] = {
            "previous_state": previous_state,
            "pending_state": self._pending_state,
            "pending_count": self._pending_count,
            "cooldown_remaining": self._continuation_cooldown_remaining,
        }

        effective_raw_state = raw_state
        if raw_state == STATE_CONTINUATION_OK and self._continuation_cooldown_remaining > 0:
            effective_raw_state = STATE_RECOVERY_WAIT
            transition_detail["continuation_forced_wait"] = True

        if immediate_risk_off and effective_raw_state == STATE_RISK_OFF_NO_TRADE and previous_state != STATE_RISK_OFF_NO_TRADE:
            self._stable_state = STATE_RISK_OFF_NO_TRADE
            self._pending_state = None
            self._pending_count = 0
            changed = True
        elif effective_raw_state == previous_state:
            self._pending_state = None
            self._pending_count = 0
        else:
            if self._pending_state == effective_raw_state:
                self._pending_count += 1
            else:
                self._pending_state = effective_raw_state
                self._pending_count = 1

            required = REGIME_CONFIRM_CONTINUATION_CYCLES if effective_raw_state == STATE_CONTINUATION_OK else REGIME_CONFIRM_EXIT_CYCLES
            if self._pending_count >= required:
                self._stable_state = effective_raw_state
                self._pending_state = None
                self._pending_count = 0
                changed = True

        if self._stable_state != STATE_CONTINUATION_OK and previous_state == STATE_CONTINUATION_OK:
            self._continuation_cooldown_remaining = max(REGIME_COOLDOWN_CYCLES_AFTER_EXIT, 0)
        elif self._stable_state == STATE_CONTINUATION_OK:
            self._continuation_cooldown_remaining = 0
        elif self._continuation_cooldown_remaining > 0:
            self._continuation_cooldown_remaining -= 1

        transition_detail.update(
            {
                "effective_raw_state": effective_raw_state,
                "new_state": self._stable_state,
                "changed": changed,
                "pending_state_after": self._pending_state,
                "pending_count_after": self._pending_count,
                "cooldown_remaining_after": self._continuation_cooldown_remaining,
            }
        )
        return effective_raw_state, changed, transition_detail

    def _build_fallback_decision(self, error: Exception) -> MarketRegimeDecision:
        now = time.time()
        error_text = str(error)
        if self._last_successful_decision and self._last_successful_ts is not None:
            age_seconds = max(0, int(now - self._last_successful_ts))
            if age_seconds <= REGIME_STALE_DECISION_MAX_SECONDS:
                base = self._last_successful_decision
                detail = dict(base.detail or {})
                detail.update(
                    {
                        "fallback_active": True,
                        "fallback_reason": "detector_error_using_last_successful_decision",
                        "fallback_error": error_text,
                        "fallback_age_seconds": age_seconds,
                    }
                )
                reasons = list(base.reasons or [])
                if "regime_stale_fallback" not in reasons:
                    reasons.append("regime_stale_fallback")
                return MarketRegimeDecision(
                    state=base.state,
                    raw_state=base.raw_state,
                    allow_new_entries=base.allow_new_entries,
                    changed=False,
                    reasons=reasons,
                    detail=detail,
                )

        return MarketRegimeDecision(
            state=STATE_RECOVERY_WAIT,
            raw_state=STATE_RECOVERY_WAIT,
            allow_new_entries=False,
            changed=False,
            reasons=["regime_detector_error"],
            detail={
                "filter_enabled": True,
                "fallback_active": False,
                "error": error_text,
            },
        )

    def detect(self, candidate_symbols: List[str]) -> MarketRegimeDecision:
        if not ENABLE_MARKET_REGIME_FILTER:
            decision = MarketRegimeDecision(
                state=STATE_CONTINUATION_OK,
                raw_state=STATE_CONTINUATION_OK,
                allow_new_entries=True,
                changed=self._last_decision is None or self._last_decision.state != STATE_CONTINUATION_OK,
                reasons=["market_regime_filter_disabled"],
                detail={"filter_enabled": False},
            )
            self._last_decision = decision
            self._last_successful_decision = decision
            self._last_successful_ts = time.time()
            return decision

        try:
            btc_symbol = self._resolve_btc_symbol(candidate_symbols)
            btc_df = self._load_indicators(btc_symbol, TREND_PERIOD_SECONDS)
            btc = self._evaluate_context(btc_df)
            breadth = self._compute_breadth(candidate_symbols, btc_symbol)
            raw_state, reasons, immediate_risk_off = self._raw_state_from_metrics(btc, breadth)
            effective_raw_state, changed, transition = self._apply_hysteresis(raw_state, immediate_risk_off)

            decision = MarketRegimeDecision(
                state=self._stable_state,
                raw_state=effective_raw_state,
                allow_new_entries=self._stable_state == STATE_CONTINUATION_OK,
                changed=changed,
                reasons=reasons,
                detail={
                    "filter_enabled": True,
                    "btc_symbol": btc_symbol,
                    "btc": btc,
                    "breadth": breadth,
                    "transition": transition,
                },
            )
            self._last_decision = decision
            self._last_successful_decision = decision
            self._last_successful_ts = time.time()
            return decision
        except Exception as exc:
            logger.warning("MARKET_REGIME_FALLBACK | error=%s", exc)
            decision = self._build_fallback_decision(exc)
            self._last_decision = decision
            return decision
