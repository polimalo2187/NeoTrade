class ExchangeClient:
    """
    Cliente para interactuar con el exchange CoinW (Spot).
    Permite consultar balances, precios y ejecutar órdenes.
    """

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        # Aquí se inicializaría la conexión con la API del exchange
        self.conectado = False

    def conectar(self):
        """
        Valida y conecta con la API del exchange.
        """
        # Lógica de validación de API Key/Secret
        self.conectado = True
        return self.conectado

    def obtener_balance(self, symbol="USDT"):
        """
        Devuelve el balance disponible del usuario en el exchange.
        """
        # Retornar balance simulado por ahora
        return 1000.0

    def obtener_precio_actual(self, symbol="BTCUSDT"):
        """
        Devuelve el precio actual del símbolo especificado.
        """
        # Retornar precio simulado por ahora
        return 50000.0

    def crear_orden(self, tipo, cantidad, precio):
        """
        Crea una orden de compra o venta en Spot.
        tipo: "BUY" o "SELL"
        """
        # Retornar un diccionario simulado de la orden
        return {
            "orden_id": "ORD123456",
            "tipo": tipo,
            "cantidad": cantidad,
            "precio": precio,
            "status": "OPEN"
        }

    def cerrar_orden(self, orden_id):
        """
        Cierra la orden abierta en el exchange.
        """
        # Retornar estado simulado
        return {
            "orden_id": orden_id,
            "status": "CLOSED"
        }
