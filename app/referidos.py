from app.models import ReferidoModel


class Referido:
    def __init__(self, referidor_id, referido_id, comision=0.0):
        self.referidor_id = referidor_id
        self.referido_id = referido_id
        self.ganancia_diaria = float(comision or 0)
        self.ganancia_acumulada = 0.0

    def calcular_comision(self, ganancia_usuario):
        self.ganancia_diaria = max(float(ganancia_usuario or 0), 0.0) * 0.03
        ReferidoModel.actualizar_ganancia_diaria(self.referido_id, self.ganancia_diaria)
        return self.ganancia_diaria

    def pagar_comision(self):
        if self.ganancia_diaria <= 0:
            return
        self.ganancia_acumulada += self.ganancia_diaria
        ReferidoModel.actualizar_ganancia_acumulada(self.referido_id, self.ganancia_diaria)
        self.ganancia_diaria = 0.0

    def generar_enlace_unico(self):
        return f"https://t.me/TuBotTelegram?start={self.referidor_id}"
