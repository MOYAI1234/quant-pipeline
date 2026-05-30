from abc import ABC, abstractmethod


class BaseAdapter(ABC):

    def __init__(self, config):
        self.config = config
        self.connected = False

    @abstractmethod
    def connect(self):
        pass

    def disconnect(self):
        self.connected = False

    @abstractmethod
    def health_check(self) -> bool:
        pass
