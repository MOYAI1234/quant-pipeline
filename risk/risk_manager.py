from .etf_risk_checker import ETFRiskChecker
from .position_manager import PositionManager
from .stop_loss import StopLoss


class RiskManager:

    def __init__(self, config):
        self.config = config
        self.etf_checker = ETFRiskChecker(config)
        self.position_manager = PositionManager(config)
        self.stop_loss = StopLoss(config)

    def check_order(self, order: dict, portfolio: dict) -> dict:
        checks = []

        action = order.get('action')
        symbol = order.get('symbol', '')

        if action == 'buy':
            etf_check = self.etf_checker.check_etf_quality(symbol)
            if not etf_check['passed']:
                checks.extend(etf_check['checks'])

            pos_check = self.position_manager.check_position_limit(portfolio, symbol)
            if not pos_check['passed']:
                checks.extend(pos_check['checks'])

            weight_check = self.position_manager.check_weight_limit(
                portfolio, order.get('amount', 0)
            )
            if not weight_check['passed']:
                checks.extend(weight_check['checks'])

        elif action == 'sell':
            positions = portfolio.get('positions', {})
            if symbol not in positions:
                checks.append(f"无持仓: {symbol}")

        return {
            'passed': len(checks) == 0,
            'checks': checks
        }

    def check_portfolio_stop_loss(self, portfolio: dict) -> list:
        """检查所有持仓的止损条件，返回需要执行的卖出信号"""
        stop_loss_signals = []
        positions = portfolio.get('positions', {})

        for symbol, pos in positions.items():
            current_price = pos.get('current_price', 0)
            avg_price = pos.get('avg_price', 0)

            if current_price <= 0 or avg_price <= 0:
                continue

            # 检查固定止损
            stop_check = self.stop_loss.check_stop_loss(symbol, current_price, avg_price)
            if stop_check['triggered']:
                stop_loss_signals.append({
                    'action': 'sell',
                    'symbol': symbol,
                    'price': current_price,
                    'amount': pos.get('shares', 0) * current_price,
                    'reason': stop_check['reason']
                })
                continue

            # 检查跟踪止损
            self.stop_loss.update_high_price(symbol, current_price)
            trailing_check = self.stop_loss.check_trailing_stop(symbol, current_price)
            if trailing_check['triggered']:
                stop_loss_signals.append({
                    'action': 'sell',
                    'symbol': symbol,
                    'price': current_price,
                    'amount': pos.get('shares', 0) * current_price,
                    'reason': trailing_check['reason']
                })

        return stop_loss_signals

    def check_portfolio_risk(self, portfolio: dict) -> dict:
        alerts = []

        pnl_percent = portfolio.get('pnl_percent', 0)
        if pnl_percent < self.config.get('alert_threshold', -10):
            alerts.append(f"总亏损告警: {pnl_percent:.2f}%")

        return {
            'safe': len(alerts) == 0,
            'alerts': alerts
        }
