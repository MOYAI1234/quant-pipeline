class StopLoss:

    def __init__(self, config):
        self.stop_loss_pct = config.get('stop_loss', 0.15)
        self.max_single_loss = config.get('max_single_loss', 0.02)
        self.trailing_stop = config.get('trailing_stop', False)
        self.trailing_pct = config.get('trailing_pct', 0.05)
        self.high_prices = {}

    def check_stop_loss(self, symbol: str, current_price: float, avg_price: float) -> dict:
        if avg_price <= 0:
            return {'triggered': False, 'reason': ''}

        loss_pct = (avg_price - current_price) / avg_price

        if loss_pct >= self.stop_loss_pct:
            return {
                'triggered': True,
                'reason': f'止损触发: 亏损{loss_pct:.2%} >= {self.stop_loss_pct:.2%}'
            }

        if loss_pct >= self.max_single_loss:
            return {
                'triggered': True,
                'reason': f'单笔止损触发: 亏损{loss_pct:.2%} >= {self.max_single_loss:.2%}'
            }

        return {'triggered': False, 'reason': ''}

    def update_high_price(self, symbol: str, price: float):
        if symbol not in self.high_prices or price > self.high_prices[symbol]:
            self.high_prices[symbol] = price

    def check_trailing_stop(self, symbol: str, current_price: float) -> dict:
        if not self.trailing_stop or symbol not in self.high_prices:
            return {'triggered': False, 'reason': ''}

        high = self.high_prices[symbol]
        drawdown = (high - current_price) / high

        if drawdown >= self.trailing_pct:
            return {
                'triggered': True,
                'reason': f'跟踪止损触发: 回撤{drawdown:.2%} >= {self.trailing_pct:.2%}'
            }

        return {'triggered': False, 'reason': ''}
