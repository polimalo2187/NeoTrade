from telegram.bot import Bot as TradingBot  # Importa tu clase Bot del proyecto
from scheduler.scheduler import Scheduler

def main():
    """
    Punto de entrada del bot de trading.
    Inicializa el bot de Telegram y el scheduler de tareas recurrentes.
    """
    # Inicializar bot de Telegram
    bot = TradingBot()
    bot.start_bot()  # Llama al método start_bot() de tu clase

    # Inicializar scheduler
    scheduler = Scheduler()
    scheduler.start()

if __name__ == "__main__":
    main()
