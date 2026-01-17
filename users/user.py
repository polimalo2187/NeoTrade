import uuid

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
        self.capital_activo = 0                 # Capital disponible para la siguiente operación
        self.operaciones_abiertas = []          # Lista de operaciones activas
        self.referidor_id = referidor_id        # ID del referidor, si aplica
        self.bot_activo = False
        self.ganancia_acumulada_referidos = 0
        self.ganancia_diaria_referidos = 0

    # =========================
    # Activación / Desactivación del bot
    # =========================
    def activar_bot(self):
        """
        Activa el bot para iniciar operaciones automáticas.
        """
        self.bot_activo = True
        # Aquí se puede iniciar el loop de trading del usuario
        print(f"Bot activado para el usuario {self.telegram_id}")

    def detener_bot(self):
        """
        Detiene el bot y pausa operaciones.
        """
        self.bot_activo = False
        print(f"Bot detenido para el usuario {self.telegram_id}")

    # =========================
    # Gestión de capital e interés compuesto
    # =========================
    def actualizar_capital(self, ganancia):
        """
        Actualiza el capital total del usuario después de cerrar una operación.
        Incluye interés compuesto.
        """
        self.capital_total += ganancia
        self.calcular_interes_compuesto()

    def calcular_interes_compuesto(self):
        """
        Calcula el capital disponible para la siguiente operación.
        Por defecto, se usa el 30% del capital total.
        """
        self.capital_activo = self.capital_total * 0.3

    # =========================
    # Gestión de operaciones
    # =========================
    def registrar_operacion(self, operacion):
        """
        Registra una nueva operación abierta por el bot.
        operacion: diccionario con info de la operación
        """
        self.operaciones_abiertas.append(operacion)

    def cerrar_operacion(self, orden_id, ganancia):
        """
        Cierra una operación y actualiza capital.
        """
        # Eliminar operación de abiertas
        self.operaciones_abiertas = [op for op in self.operaciones_abiertas if op.get("orden_id") != orden_id]
        # Actualizar capital con ganancia
        self.actualizar_capital(ganancia)

    # =========================
    # Sistema de referidos
    # =========================
    def generar_enlace_unico(self):
        """
        Genera un enlace único de referido para el usuario.
        """
        return f"https://t.me/TU_BOT?start={self.telegram_id}_{uuid.uuid4().hex}"

    def actualizar_ganancia_referido(self, monto):
        """
        Actualiza la ganancia acumulada y diaria del referido.
        """
        self.ganancia_diaria_referidos += monto
        self.ganancia_acumulada_referidos += monto

    def reset_ganancia_diaria_referidos(self):
        """
        Reinicia la ganancia diaria de referidos (al cerrar el día).
        """
        self.ganancia_diaria_referidos = 0
