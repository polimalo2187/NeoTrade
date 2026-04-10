from typing import Dict, List, Optional

from app.config import ADMIN_COINW_UID, FEE_SETTLEMENT_THRESHOLD, PAYMENT_ASSET


def mensaje_capital(usuario: Dict) -> str:
    capital_total = usuario.get("capital_total", 0)
    capital_activo = usuario.get("capital_activo", 0)
    active_position = usuario.get("active_position")

    lines = [
        f"💰 Capital estimado: {capital_total:.4f} {PAYMENT_ASSET}",
        f"📊 Capital operativo configurado: {capital_activo:.4f} {PAYMENT_ASSET}",
        f"🤖 Bot activo: {'Sí' if usuario.get('bot_activo') else 'No'}",
        f"🔐 Trading habilitado: {'Sí' if usuario.get('trading_enabled', True) else 'No'}",
        f"💸 Fee pendiente: {float(usuario.get('fee_due_total', 0) or 0):.2f} {PAYMENT_ASSET}",
        f"📌 Umbral fee: {float(usuario.get('fee_threshold', FEE_SETTLEMENT_THRESHOLD) or FEE_SETTLEMENT_THRESHOLD):.2f} {PAYMENT_ASSET}",
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

    if usuario.get("trading_pause_reason") == "fee_due":
        lines.extend(["", "⛔ Trading pausado por fee pendiente."])

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
                    f"  PnL: {op.get('pnl_quote', 0):.4f} {op.get('quote_asset', PAYMENT_ASSET)}",
                    f"  Fee: {float(op.get('fee_generated', 0) or 0):.4f} {op.get('quote_asset', PAYMENT_ASSET)}",
                ]
            )
        )
    return "\n\n".join(bloques)


def mensaje_referidos(usuario: Dict) -> str:
    enlace = f"https://t.me/TradeNeo_bot?start={usuario.get('codigo_referido', usuario.get('telegram_id'))}"
    return (
        f"🔗 Tu enlace único de referido:\n{enlace}\n\n"
        f"💵 Ganancia diaria referidos: {usuario.get('ganancia_diaria_referidos', 0):.2f} {PAYMENT_ASSET}\n"
        f"💰 Ganancia acumulada referidos: {usuario.get('ganancia_acumulada_referidos', 0):.2f} {PAYMENT_ASSET}"
    )


def mensaje_configuracion() -> str:
    return (
        "⚙️ Menú de configuración\n"
        "• API Key / Secret de CoinW Spot\n"
        "• Estado del bot\n"
        "• Notificaciones básicas de operaciones\n"
        "• Fee admin con pago manual interno CoinW"
    )


def mensaje_fee(usuario: Dict, invoice: Optional[Dict]) -> str:
    fee_due = float(usuario.get("fee_due_total", 0) or 0)
    fee_paid = float(usuario.get("fee_paid_total", 0) or 0)
    fee_status = usuario.get("fee_status", "clear")
    threshold = float(usuario.get("fee_threshold", FEE_SETTLEMENT_THRESHOLD) or FEE_SETTLEMENT_THRESHOLD)

    lines = [
        "💸 Estado de fee",
        f"Pendiente actual: {fee_due:.2f} {PAYMENT_ASSET}",
        f"Pagado histórico: {fee_paid:.2f} {PAYMENT_ASSET}",
        f"Umbral de bloqueo: {threshold:.2f} {PAYMENT_ASSET}",
        f"Estado: {fee_status}",
    ]

    if usuario.get("trading_pause_reason") == "fee_due":
        lines.extend(["", "⛔ Tu trading está pausado por fee pendiente."])

    if invoice:
        lines.extend(
            [
                "",
                f"Factura activa: {invoice.get('invoice_id')}",
                f"Monto exacto: {float(invoice.get('invoice_amount', 0) or 0):.2f} {invoice.get('asset', PAYMENT_ASSET)}",
                "Método: CoinW Internal Transfer",
                f"UID destino: {invoice.get('destination_uid') or ADMIN_COINW_UID or 'NO_CONFIGURADO'}",
                f"Estado factura: {invoice.get('status')}",
                "",
                "Después de pagar, pulsa '✅ Ya pagué fee' y reporta el pago.",
            ]
        )
    else:
        lines.extend(["", "No hay factura activa en este momento."])

    return "\n".join(lines)
