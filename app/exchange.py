import requests

class ExchangeClient:
    """
    Cliente para interactuar con el exchange CoinW (Spot).
    Permite consultar balances, precios y ejecutar órdenes.
    Preparado para interés compuesto y múltiples pares filtrados por volumen real.
    """

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.conectado = False
        self.base_url = "https://api.coinw.com/api/v1"  # Placeholder URL

    def conectar(self):
        """
        Valida y conecta con la API del exchange.
        """
        if self.api_key and self.api_secret:
            self.conectado = True
        else:
            self.conectado = False
        return self.conectado

    def obtener_balance(self, symbol="USDT"):
        """
        Devuelve el balance disponible del usuario en el exchange.
        """
        return 1000.0  # Simulación temporal

    def obtener_precio_actual(self, symbol="BTCUSDT"):
        """
        Devuelve el precio actual del símbolo especificado.
        """
        return 50000.0  # Simulación temporal

    def crear_orden(self, tipo, cantidad, precio, symbol="BTCUSDT"):
        """
        Crea una orden de compra o venta en Spot.
        """
        if not self.conectado:
            raise Exception("No conectado al exchange")
        return {
            "orden_id": "ORD123456",
            "tipo": tipo,
            "cantidad": cantidad,
            "precio": precio,
            "symbol": symbol,
            "status": "OPEN"
        }

    def cerrar_orden(self, orden_id):
        """
        Cierra la orden abierta en el exchange.
        """
        if not self.conectado:
            raise Exception("No conectado al exchange")
        return {
            "orden_id": orden_id,
            "status": "CLOSED"
        }

    # ======================================
    # NUEVO: Obtener pares disponibles
    # ======================================
    def obtener_pares_disponibles(self, volumen_minimo=1000):
        """
        Obtiene todos los pares Spot disponibles y filtra por volumen real.
        volumen_minimo: volumen mínimo 24h para considerar par confiable
        """
        if not self.conectado:
            raise Exception("No conectado al exchange")

        # Simulación: pares con volumen aleatorio
        todos_pares = [
            {"symbol": "BTCUSDT", "volumen": 50000},
            {"symbol": "ETHUSDT", "volumen": 40000},
            {"symbol": "XRPUSDT", "volumen": 200},
            {"symbol": "LTCUSDT", "volumen": 1500},
            {"symbol": "DOGEUSDT", "volumen": 50}
        ]

        pares_filtrados = [p["symbol"] for p in todos_pares if p["volumen"] >= volumen_minimo]
        return pares_filtrados

    # ======================================
    # Operaciones con interés compuesto
    # ======================================
    def ejecutar_operacion(self, tipo, usuario, symbol):
        """
        Operar considerando interés compuesto sobre el capital activo del usuario.
        """
        capital_disponible = usuario.capital_activo
        precio_actual = self.obtener_precio_actual(symbol)
        cantidad = capital_disponible / precio_actual

        orden = self.crear_orden(tipo=tipo, cantidad=cantidad, precio=precio_actual, symbol=symbol)
        usuario.capital_activo = 0
        return orden

    def cerrar_operacion(self, orden, usuario, precio_cierre):
        """
        Cierra la operación y actualiza capital aplicando interés compuesto.
        """
        resultado = self.cerrar_orden(orden["orden_id"])
        tipo = orden["tipo"]
        cantidad = orden["cantidad"]
        precio_entrada = orden["precio"]

        if tipo == "BUY":
            ganancia = cantidad * (precio_cierre - precio_entrada)
        else:
            ganancia = cantidad * (precio_entrada - precio_cierre)

        usuario.capital_total += ganancia
        usuario.capital_activo = usuario.capital_total
        return {
            "orden_id": orden["orden_id"],
            "ganancia": ganancia,
            "capital_total": usuario.capital_total,
            "capital_activo": usuario.capital_activo,
            "resultado_exchange": resultado
  }
