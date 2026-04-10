from typing import Dict, List


def mensaje_capital(usuario: Dict) -> str:
    capital_total = usuario.get("capital_total", 0)
    capital_activo = usuario.get("capital_activo", 0)
    active_position = usuario.get("active_position")

    lines = [
        f"💰 Capital estimado: {capital_total:.4f}",
        f"📊 Capital activo configurado: {capital_activo:.4f}",
        f"🤖 Bot activo: {'Sí' if usuario.get('bot_activo') else 'No'}",
    ]

    if active_position:
        lines.extend(
            [
                "",
                "📍 Posición activa:",
                f"Par: {active_position.get('symbol')}",
                f"Entrada: {active_position.get('entry_price')}",
                f"SL: {active_position.get('stop_loss')}",
                f"TP: {active_position.get('take_profit')}",
            ]
        )

    if usuario.get("last_engine_error"):
        lines.extend(["", f"⚠️ Último error del motor: {usuario['last_engine_error']}"])

    return "\n".join(lines)


def mensaje_historial(operaciones: List[Dict]) -> str:
    if not operaciones:
        return "📄 No hay operaciones registradas aún."

    bloques = ["📄 Últimas operaciones:"]
    for op in operaciones[:10]:
        bloques.append(
            "\n".join(
                [
                    f"• Par: {op.get('symbol', 'N/A')}",
                    f"  Tipo: {op.get('side', op.get('tipo', 'N/A'))}",
                    f"  Entrada: {op.get('entry_price', 'N/A')}",
                    f"  Salida: {op.get('exit_price', 'N/A')}",
                    f"  Estado: {op.get('status', 'N/A')}",
                    f"  PnL: {op.get('pnl_quote', 0):.4f} {op.get('quote_asset', 'USDT')}",
                ]
            )
        )
    return "\n\n".join(bloques)


def mensaje_referidos(usuario: Dict) -> str:
    enlace = f"https://t.me/TradeNeo_bot?start={usuario.get('codigo_referido', usuario.get('telegram_id'))}"
    return (
        f"🔗 Tu enlace único de referido:\n{enlace}\n\n"
        f"💵 Ganancia diaria referidos: {usuario.get('ganancia_diaria_referidos', 0):.2f} USDT\n"
        f"💰 Ganancia acumulada referidos: {usuario.get('ganancia_acumulada_referidos', 0):.2f} USDT"
    )


def mensaje_configuracion() -> str:
    return (
        "⚙️ Menú de configuración\n"
        "• API Key / Secret de CoinW Spot\n"
        "• Estado del bot\n"
        "• Notificaciones básicas de operaciones"
    )
