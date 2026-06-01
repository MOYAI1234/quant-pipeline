import signal
import sys
from datetime import datetime

from config.settings import SYSTEM_CONFIG
from config.logging_config import setup_logging
from data.data_manager import DataManager
from strategy.strategy_manager import StrategyManager
from execution.simulator import Simulator
from risk.risk_manager import RiskManager
from analysis.macro_analyzer import MacroAnalyzer
from monitor.monitor import SystemMonitor
from monitor.report import ReportGenerator


class QuantPipeline:

    def __init__(self, config=None):
        self.config = config or SYSTEM_CONFIG
        self.logger = setup_logging()

        self.data_manager = DataManager(self.config.get('data', {}))
        self.strategy_manager = StrategyManager()
        self.executor = Simulator(self.config.get('account', {}))
        self.risk_manager = RiskManager(self.config.get('risk', {}))
        self.macro_analyzer = MacroAnalyzer(self.config.get('analysis', {}))
        self.monitor = SystemMonitor(self.config.get('monitor', {}))
        self.report_generator = ReportGenerator(self.config.get('monitor', {}))

        self.running = False

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.logger.info("收到退出信号，正在停止...")
        self.running = False

    def add_strategy(self, strategy):
        self.strategy_manager.register(strategy)
        self.logger.info(f"注册策略: {strategy.name}")

    def connect(self):
        self.logger.info("连接数据源...")
        self.data_manager.connect()
        self.logger.info("连接分析服务...")
        self.macro_analyzer.connect()
        self.logger.info("所有服务已连接")

    def run(self):
        self.logger.info("=" * 50)
        self.logger.info("量化助手 Pipeline 启动")
        self.logger.info("=" * 50)

        self.connect()

        self.logger.info("获取宏观分析...")
        macro_analysis = self.macro_analyzer.get_market_analysis()
        self.logger.info(f"市场情绪: {macro_analysis['sentiment']['sentiment']}")
        self.logger.info(f"投资建议: {macro_analysis['recommendation']}")

        self.running = True
        self.logger.info("开始运行策略...")

        check_interval = self.config.get('monitor', {}).get('check_interval', 60)

        while self.running:
            try:
                self.run_once()

                import time
                time.sleep(check_interval)

            except Exception as e:
                self.logger.error(f"错误: {e}")
                import time
                time.sleep(check_interval)

        self.stop()

    def run_once(self):
        """执行一轮行情获取、风控检查、策略信号和监控更新。"""
        # 获取所有持仓的实时行情
        current_prices = {}
        for symbol in self.executor.positions:
            quote = self.data_manager.get_etf_realtime(symbol)
            if quote and quote.get('price', 0) > 0:
                current_prices[symbol] = quote['price']

        # 获取组合状态（使用实时价格估值）
        portfolio = self.executor.get_portfolio(current_prices)

        # 检查持仓止损
        stop_loss_signals = self.risk_manager.check_portfolio_stop_loss(portfolio)
        for sig in stop_loss_signals:
            risk_check = self.risk_manager.check_order(sig, portfolio)
            if risk_check['passed']:
                success = self.executor.execute_order(sig)
                if success:
                    # 通知所有持有该 symbol 的策略
                    for name, strategy in self.strategy_manager.get_all().items():
                        if hasattr(strategy, 'on_trade_confirmed'):
                            strategy.on_trade_confirmed(sig)
                    self.logger.info(f"[止损] 执行卖出: {sig['symbol']} {sig.get('price', 0)}")

        # 更新组合状态
        portfolio = self.executor.get_portfolio(current_prices)

        for name, strategy in self.strategy_manager.get_all().items():
            # 获取市场数据
            if hasattr(strategy, 'etf_pool'):
                data = {}
                for symbol in strategy.etf_pool:
                    data[symbol] = self.data_manager.get_etf_realtime(symbol)
                    history = self.data_manager.get_etf_history(symbol, '', '')
                    if history:
                        data[symbol]['prices'] = [h.get('close', 0) for h in history]
            else:
                data = self.data_manager.get_etf_realtime(strategy.symbol)

            # 传递 portfolio 给策略
            signals = strategy.generate_signal(data, portfolio)

            for sig in signals:
                risk_check = self.risk_manager.check_order(
                    sig, portfolio
                )

                if risk_check['passed']:
                    success = self.executor.execute_order(sig)
                    if success:
                        strategy.record_trade(sig)
                        if hasattr(strategy, 'on_trade_confirmed'):
                            strategy.on_trade_confirmed(sig)
                        self.logger.info(
                            f"[{name}] 执行交易: {sig['action']} {sig.get('price', 0)}"
                        )
                    else:
                        if hasattr(strategy, 'on_trade_failed'):
                            strategy.on_trade_failed(sig)
                        self.logger.warning(
                            f"[{name}] 执行失败: {sig['action']} {sig.get('price', 0)}"
                        )
                else:
                    if hasattr(strategy, 'on_trade_failed'):
                        strategy.on_trade_failed(sig)
                    self.logger.warning(
                        f"[{name}] 风险检查未通过: {risk_check['checks']}"
                    )

        self.monitor.update_metrics(
            self.executor.get_portfolio(current_prices),
            self._get_strategy_summary()
        )

        return self.get_status()

    def _get_strategy_summary(self) -> dict:
        summary = {}
        for name, strategy in self.strategy_manager.get_all().items():
            summary[name] = strategy.get_performance()
        return summary

    def get_status(self) -> dict:
        portfolio = self.executor.get_portfolio()
        strategy_summary = self._get_strategy_summary()
        return {
            'portfolio': portfolio,
            'strategies': strategy_summary,
            'metrics': self.monitor.get_metrics()
        }

    def generate_report(self, report_type: str = 'daily') -> str:
        portfolio = self.executor.get_portfolio()
        strategy_summary = self._get_strategy_summary()
        if report_type == 'weekly':
            return self.report_generator.generate_weekly_report(portfolio, strategy_summary)
        return self.report_generator.generate_daily_report(portfolio, strategy_summary)

    def stop(self):
        self.logger.info("系统停止中...")
        self.monitor.print_status()

        self.logger.info("策略表现:")
        for name, strategy in self.strategy_manager.get_all().items():
            perf = strategy.get_performance()
            self.logger.info(
                f"[{name}] 交易次数: {perf.get('total_trades', 0)}, "
                f"胜率: {perf.get('win_rate', 0):.2%}, "
                f"总收益: {perf.get('total_profit', 0):.2f}"
            )

        self.data_manager.disconnect()
        self.logger.info("系统已停止")


if __name__ == '__main__':
    from strategy.grid_strategy import GridStrategy

    system = QuantPipeline()

    grid_strategy = GridStrategy({
        'name': '网格策略-沪深300',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 5,
        'capital_per_grid': 10000,
    })
    system.add_strategy(grid_strategy)

    system.run()
