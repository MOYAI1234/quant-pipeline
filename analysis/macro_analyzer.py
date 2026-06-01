from adapters.jason_kb_adapter import JasonKBAdapter


class MacroAnalyzer:

    def __init__(self, config):
        self.jason_kb = JasonKBAdapter(config.get('jason_kb', {}))
        self.jason_kb.connect()

    def connect(self):
        self.jason_kb.connect()

    def get_market_analysis(self) -> dict:
        sentiment = self.jason_kb.get_market_sentiment()
        warnings = self.jason_kb.get_risk_warning()
        return {
            'sentiment': sentiment,
            'warnings': warnings,
            'recommendation': self._generate_recommendation(sentiment, warnings)
        }

    def get_industry_outlook(self, industry: str) -> dict:
        return self.jason_kb.get_industry_analysis(industry)

    def get_investment_advice(self, portfolio: dict) -> dict:
        return self.jason_kb.get_investment_advice(portfolio)

    def _generate_recommendation(self, sentiment: dict, warnings: list) -> str:
        score = sentiment.get('score', 50)
        if score > 70:
            return "市场情绪积极，可适当增加仓位"
        elif score < 30:
            return "市场情绪悲观，建议谨慎操作"
        else:
            return "市场情绪中性，保持现有策略"
