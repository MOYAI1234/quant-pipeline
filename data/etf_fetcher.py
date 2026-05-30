from .data_manager import DataManager


class ETFFetcher:

    def __init__(self, data_manager: DataManager):
        self.dm = data_manager

    def get_price(self, symbol: str) -> float:
        data = self.dm.get_etf_realtime(symbol)
        return data.get('price', 0)

    def get_nav_premium(self, symbol: str) -> dict:
        return self.dm.get_etf_nav(symbol)

    def get_history_prices(self, symbol: str, days: int = 30) -> list:
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        history = self.dm.get_etf_history(symbol, start_date, end_date)
        return [h.get('close', 0) for h in history]

    def get_volume(self, symbol: str) -> float:
        data = self.dm.get_etf_realtime(symbol)
        return data.get('amount', 0)
