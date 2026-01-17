# Plantillas de mensajes para el bot de trading en Telegram

def mensaje_capital(usuario):
    """
    Retorna el mensaje con el capital del usuario.
    """
    return (
        f"💰 Capital Total: {usuario.capital_total}\n"
        f"📊 Capital Activo: {usuario.capital_activo}\n"
        f"💹 Capital disponible para próxima operación: {usuario.capital_activo}"
    )

def mensaje_historial(operaciones):
    """
    Retorna el historial de operaciones del usuario.
    operaciones: lista de diccionarios con info de cada operación
    """
    if not operaciones:
        return "📄 No hay operaciones registradas aún."
    
    mensaje = "📄 Historial de Operaciones:\n"
    for op in operaciones[-10:]:  # Mostrar últimas 10 operaciones
        mensaje += (
            f"\n🔹 Tipo: {op.get('tipo', 'N/A')}"
            f"\n💵 Entrada: {op.get('entry_price', 'N/A')}"
            f"\n💰 Salida: {op.get('exit_price', 'N/A')}"
            f"\n📈 Score: {op.get('score', 'N/A')}"
            f"\n✅ Estado: {op.get('status', 'N/A')}\n"
        )
    return mensaje

def mensaje_referidos(usuario):
    """
    Retorna el mensaje con el enlace único de referidos y ganancias.
    """
    enlace = usuario.generar_enlace_unico() if hasattr(usuario, 'generar_enlace_unico') else "Enlace no disponible"
    return (
        f"🔗 Tu enlace único de referido:\n{enlace}\n\n"
        f"💵 Ganancia diaria referidos: {getattr(usuario, 'ganancia_diaria', 0)}\n"
        f"💰 Ganancia acumulada referidos: {getattr(usuario, 'ganancia_acumulada', 0)}"
    )

def mensaje_configuracion():
    """
    Retorna mensaje de introducción al menú de configuración.
    """
    return (
        "⚙️ Menú de Configuración:\n"
        "🔑 API Key / Secret\n"
        "⚙️ Preferencias\n"
        "🔔 Notificaciones"
    )
