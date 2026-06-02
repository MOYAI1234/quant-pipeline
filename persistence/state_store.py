import json
from pathlib import Path


STATE_VERSION = 1


class JsonStateStore:

    def __init__(self, path: str):
        self.path = Path(path)

    def build_snapshot(self, executor, strategies: dict) -> dict:
        return {
            'version': STATE_VERSION,
            'account': executor.snapshot(),
            'strategies': {
                name: strategy.snapshot()
                for name, strategy in strategies.items()
                if hasattr(strategy, 'snapshot')
            },
        }

    def save(self, executor, strategies: dict) -> dict:
        state = self.build_snapshot(executor, strategies)
        self.save_state(state)
        return state

    def save_state(self, state: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temp_path.replace(self.path)

    def load_state(self) -> dict:
        if not self.path.exists():
            return {}
        state = json.loads(self.path.read_text(encoding='utf-8'))
        self._validate_state_version(state)
        return state

    def restore(self, executor, strategies: dict, state: dict = None) -> dict:
        loaded_state = state if state is not None else self.load_state()
        if not loaded_state:
            return {}
        if state is not None:
            self._validate_state_version(loaded_state)

        account_state = loaded_state.get('account')
        if account_state:
            executor.restore(account_state)

        strategy_states = loaded_state.get('strategies', {})
        for name, strategy_state in strategy_states.items():
            strategy = strategies.get(name)
            if strategy and hasattr(strategy, 'restore'):
                self._validate_strategy_type(name, strategy, strategy_state)
                strategy.restore(strategy_state)
        return loaded_state

    def _validate_state_version(self, state: dict):
        if state.get('version') != STATE_VERSION:
            raise ValueError('不支持的状态文件版本')

    def _validate_strategy_type(self, name: str, strategy, strategy_state: dict):
        state_type = strategy_state.get('type')
        expected_type = strategy.__class__.__name__
        if state_type and state_type != expected_type:
            raise ValueError(
                f"策略状态类型不匹配: {name} 需要 {expected_type}, 实际为 {state_type}"
            )
