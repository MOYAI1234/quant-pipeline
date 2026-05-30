from datetime import datetime, timedelta


def format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def format_percent(value: float) -> str:
    return f"{value:.2f}%"


def get_date_range(days: int) -> tuple:
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')


def calculate_return(start_price: float, end_price: float) -> float:
    if start_price == 0:
        return 0
    return (end_price - start_price) / start_price * 100


def calculate_sharpe(returns: list, risk_free_rate: float = 0.03) -> float:
    if not returns:
        return 0
    avg_return = sum(returns) / len(returns)
    if len(returns) < 2:
        return 0
    variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
    std = variance ** 0.5
    if std == 0:
        return 0
    return (avg_return - risk_free_rate) / std
