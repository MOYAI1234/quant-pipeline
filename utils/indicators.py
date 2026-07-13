def calc_ma(prices: list, period: int) -> list:
    if len(prices) < period:
        return []
    result = []
    for i in range(period - 1, len(prices)):
        avg = sum(prices[i - period + 1:i + 1]) / period
        result.append(avg)
    return result


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(prices) < slow:
        return {'macd': 0, 'signal': 0, 'histogram': 0}
    fast_ema = _calc_ema(prices, fast)
    slow_ema = _calc_ema(prices, slow)
    macd_line = fast_ema - slow_ema
    return {'macd': macd_line, 'signal': 0, 'histogram': macd_line}


def calc_bollinger(prices: list, period: int = 20, std_dev: float = 2.0) -> dict:
    if len(prices) < period:
        return {'upper': 0, 'middle': 0, 'lower': 0}
    recent = prices[-period:]
    middle = sum(recent) / period
    variance = sum((p - middle) ** 2 for p in recent) / period
    std = variance ** 0.5
    return {
        'upper': middle + std_dev * std,
        'middle': middle,
        'lower': middle - std_dev * std
    }


def _calc_ema(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema
