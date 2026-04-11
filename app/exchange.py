import hashlib
import json
import logging
import time
import urllib.parse
import uuid
from json import JSONDecodeError
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

from app.config import COINW_BASE_URL, QUOTE_ASSET


logger = logging.getLogger(__name__)


class CoinWApiError(Exception):
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.payload = payload or {}
        self.status_code = status_code


class CoinWEmptySpotBalanceError(CoinWApiError):
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, payload=payload or {})


@dataclass
class InstrumentRule:
    symbol: str
    price_precision: int
    count_precision: int
    min_buy_count: Decimal
    min_buy_amount: Decimal
    max_buy_count: Decimal
    max_buy_amount: Decimal
    min_buy_price: Decimal
    max_buy_price: Decimal
    state: int
    base_asset: str
    quote_asset: str


class ExchangeClient:
    """Cliente real para CoinW Spot."""

    PUBLIC_ENDPOINT = "/api/v1/public"
    PRIVATE_ENDPOINT = "/api/v1/private"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, timeout: int = 15):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = COINW_BASE_URL.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "NeoTrade/1.0"})

    @property
    def conectado(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def conectar(self) -> bool:
        if not self.conectado:
            return False
        self.validar_credenciales()
        return True

    @staticmethod
    def _is_success(payload: Dict[str, Any]) -> bool:
        code = payload.get("code")
        return payload.get("success") is True or str(code) in {"200", "0"}

    def _public_request(self, command: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{self.PUBLIC_ENDPOINT}",
            params={"command": command, **(params or {})},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not self._is_success(payload):
            raise CoinWApiError(payload.get("msg") or str(payload))
        return payload

    def _private_request(self, command: str, params: Optional[Dict[str, Any]] = None, method: str = "POST") -> Dict[str, Any]:
        if not self.conectado:
            raise CoinWApiError("API Key/API Secret no configuradas")

        params = dict(params or {})
        params["api_key"] = self.api_key

        sorted_params = sorted(params.items(), key=lambda item: item[0])
        encoded = "".join(f"{k}={v}&" for k, v in sorted_params)
        sign_payload = f"{encoded}secret_key={self.api_secret}"
        sign = hashlib.md5(sign_payload.encode("utf-8")).hexdigest().upper()

        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{self.PRIVATE_ENDPOINT}?command={command}&sign={sign}&{query}"

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                headers={"Content-Type": "application/json"},
                data={} if method.upper() == "POST" else None,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            body = exc.response.text if exc.response is not None else ""
            if status_code in {401, 403, 451}:
                raise CoinWApiError(
                    f"CoinW rechazó la solicitud HTTP {status_code}. Revisa permisos Spot, whitelist de IP del servidor y posibles restricciones regionales.",
                    status_code=status_code,
                ) from exc
            raise CoinWApiError(
                f"Error HTTP contra CoinW: {status_code or 'desconocido'} {body[:300]}",
                status_code=status_code,
            ) from exc
        try:
            payload = response.json()
        except JSONDecodeError as exc:
            raise CoinWApiError(f"CoinW devolvió una respuesta no JSON: {response.text[:300]}", status_code=response.status_code) from exc

        if not self._is_success(payload):
            code = str(payload.get("code", ""))
            if code == "6000":
                raise CoinWApiError(
                    "CoinW devolvió code 6000 (auth/API error). Causas típicas: API Key/API Secret incorrectas, API deshabilitada o borrada, permiso Spot API no habilitado, whitelist sin la IP pública del servidor, o IP/región restringida.",
                    payload=payload,
                    status_code=response.status_code,
                )
            raise CoinWApiError(payload.get("msg") or payload.get("message") or str(payload), payload=payload, status_code=response.status_code)
        return payload

    def validar_credenciales(self) -> Dict[str, Any]:
        return self._private_request("returnBalances", {})


    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        try:
            if value is None or value == "":
                return Decimal("0")
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    @staticmethod
    def _asset_candidates(asset: str) -> Iterable[str]:
        asset = str(asset or "").strip()
        if not asset:
            return []
        candidates = {asset, asset.upper(), asset.lower()}
        return [candidate for candidate in candidates if candidate]

    @staticmethod
    def _looks_like_asset_key(value: Any) -> bool:
        text = str(value or "").strip()
        return bool(text) and len(text) <= 15 and text.replace("_", "").replace("-", "").isalnum()

    @staticmethod
    def _balance_preview(payload: Any, limit: int = 600) -> str:
        try:
            raw = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            raw = str(payload)
        return raw[:limit]

    def _normalize_balances_payload(self, payload_data: Any) -> Dict[str, Dict[str, Decimal]]:
        normalized: Dict[str, Dict[str, Decimal]] = {}

        def merge_balance(asset_name: Any, available: Decimal, locked: Decimal, total: Decimal) -> None:
            asset = str(asset_name or "").strip().upper()
            if not asset:
                return
            current = normalized.get(asset, {"available": Decimal("0"), "locked": Decimal("0"), "total": Decimal("0")})
            new_available = available if available > current["available"] else current["available"]
            new_locked = locked if locked > current["locked"] else current["locked"]
            computed_total = total if total > 0 else new_available + new_locked
            new_total = computed_total if computed_total > current["total"] else current["total"]
            normalized[asset] = {"available": new_available, "locked": new_locked, "total": new_total}

        def _max_decimal_from_keys(item: Dict[str, Any], keys: Iterable[str]) -> Decimal:
            values = [self._to_decimal(item.get(key)) for key in keys if key in item]
            positives = [value for value in values if value > 0]
            if positives:
                return max(positives)
            return max(values) if values else Decimal("0")

        def store(asset_name: Any, item: Any) -> None:
            asset = str(asset_name or "").strip().upper()
            if not asset:
                return
            if isinstance(item, dict):
                available = _max_decimal_from_keys(
                    item,
                    ("available", "free", "normal", "balance", "usable", "canUseAmount", "remainAmount", "remain", "cash", "total"),
                )
                locked = _max_decimal_from_keys(
                    item,
                    ("onOrders", "frozen", "locked", "hold", "freeze", "lock", "occupied", "withdrawing"),
                )
                total = _max_decimal_from_keys(
                    item,
                    ("total", "amount", "balance", "normal", "available", "usable", "free", "canUseAmount"),
                )
                if total <= 0:
                    total = available + locked
            else:
                available = self._to_decimal(item)
                locked = Decimal("0")
                total = available
            merge_balance(asset, available, locked, total)

        def walk(node: Any) -> None:
            if node is None:
                return
            if isinstance(node, str):
                try:
                    parsed = json.loads(node)
                except Exception:
                    return
                walk(parsed)
                return
            if isinstance(node, list):
                for row in node:
                    walk(row)
                return
            if not isinstance(node, dict):
                return

            # Common nested containers
            for nested_key in ("data", "balances", "assets", "items", "rows", "list", "result", "wallet", "account", "accounts", "details"):
                nested_value = node.get(nested_key)
                if nested_value is not None and nested_value is not node:
                    walk(nested_value)

            asset_name = (
                node.get("asset")
                or node.get("currency")
                or node.get("coin")
                or node.get("symbol")
                or node.get("currencyName")
                or node.get("coinName")
                or node.get("name")
            )
            if asset_name:
                store(asset_name, node)

            # Direct map of asset -> balance dict/value
            direct_asset_entries = []
            for key, value in node.items():
                if self._looks_like_asset_key(key) and (isinstance(value, (dict, str, int, float))):
                    direct_asset_entries.append((key, value))
            if direct_asset_entries:
                for key, value in direct_asset_entries:
                    store(key, value)

            # Fallback deep walk through arbitrary nested dict values
            for value in node.values():
                if isinstance(value, (dict, list, str)):
                    walk(value)

        walk(payload_data)
        return normalized

    @staticmethod
    def _balances_have_positive_amount(balances: Dict[str, Dict[str, Decimal]]) -> bool:
        for item in balances.values():
            total = item.get("total", Decimal("0"))
            if total <= 0:
                total = item.get("available", Decimal("0")) + item.get("locked", Decimal("0"))
            if total > 0:
                return True
        return False

    def _find_balance_entry(self, balances: Dict[str, Dict[str, Decimal]], asset: str) -> Dict[str, Decimal]:
        for candidate in self._asset_candidates(asset):
            item = balances.get(candidate.upper()) or balances.get(candidate)
            if item is not None:
                return item
        return {"available": Decimal("0"), "locked": Decimal("0"), "total": Decimal("0")}

    def obtener_balance(self, asset: str = QUOTE_ASSET) -> float:
        payload = self._private_request("returnBalances", {})
        balances = self._normalize_balances_payload(payload.get("data", {}))
        item = self._find_balance_entry(balances, asset)
        return float(item.get("available", Decimal("0")) or 0)

    def obtener_balances_completos(self) -> Dict[str, Dict[str, Decimal]]:
        balances_complete: Dict[str, Dict[str, Decimal]] = {}
        balances_available: Dict[str, Dict[str, Decimal]] = {}
        payload_complete: Any = None
        payload_available: Any = None

        try:
            payload_complete = self._private_request("returnCompleteBalances", {})
            balances_complete = self._normalize_balances_payload(payload_complete.get("data", payload_complete))
        except CoinWApiError:
            raise
        except Exception:
            logger.exception("No se pudieron normalizar balances completos de CoinW")

        try:
            payload_available = self._private_request("returnBalances", {})
            balances_available = self._normalize_balances_payload(payload_available.get("data", payload_available))
        except CoinWApiError:
            raise
        except Exception:
            logger.exception("No se pudieron normalizar balances disponibles de CoinW")

        merged: Dict[str, Dict[str, Decimal]] = {}
        for source in (balances_complete, balances_available):
            for asset, item in source.items():
                current = merged.get(asset, {"available": Decimal("0"), "locked": Decimal("0"), "total": Decimal("0")})
                available = item.get("available", Decimal("0"))
                locked = item.get("locked", Decimal("0"))
                total = item.get("total", Decimal("0"))
                merged[asset] = {
                    "available": available if available > current["available"] else current["available"],
                    "locked": locked if locked > current["locked"] else current["locked"],
                    "total": total if total > current["total"] else current["total"],
                }

        for asset, item in merged.items():
            if item["total"] <= 0:
                item["total"] = item["available"] + item["locked"]

        if not self._balances_have_positive_amount(merged):
            diagnostic_payload = {
                "complete": payload_complete,
                "available": payload_available,
            }
            logger.warning(
                "COINW_BALANCES_ZERO | complete=%s | available=%s",
                self._balance_preview(payload_complete),
                self._balance_preview(payload_available),
            )
            raise CoinWEmptySpotBalanceError(
                "CoinW devolvió los balances Spot vacíos para esta API.",
                payload=diagnostic_payload,
            )

        logger.info(
            "COINW_BALANCES_NORMALIZED | balances=%s",
            {asset: {k: str(v) for k, v in item.items()} for asset, item in list(merged.items())[:10]},
        )

        return merged

    def obtener_balance_disponible(self, asset: str = QUOTE_ASSET) -> Decimal:
        balances = self.obtener_balances_completos()
        item = self._find_balance_entry(balances, asset)
        return item.get("available", Decimal("0"))

    def obtener_balance_total(self, asset: str = QUOTE_ASSET) -> Decimal:
        balances = self.obtener_balances_completos()
        item = self._find_balance_entry(balances, asset)
        total = item.get("total", Decimal("0"))
        if total <= 0:
            total = item.get("available", Decimal("0")) + item.get("locked", Decimal("0"))
        return total

    def estimar_capital_total_en_quote(self, quote_asset: str = QUOTE_ASSET) -> Dict[str, Decimal]:
        balances = self.obtener_balances_completos()
        quote_total = self.obtener_balance_total(quote_asset)
        quote_available = self.obtener_balance_disponible(quote_asset)
        total_estimated = quote_total

        try:
            ticker = self.obtener_ticker_24h()
        except Exception:
            ticker = {}

        for asset, item in balances.items():
            if asset.upper() == quote_asset.upper():
                continue
            asset_total = item.get("total", Decimal("0"))
            if asset_total <= 0:
                asset_total = item.get("available", Decimal("0")) + item.get("locked", Decimal("0"))
            if asset_total <= 0:
                continue
            symbol = f"{asset.upper()}_{quote_asset.upper()}"
            ticker_item = ticker.get(symbol) if isinstance(ticker, dict) else None
            if not ticker_item:
                continue
            last_price = self._to_decimal(ticker_item.get("last", 0))
            if last_price <= 0:
                continue
            total_estimated += asset_total * last_price

        return {
            "quote_available": quote_available,
            "quote_total": quote_total,
            "capital_total_estimated": total_estimated,
        }

    def obtener_ticker_24h(self) -> Dict[str, Dict[str, Any]]:
        return self._public_request("returnTicker", {}).get("data", {})

    def obtener_precio_actual(self, symbol: str = "BTC_USDT") -> float:
        data = self.obtener_ticker_24h()
        item = data.get(symbol.upper())
        if not item:
            raise CoinWApiError(f"No se encontró ticker para {symbol}")
        return float(item["last"])

    def obtener_info_instrumentos(self) -> Dict[str, InstrumentRule]:
        payload = self._public_request("returnSymbol", {})
        instrumentos = {}
        for row in payload.get("data", []):
            symbol = str(row["currencyPair"]).upper()
            instrumentos[symbol] = InstrumentRule(
                symbol=symbol,
                price_precision=int(row.get("pricePrecision", 8)),
                count_precision=int(row.get("countPrecision", 8)),
                min_buy_count=Decimal(str(row.get("minBuyCount", 0) or 0)),
                min_buy_amount=Decimal(str(row.get("minBuyAmount", 0) or 0)),
                max_buy_count=Decimal(str(row.get("maxBuyCount", 0) or 0)),
                max_buy_amount=Decimal(str(row.get("maxBuyAmount", 0) or 0)),
                min_buy_price=Decimal(str(row.get("minBuyPrice", 0) or 0)),
                max_buy_price=Decimal(str(row.get("maxBuyPrice", 0) or 0)),
                state=int(row.get("state", 0)),
                base_asset=str(row.get("currencyBase", "")).upper(),
                quote_asset=str(row.get("currencyQuote", "")).upper(),
            )
        return instrumentos

    def obtener_pares_disponibles(
        self,
        volumen_minimo: float,
        quote_asset: str = QUOTE_ASSET,
        max_pairs: Optional[int] = None,
    ) -> List[str]:
        ticker = self.obtener_ticker_24h()
        symbol_info = self.obtener_info_instrumentos()
        candidates: List[tuple] = []
        suffix = f"_{quote_asset.upper()}"

        for symbol, item in ticker.items():
            if not symbol.endswith(suffix):
                continue
            if int(item.get("isFrozen", 1)) != 0:
                continue
            info = symbol_info.get(symbol)
            if not info or info.state != 1:
                continue
            volume = float(item.get("baseVolume", 0) or 0)
            if volume < volumen_minimo:
                continue
            candidates.append((symbol, volume))

        candidates.sort(key=lambda item: item[1], reverse=True)
        symbols = [symbol for symbol, _ in candidates]
        return symbols[:max_pairs] if max_pairs else symbols

    def _parse_klines_payload(self, payload: Dict[str, Any], symbol: str) -> pd.DataFrame:
        rows = [row for row in payload.get("data", []) if str(row.get("pair", "")).upper() == symbol.upper()]
        if not rows:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
        df = df.dropna(subset=["open", "high", "low", "close", "volume"]).sort_values("date")
        return df.reset_index(drop=True)

    def _drop_incomplete_last_candle(self, df: pd.DataFrame, period_seconds: int, reference_end_ms: int) -> pd.DataFrame:
        if df.empty:
            return df
        last_open_ms = int(pd.Timestamp(df.iloc[-1]["date"]).timestamp() * 1000)
        if last_open_ms + (period_seconds * 1000) > int(reference_end_ms):
            return df.iloc[:-1].reset_index(drop=True)
        return df

    def obtener_klines(self, symbol: str, period_seconds: int, limit: int = 120) -> pd.DataFrame:
        now_ms = int(time.time() * 1000)
        fetch_limit = max(limit + 2, limit)
        start_ms = now_ms - (period_seconds * fetch_limit * 1000)
        payload = self._public_request(
            "returnChartData",
            {
                "currencyPair": symbol.upper(),
                "period": period_seconds,
                "start": start_ms,
                "end": now_ms,
            },
        )
        df = self._parse_klines_payload(payload, symbol)
        df = self._drop_incomplete_last_candle(df, period_seconds, now_ms)
        if df.empty:
            raise CoinWApiError(f"No se recibieron velas cerradas para {symbol} en {period_seconds}s")
        return df.tail(limit).reset_index(drop=True)

    def obtener_klines_rango(self, symbol: str, period_seconds: int, start_ms: int, end_ms: int) -> pd.DataFrame:
        if end_ms <= start_ms:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        payload = self._public_request(
            "returnChartData",
            {
                "currencyPair": symbol.upper(),
                "period": period_seconds,
                "start": int(start_ms),
                "end": int(end_ms),
            },
        )
        df = self._parse_klines_payload(payload, symbol)
        return self._drop_incomplete_last_candle(df, period_seconds, int(end_ms) + (period_seconds * 1000))

    def obtener_ordenes_abiertas(self, symbol: str) -> List[Dict[str, Any]]:
        payload = self._private_request("returnOpenOrders", {"currencyPair": symbol.upper()})
        data = payload.get("data", [])
        return data if isinstance(data, list) else []

    def obtener_estado_orden(self, order_number: str) -> Dict[str, Any]:
        return self._private_request("returnOrderStatus", {"orderNumber": str(order_number)}).get("data", {})

    def cancelar_orden(self, order_number: str) -> Dict[str, Any]:
        return self._private_request("cancelOrder", {"orderNumber": str(order_number)}).get("data", {})

    def cancelar_todas_las_ordenes(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if symbol:
            params["currencyPair"] = symbol.upper()
        return self._private_request("cancelAllOrder", params).get("data", {})

    def _gen_client_order_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:20]}"

    @staticmethod
    def _quantize(value: Decimal, precision: int) -> Decimal:
        if precision < 0:
            return value
        quantum = Decimal("1") if precision == 0 else Decimal(f"1e-{precision}")
        return value.quantize(quantum, rounding=ROUND_DOWN)

    def ajustar_amount(self, amount: Decimal, rule: InstrumentRule) -> Decimal:
        amount = self._quantize(amount, rule.count_precision)
        if amount < rule.min_buy_count:
            raise CoinWApiError(
                f"Cantidad {amount} menor al mínimo permitido {rule.min_buy_count} para {rule.symbol}"
            )
        if rule.max_buy_count > 0 and amount > rule.max_buy_count:
            amount = self._quantize(rule.max_buy_count, rule.count_precision)
        return amount

    def ajustar_price(self, price: Decimal, rule: InstrumentRule) -> Decimal:
        price = self._quantize(price, rule.price_precision)
        if price < rule.min_buy_price:
            price = rule.min_buy_price
        if rule.max_buy_price > 0 and price > rule.max_buy_price:
            price = rule.max_buy_price
        return price

    def ajustar_funds(self, funds: Decimal, rule: InstrumentRule) -> Decimal:
        funds = funds.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if funds < rule.min_buy_amount:
            raise CoinWApiError(
                f"Monto {funds} menor al mínimo permitido {rule.min_buy_amount} {rule.quote_asset} para {rule.symbol}"
            )
        if rule.max_buy_amount > 0 and funds > rule.max_buy_amount:
            funds = rule.max_buy_amount.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return funds

    def crear_orden_mercado_buy(self, symbol: str, funds: Decimal, rule: InstrumentRule) -> Dict[str, Any]:
        funds = self.ajustar_funds(funds, rule)
        return self._private_request(
            "doTrade",
            {
                "symbol": symbol.upper(),
                "type": "0",
                "funds": str(funds),
                "isMarket": "true",
                "out_trade_no": self._gen_client_order_id("buy"),
            },
        ).get("data", {})

    def crear_orden_mercado_sell(self, symbol: str, amount: Decimal, rule: InstrumentRule) -> Dict[str, Any]:
        amount = self.ajustar_amount(amount, rule)
        return self._private_request(
            "doTrade",
            {
                "symbol": symbol.upper(),
                "type": "1",
                "amount": str(amount),
                "isMarket": "true",
                "out_trade_no": self._gen_client_order_id("sell"),
            },
        ).get("data", {})

    def crear_orden_limite(self, side: str, symbol: str, amount: Decimal, price: Decimal, rule: InstrumentRule) -> Dict[str, Any]:
        amount = self.ajustar_amount(amount, rule)
        price = self.ajustar_price(price, rule)
        side_value = "0" if side.upper() == "BUY" else "1"
        return self._private_request(
            "doTrade",
            {
                "symbol": symbol.upper(),
                "type": side_value,
                "amount": str(amount),
                "rate": str(price),
                "isMarket": "false",
                "out_trade_no": self._gen_client_order_id(side.lower()),
            },
        ).get("data", {})

    def estimar_fill_desde_estado(self, order_status: Dict[str, Any], fallback_price: Optional[Decimal] = None) -> Dict[str, Decimal]:
        total = Decimal(str(order_status.get("total", 0) or 0))
        starting_amount = Decimal(str(order_status.get("startingAmount", 0) or 0))
        if total > 0 and starting_amount > 0:
            avg_price = (starting_amount / total).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            return {"amount": total, "avg_price": avg_price, "quote_amount": starting_amount}
        return {
            "amount": total,
            "avg_price": fallback_price or Decimal("0"),
            "quote_amount": starting_amount,
        }
