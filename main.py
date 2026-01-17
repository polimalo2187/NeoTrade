from telegram.bot import Bot
from scheduler.scheduler import Scheduler

def main():
    """
    Punto de entrada del bot de trading.
    Inicializa el bot de Telegram y el scheduler de tareas recurrentes.
    """
    # Inicializar bot de Telegram
    bot = Bot()
    bot.start()

    # Inicializar scheduler
    scheduler = Scheduler()
    scheduler.start()

if __name__ == "__main__":
    main()
