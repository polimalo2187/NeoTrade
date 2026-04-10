import os


class WalletAdmin:
    def __init__(self):
        self.address = os.environ.get("ADMIN_WALLET_ADDRESS")
        self.private_key = os.environ.get("ADMIN_WALLET_PRIVATE_KEY")
        self.saldo = 0.0

    @property
    def configurada(self) -> bool:
        return bool(self.address and self.private_key)

    def recibir_fee(self, monto):
        self.saldo += float(monto or 0)

    def pagar_referido(self, monto, referidor_id):
        monto = float(monto or 0)
        if monto > self.saldo:
            return False
        self.saldo -= monto
        return True

    def obtener_saldo(self):
        return self.saldo
