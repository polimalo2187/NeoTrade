import pandas as pd
from typing import Optional, Dict
import ta
from config import EMA_FAST, EMA_SLOW, RSI_PERIOD, RSI_TREND_MIN, RSI_PULLBACK_MIN, RSI_PULLBACK_MAX, MAX_SCORE

class MTFStrategy:
    """
    Estrategia Multi Time Frame (MTF) para operaciones LONG en Spot.
    Analiza diferentes marcos de tiempo (1H, 15M, 5M) y devuelve señales con score.
    """

    def __init__(self):
        pass

    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Agrega indicadores EMA y RSI al DataFrame de precios.
        """
        df = df.copy()
        df["ema_fast"] = ta.trend.ema_indicator(df["close"], EMA_FAST)
        df["ema_slow"] = ta.trend.ema_indicator(df["close"], EMA_SLOW)
        df["rsi"] = ta.momentum.rsi(df["close"], RSI_PERIOD)
        return df

    @staticmethod
    def is_trend_bullish(df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        return last["ema_fast"] > last["ema_slow"] and last["rsi"] >= RSI_TREND_MIN

    @staticmethod
    def pullback_confirmation(df: pd.DataFrame, direction: str) -> bool:
        last = df.iloc[-1]
        if direction == "LONG":
            return last["close"] >= last["ema_fast"] and RSI_PULLBACK_MIN <= last["rsi"] <= RSI_PULLBACK_MAX
        return False

    @staticmethod
    def entry_confirmation(df: pd.DataFrame, direction: str) -> bool:
        last = df.iloc[-1]
        if direction == "LONG":
            return last["ema_fast"] > last["ema_slow"] and last["rsi"] > RSI_TREND_MIN
        return False

    def analizar(self, df_1h: pd.DataFrame, df_15m: pd.DataFrame, df_5m: pd.DataFrame) -> Optional[Dict]:
        """
        Analiza los DataFrames de diferentes marcos de tiempo y devuelve:
        - direction: "LONG"
        - entry_price: precio de entrada
        - score: puntuación de la señal
        - components: detalle de score por condición
        """
        df_1h = self.add_indicators(df_1h)
        df_15m = self.add_indicators(df_15m)
        df_5m = self.add_indicators(df_5m)

        score = 0
        components = []

        # Tendencia 1H
        if self.is_trend_bullish(df_1h):
            direction = "LONG"
            score += 35
            components.append(("trend_1h", 35))
        else:
            return None

        # Pullback 15M
        if self.pullback_confirmation(df_15m, direction):
            score += 30
            components.append(("pullback_15m", 30))
        else:
            return None

        # Entrada 5M
        if not self.entry_confirmation(df_5m, direction):
            return None

        last = df_5m.iloc[-1]
        distance_pct = abs(last["close"] - last["ema_fast"]) / last["close"]
        entry_score = max(0, 30 - distance_pct * 3000)
        entry_score = min(30, entry_score)

        score += entry_score
        components.append(("entry_5m", round(entry_score, 2)))

        # Bonus momentum
        bonus = 5 if last["rsi"] > 60 else 0
        if bonus:
            score += bonus
            components.append(("momentum_bonus", bonus))

        score = max(0, min(score, MAX_SCORE))

        return {
            "direction": direction,
            "entry_price": round(float(last["close"]), 4),
            "score": round(score, 2),
            "components": components,
      }
