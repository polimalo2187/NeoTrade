import requests

class ExchangeClient:
    """
    Cliente para interactuar con el exchange CoinW (Spot).
    Permite consultar balances, precios y ejecutar órdenes.
    Preparado para integrarse con interés compuesto y capital del usuario.
    """

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.conectado = False
        # Aquí se podría inicializar la sesión con headers, etc.
        self.base_url = "https://api.coinw.com/api/v1"  # Placeholder URL

    def conectar(self):
        """
        Valida y conecta con la API del exchange.
        """
        # Aquí se puede agregar una llamada real para validar la API Key/Secret
        if self.api_key and self.api_secret:
            self.conectado = True
        else:
            self.conectado = False
        return self.conectado

    def obtener_balance(self, symbol="USDT"):
        """
        Devuelve el balance disponible del usuario en el exchange.
        Preparado para integrarse con interés compuesto.
        """
        # Aquí se puede hacer llamada real a CoinW para obtener balance
        # Por ahora retornamos balance simulado
        return 1000.0

    def obtener_precio_actual(self, symbol="BTCUSDT"):
        """
        Devuelve el precio actual del símbolo especificado.
        """
        # Aquí se puede hacer llamada real a CoinW para obtener precio
        # Por ahora retornamos precio simulado
        return 50000.0

    def crear_orden(self, tipo, cantidad, precio, symbol="BTCUSDT"):
        """
        Crea una orden de compra o venta en Spot.
        tipo: "BUY" o "SELL"
        symbol: par de trading, por defecto BTCUSDT
        """
        if not self.conectado:
            raise Exception("No conectado al exchange")

        # Aquí se puede implementar la llamada real a CoinW
        # Por ahora devolvemos orden simulada
        orden = {
            "orden_id": "ORD123456",
            "tipo": tipo,
            "cantidad": cantidad,
            "precio": precio,
            "symbol": symbol,
            "status": "OPEN"
        }
        return orden

    def cerrar_orden(self, orden_id):
        """
        Cierra la orden abierta en el exchange.
        """
        if not self.conectado:
            raise Exception("No conectado al exchange")

        # Aquí se puede implementar la llamada real a CoinW
        # Por ahora devolvemos estado simulado
        return {
            "orden_id": orden_id,
            "status": "CLOSED"
        }

    def ejecutar_operacion(self, tipo, usuario, symbol="BTCUSDT"):
        """
        Método auxiliar para operar considerando interés compuesto.
        Usa el capital activo del usuario para calcular la cantidad.
        """
        capital_disponible = usuario.capital_activo
        precio_actual = self.obtener_precio_actual(symbol)
        cantidad = capital_disponible / precio_actual  # Compra total del capital disponible

        orden = self.crear_orden(tipo=tipo, cantidad=cantidad, precio=precio_actual, symbol=symbol)

        # Actualizamos capital del usuario considerando la operación abierta
        usuario.capital_activo = 0  # Todo capital comprometido
        return orden

    def cerrar_operacion(self, orden, usuario, precio_cierre):
        """
        Método auxiliar para cerrar la operación y actualizar capital del usuario.
        Aplica el interés compuesto automático.
        """
        resultado = self.cerrar_orden(orden["orden_id"])
        # Calculamos ganancia simulada
        tipo = orden["tipo"]
        cantidad = orden["cantidad"]
        precio_entrada = orden["precio"]

        if tipo == "BUY":
            ganancia = cantidad * (precio_cierre - precio_entrada)
        else:  # SELL
            ganancia = cantidad * (precio_entrada - precio_cierre)

        # Interés compuesto: se suma al capital activo
        usuario.capital_total += ganancia
        usuario.capital_activo = usuario.capital_total  # Todo capital disponible para próxima operación

        return {
            "orden_id": orden["orden_id"],
            "ganancia": ganancia,
            "capital_total": usuario.capital_total,
            "capital_activo": usuario.capital_activo,
            "resultado_exchange": resultado
              }
