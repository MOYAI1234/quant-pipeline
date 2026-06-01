from adapters.mx_search_adapter import MX_SearchAdapter


class NewsAnalyzer:

    def __init__(self, config):
        self.mx_search = MX_SearchAdapter(config.get('mx_search', {}))
        self.mx_search.connect()

    def analyze_etf_news(self, symbol: str, days: int = 7) -> dict:
        news = self.mx_search.search_etf_news(symbol, days)
        return {
            'symbol': symbol,
            'news_count': len(news),
            'news': news,
            'sentiment': self._analyze_sentiment(news)
        }

    def analyze_market_news(self, days: int = 7) -> dict:
        news = self.mx_search.search_policy_news(days)
        return {
            'news_count': len(news),
            'news': news,
            'sentiment': self._analyze_sentiment(news)
        }

    def get_hot_topics(self, days: int = 3) -> list:
        return self.mx_search.search_news("ETF 热点", days)

    def _analyze_sentiment(self, news: list) -> str:
        if not news:
            return "neutral"
        positive_keywords = ["利好", "上涨", "增长", "突破", "新高"]
        negative_keywords = ["利空", "下跌", "亏损", "风险", "暴跌"]
        pos_count = 0
        neg_count = 0
        for item in news:
            title = item.get('title', '')
            for kw in positive_keywords:
                if kw in title:
                    pos_count += 1
            for kw in negative_keywords:
                if kw in title:
                    neg_count += 1
        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"
