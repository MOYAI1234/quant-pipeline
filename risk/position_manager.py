class PositionManager:

    def __init__(self, config):
        self.max_position = config.get('max_position', 5)
        self.max_single_weight = config.get('max_single_weight', 0.25)
        self.max_industry_weight = config.get('max_industry_weight', 0.30)

    def check_position_limit(self, portfolio: dict, new_symbol: str = None) -> dict:
        checks = []
        positions = portfolio.get('positions', {})
        current_count = len(positions)

        if new_symbol not in positions and current_count >= self.max_position:
            checks.append(f"仓位已满: {current_count}/{self.max_position}")

        return {
            'passed': len(checks) == 0,
            'checks': checks
        }

    def check_weight_limit(self, portfolio: dict, order_amount: float) -> dict:
        checks = []
        total_value = portfolio.get('total_value', 0)

        if total_value > 0:
            weight = order_amount / total_value
            if weight > self.max_single_weight:
                checks.append(f"单笔权重过大: {weight:.2%} > {self.max_single_weight:.2%}")

        return {
            'passed': len(checks) == 0,
            'checks': checks
        }
