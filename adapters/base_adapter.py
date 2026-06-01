from abc import ABC


class BaseAdapter(ABC):
    SUPPORTED_MODES = {'mock', 'real'}

    def __init__(self, config):
        self.config = config
        self.mode = config.get('mode', 'mock')
        if self.mode not in self.SUPPORTED_MODES:
            raise ValueError(f"不支持的适配器模式: {self.mode}")
        self.connected = False
        self.last_error = ''

    def connect(self):
        if self.mode == 'mock':
            self.connected = True
            self.last_error = ''
            return

        self.connected = False
        self.last_error = 'real mode not implemented'

    def disconnect(self):
        self.connected = False

    def health_check(self) -> dict:
        return {
            'service': self.__class__.__name__,
            'mode': self.mode,
            'connected': self.connected,
            'available': self.connected and not self.last_error,
            'mock': self.mode == 'mock',
            'error': self.last_error,
        }

    def _ensure_available(self):
        from data.contracts import ServiceUnavailableError

        if self.mode != 'mock':
            raise ServiceUnavailableError(
                f"{self.__class__.__name__} real mode is not implemented",
                error_code='REAL_MODE_NOT_IMPLEMENTED',
                source=self.__class__.__name__,
            )
        if not self.connected:
            raise ServiceUnavailableError(
                f"{self.__class__.__name__} is not connected",
                error_code='ADAPTER_NOT_CONNECTED',
                source=self.__class__.__name__,
            )
