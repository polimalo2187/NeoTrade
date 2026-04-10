from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from app.config import (
    EMA_FAST,
    EMA_SLOW,
    MAX_SCORE,
    MIN_SIGNAL_SCORE,
    RSI_PERIOD,
    RSI_PULLBACK_MAX,
    RSI_PULLBACK_MIN,
    RSI_TREND_MIN,
    STOP_LOSS_PORC,
    TAKE_PROFIT_PORC,
)


@dataclass
class Signal:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    score: float
    components: list


class MTFStrategy:
    """Estrategia MTF LONG para Spot, conservadora y simple."""

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
    def _calc_levels(df_entry: pd.DataFrame, entry_price: float) -> Dict[str, float]:
        recent_low = float(df_entry["low"].tail(8).min())
        percent_stop = entry_price * (1 - STOP_LOSS_PORC)
        candidate_stop = min(percent_stop, recent_low * 0.999)
        if candidate_stop <= 0 or candidate_stop >= entry_price:
            candidate_stop = percent_stop
        risk = entry_price - candidate_stop
        tp_fixed = entry_price * (1 + TAKE_PROFIT_PORC)
        tp_rr = entry_price + (risk * 2)
        take_profit = max(tp_fixed, tp_rr)
        return {
            "stop_loss": round(candidate_stop, 8),
            "take_profit": round(take_profit, 8),
        }

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
        levels = self._calc_levels(df_entry, entry_price)

        return {
            "direction": "LONG",
            "entry_price": entry_price,
            "stop_loss": levels["stop_loss"],
            "take_profit": levels["take_profit"],
            "score": score,
            "components": components,
        }
