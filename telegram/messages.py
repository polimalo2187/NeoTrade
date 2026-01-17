# =========================
# Plantillas de mensajes para el bot de trading en Telegram
# =========================

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
    ganancia_diaria = getattr(usuario, 'ganancia_diaria', 0)
    ganancia_acumulada = getattr(usuario, 'ganancia_acumulada', 0)
    
    return (
        f"🔗 Tu enlace único de referido:\n{enlace}\n\n"
        f"💵 Ganancia diaria referidos: {ganancia_diaria:.2f} USDT\n"
        f"💰 Ganancia acumulada referidos: {ganancia_acumulada:.2f} USDT"
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

# =========================
# Funciones adicionales para el panel de administrador
# =========================

def mensaje_capital_total_usuarios(usuarios):
    """
    Mensaje con el capital total de todos los usuarios.
    """
    total = sum(u.get("capital_total", 0) for u in usuarios)
    return f"💰 Capital total de todos los usuarios: {total:.2f} USDT"

def mensaje_comisiones_referidos(referidos):
    """
    Mensaje con todas las comisiones de referidos registradas.
    """
    if not referidos:
        return "No hay comisiones registradas aún."
    
    mensaje = "🔗 Comisiones de referidos:\n"
    for r in referidos:
        mensaje += f"{r['referidor_id']}: {r.get('comision', 0):.2f} USDT\n"
    return mensaje

def mensaje_historial_completo(operaciones):
    """
    Mensaje con historial completo de todas las operaciones de todos los usuarios.
    """
    if not operaciones:
        return "No hay operaciones registradas aún."
    
    mensaje = "📄 Historial completo de operaciones:\n"
    for op in operaciones[-20:]:  # últimas 20 operaciones globales
        mensaje += (
            f"\nUsuario: {op.get('telegram_id', 'N/A')}"
            f"\n🔹 Tipo: {op.get('tipo', 'N/A')}"
            f"\n💵 Entrada: {op.get('entry_price', 'N/A')}"
            f"\n💰 Salida: {op.get('exit_price', 'N/A')}"
            f"\n📈 Score: {op.get('score', 'N/A')}"
            f"\n✅ Estado: {op.get('status', 'N/A')}\n"
        )
    return mensaje
