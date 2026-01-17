class Usuario:
    """
    Clase que representa a un usuario del bot de trading.
    Maneja capital, operaciones abiertas y referidor asociado.
    """

    def __init__(self, telegram_id, api_key=None, api_secret=None, capital_total=0, referidor_id=None):
        self.telegram_id = telegram_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.capital_total = capital_total      # Capital total del usuario
        self.capital_activo = 0                 # Capital actualmente en operaciones (30% por operación)
        self.operaciones_abiertas = []          # Lista de operaciones activas
        self.referidor_id = referidor_id        # ID del referidor, si aplica

    def activar_bot(self):
        """
        Activa el bot para que inicie operaciones automáticas.
        """
        pass

    def detener_bot(self):
        """
        Detiene el bot y pausa operaciones.
        """
        pass

    def actualizar_capital(self):
        """
        Actualiza el capital total del usuario después de una operación.
        Incluye el interés compuesto.
        """
        pass

    def registrar_operacion(self, operacion):
        """
        Registra una nueva operación abierta por el bot.
        """
        self.operaciones_abiertas.append(operacion)

    def calcular_interes_compuesto(self):
        """
        Calcula el capital disponible para la siguiente operación incluyendo ganancias acumuladas.
        """
        pass
