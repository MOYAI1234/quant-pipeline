def validate_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    return len(symbol) == 6 and symbol.isdigit()


def validate_price(price: float) -> bool:
    return price > 0


def validate_amount(amount: float) -> bool:
    return amount > 0


def validate_order(order: dict) -> tuple:
    errors = []
    if not order.get('action'):
        errors.append("缺少 action")
    elif order['action'] not in ('buy', 'sell', 'rebalance'):
        errors.append(f"无效的 action: {order['action']}")

    if order.get('action') in ('buy', 'sell'):
        if not validate_price(order.get('price', 0)):
            errors.append("无效的价格")
        if not validate_amount(order.get('amount', 0)):
            errors.append("无效的金额")

    return len(errors) == 0, errors
