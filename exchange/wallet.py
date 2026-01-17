import os

class WalletAdmin:
    """
    Maneja la wallet externa de USDT/BSC del administrador.
    """

    def __init__(self):
        # Claves de la wallet almacenadas en variables de entorno
        self.api_key = os.environ.get("ADMIN_WALLET_API_KEY")
        self.api_secret = os.environ.get("ADMIN_WALLET_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise ValueError("Debe configurar ADMIN_WALLET_API_KEY y ADMIN_WALLET_API_SECRET en las variables de entorno")
        self.saldo = 0.0  # Saldo simulado para pruebas

    def recibir_fee(self, monto):
        """
        Recibe las fees cobradas de los usuarios.
        """
        self.saldo += monto
        print(f"💵 Fee recibida: {monto} USDT. Saldo actual: {self.saldo} USDT")

    def pagar_referido(self, monto, referidor_id):
        """
        Paga la comisión de un referido desde la wallet del administrador.
        """
        if monto > self.saldo:
            print(f"⚠️ Saldo insuficiente para pagar al referido {referidor_id}")
            return False
        self.saldo -= monto
        print(f"💸 Comisión pagada al referido {referidor_id}: {monto} USDT. Saldo restante: {self.saldo} USDT")
        return True

    def obtener_saldo(self):
        """
        Devuelve el saldo actual de la wallet del administrador.
        """
        return self.saldo
