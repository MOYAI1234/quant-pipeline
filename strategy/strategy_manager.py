class StrategyManager:

    def __init__(self):
        self.strategies = {}

    def register(self, strategy):
        self.strategies[strategy.name] = strategy

    def remove(self, name: str):
        if name in self.strategies:
            del self.strategies[name]

    def get(self, name: str):
        return self.strategies.get(name)

    def get_all(self) -> dict:
        return self.strategies

    def generate_all_signals(self, data: dict) -> dict:
        all_signals = {}
        for name, strategy in self.strategies.items():
            all_signals[name] = strategy.generate_signal(data)
        return all_signals
