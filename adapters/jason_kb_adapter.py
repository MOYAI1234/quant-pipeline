from .base_adapter import BaseAdapter


class JasonKBAdapter(BaseAdapter):

    def __init__(self, config):
        super().__init__(config)

    def get_market_sentiment(self) -> dict:
        self._ensure_available()
        return {
            'sentiment': 'neutral',
            'score': 50,
            'factors': []
        }

    def get_industry_analysis(self, industry: str) -> dict:
        self._ensure_available()
        return {
            'industry': industry,
            'outlook': 'positive',
            'reasons': []
        }

    def get_risk_warning(self) -> list:
        self._ensure_available()
        return []

    def get_investment_advice(self, _portfolio: dict) -> dict:
        self._ensure_available()
        return {
            'suggestions': [],
            'warnings': []
        }
