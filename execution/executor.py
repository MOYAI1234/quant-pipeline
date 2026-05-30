from abc import ABC, abstractmethod


class BaseExecutor(ABC):

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def execute_order(self, order: dict) -> bool:
        pass

    @abstractmethod
    def get_portfolio(self) -> dict:
        pass
