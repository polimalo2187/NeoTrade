from models.models import ReferidoModel

class Referido:
    """
    Clase que maneja el sistema de referidos del bot.
    Calcula las comisiones del referidor y genera el enlace único.
    """

    def __init__(self, referidor_id, referido_id):
        self.referidor_id = referidor_id    # ID del usuario que refirió
        self.referido_id = referido_id      # ID del usuario referido
        self.ganancia_diaria = 0            # Ganancia calculada del día
        self.ganancia_acumulada = 0         # Ganancia total acumulada

    def calcular_comision(self, ganancia_usuario):
        """
        Calcula la comisión del referidor basada en la ganancia del usuario.
        Registra la comisión diaria en la base de datos.
        """
        self.ganancia_diaria = ganancia_usuario * 0.03  # 3% comisión
        # Guardar ganancia diaria en la base de datos
        ReferidoModel.actualizar_ganancia_diaria(self.referido_id, self.ganancia_diaria)
        return self.ganancia_diaria

    def pagar_comision(self):
        """
        Paga la comisión al referidor. Se ejecuta a las 14:00 hora Cuba.
        Actualiza la ganancia acumulada y reinicia la diaria.
        """
        self.ganancia_acumulada += self.ganancia_diaria
        # Actualizar ganancia acumulada en la base de datos
        ReferidoModel.actualizar_ganancia_acumulada(self.referido_id, self.ganancia_acumulada)
        self.ganancia_diaria = 0

    def generar_enlace_unico(self):
        """
        Genera el enlace único de referido que el usuario puede compartir.
        """
        return f"https://t.me/TuBotTelegram?start={self.referidor_id}"
