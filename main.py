import signal
import sys
import time
from datetime import datetime

from config.settings import SYSTEM_CONFIG
from config.logging_config import setup_logging
from data.data_manager import DataManager
from strategy.strategy_manager import StrategyManager
from execution.order_manager import OrderManager
from execution.simulator import Simulator
from persistence import JsonStateStore
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
        self.order_manager = OrderManager()
        self.risk_manager = RiskManager(self.config.get('risk', {}))
        self.macro_analyzer = MacroAnalyzer(self.config.get('analysis', {}))
        self.monitor = SystemMonitor(self.config.get('monitor', {}))
        self.report_generator = ReportGenerator(self.config.get('monitor', {}))
        self.state_config = self.config.get('state', {})
        self.state_store = self._build_state_store(self.state_config)
        self.state_restore_failed = False
        self.runtime_state = self._default_runtime_state()

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

    def _build_state_store(self, state_config: dict):
        if not state_config.get('enabled', False):
            return None
        return JsonStateStore(state_config.get('path', 'data/state.json'))

    def restore_state(self) -> dict:
        if not self.state_store:
            return {}
        self.state_restore_failed = False
        try:
            restored_state = self.state_store.restore(
                self.executor,
                dict(self.strategy_manager.get_all()),
                order_manager=self.order_manager,
            )
        except Exception as e:
            self.state_restore_failed = True
            self.logger.warning(f"状态恢复失败，使用默认状态: {e}")
            return {}
        if restored_state:
            self.runtime_state = self._merge_runtime_state(
                restored_state.get('metadata', {})
            )
            self.logger.info(f"已恢复状态: {self.state_store.path}")
        return restored_state

    def save_state(self) -> dict:
        if not self.state_store:
            return {}
        if self.state_restore_failed:
            self.logger.warning("状态恢复失败，本轮跳过状态保存，避免覆盖原状态文件")
            return {}
        saved_state = self.state_store.save(
            self.executor,
            dict(self.strategy_manager.get_all()),
            self.runtime_state,
            self.order_manager,
        )
        self.logger.info(f"已保存状态: {self.state_store.path}")
        return saved_state

    def _merge_runtime_state(self, metadata: dict) -> dict:
        runtime_state = self._default_runtime_state()
        runtime_state.update(metadata or {})
        runtime_state['last_market_time_by_symbol'] = dict(
            runtime_state.get('last_market_time_by_symbol', {})
        )
        return runtime_state

    def _default_runtime_state(self) -> dict:
        return {
            'last_run_at': None,
            'last_market_time_by_symbol': {},
        }

    def _mark_runtime_tick(self) -> None:
        self.runtime_state['last_run_at'] = datetime.now().isoformat()

    def _record_market_time(self, symbol: str, quote: dict) -> None:
        if not symbol or not isinstance(quote, dict):
            return
        timestamp = quote.get('timestamp') or quote.get('date')
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        if timestamp:
            self.runtime_state.setdefault('last_market_time_by_symbol', {})[symbol] = timestamp

    def _strategy_matches_signal(self, strategy, signal: dict) -> bool:
        symbol = signal.get('symbol')
        if not symbol:
            return False
        related_symbols = set(getattr(strategy, 'etf_pool', []) or [])
        strategy_symbol = getattr(strategy, 'symbol', None)
        if strategy_symbol:
            related_symbols.add(strategy_symbol)
        return symbol in related_symbols

    def run(self):
        self.logger.info("=" * 50)
        self.logger.info("量化助手 Pipeline 启动")
        self.logger.info("=" * 50)

        self.connect()

        self.logger.info("获取宏观分析...")
        macro_analysis = self.macro_analyzer.get_market_analysis()
        self.logger.info(f"市场情绪: {macro_analysis['sentiment']['sentiment']}")
        self.logger.info(f"投资建议: {macro_analysis['recommendation']}")

        if self.state_config.get('restore_on_start', True):
            self.restore_state()

        self.running = True
        self.logger.info("开始运行策略...")

        check_interval = self.config.get('monitor', {}).get('check_interval', 60)

        while self.running:
            try:
                self.run_once()
                time.sleep(check_interval)

            except Exception as e:
                self.logger.error(f"错误: {e}")
                time.sleep(check_interval)

        self.stop()

    def run_once(self):
        """执行一轮行情获取、风控检查、策略信号和监控更新。"""
        self._mark_runtime_tick()

        # 获取所有持仓的实时行情
        current_prices = {}
        for symbol in self.executor.positions:
            quote = self.data_manager.get_etf_realtime(symbol)
            if quote and quote.get('price', 0) > 0:
                current_prices[symbol] = quote['price']
                self._record_market_time(symbol, quote)

        # 获取组合状态（使用实时价格估值）
        portfolio = self.executor.get_portfolio(current_prices)

        # 检查持仓止损
        stop_loss_signals = self.risk_manager.check_portfolio_stop_loss(portfolio)
        for sig in stop_loss_signals:
            order_id = self.order_manager.create_order(sig)
            risk_check = self.risk_manager.check_order(sig, portfolio)
            if risk_check['passed']:
                success = self.executor.execute_order(sig)
                if success:
                    self.order_manager.update_status(order_id, 'filled')
                    for strategy in self.strategy_manager.get_all().values():
                        if (
                            self._strategy_matches_signal(strategy, sig)
                            and hasattr(strategy, 'on_trade_confirmed')
                        ):
                            strategy.on_trade_confirmed(sig)
                    self.logger.info(f"[止损] 执行卖出: {sig['symbol']} {sig.get('price', 0)}")
                else:
                    self.order_manager.update_status(order_id, 'failed')
            else:
                self.order_manager.update_status(order_id, 'rejected')

        # 更新组合状态
        portfolio = self.executor.get_portfolio(current_prices)

        for name, strategy in self.strategy_manager.get_all().items():
            # 获取市场数据
            if hasattr(strategy, 'etf_pool'):
                data = {}
                for symbol in strategy.etf_pool:
                    quote = self.data_manager.get_etf_realtime(symbol)
                    data[symbol] = quote or {}
                    if quote and quote.get('price', 0) > 0:
                        self._record_market_time(symbol, quote)
                    history = self.data_manager.get_etf_history(symbol, '', '')
                    if history:
                        data[symbol]['prices'] = [h.get('close', 0) for h in history]
            else:
                data = self.data_manager.get_etf_realtime(strategy.symbol)
                if data and data.get('price', 0) > 0:
                    self._record_market_time(strategy.symbol, data)

            # 传递 portfolio 给策略
            signals = strategy.generate_signal(data, portfolio)

            for sig in signals:
                order_id = self.order_manager.create_order(sig)
                risk_check = self.risk_manager.check_order(
                    sig, portfolio
                )

                if risk_check['passed']:
                    success = self.executor.execute_order(sig)
                    if success:
                        self.order_manager.update_status(order_id, 'filled')
                        strategy.record_trade(sig)
                        if hasattr(strategy, 'on_trade_confirmed'):
                            strategy.on_trade_confirmed(sig)
                        self.logger.info(
                            f"[{name}] 执行交易: {sig['action']} {sig.get('price', 0)}"
                        )
                    else:
                        self.order_manager.update_status(order_id, 'failed')
                        if hasattr(strategy, 'on_trade_failed'):
                            strategy.on_trade_failed(sig)
                        self.logger.warning(
                            f"[{name}] 执行失败: {sig['action']} {sig.get('price', 0)}"
                        )
                else:
                    self.order_manager.update_status(order_id, 'rejected')
                    if hasattr(strategy, 'on_trade_failed'):
                        strategy.on_trade_failed(sig)
                    self.logger.warning(
                        f"[{name}] 风险检查未通过: {risk_check['checks']}"
                    )

        portfolio = self.executor.get_portfolio(current_prices)
        strategy_summary = self._get_strategy_summary()
        self.monitor.update_metrics(portfolio, strategy_summary)

        return {
            'portfolio': portfolio,
            'strategies': strategy_summary,
            'metrics': self.monitor.get_metrics()
        }

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
        data_health = self._get_data_health()
        if report_type == 'weekly':
            return self.report_generator.generate_weekly_report(
                portfolio,
                strategy_summary,
                data_health,
            )
        return self.report_generator.generate_daily_report(
            portfolio,
            strategy_summary,
            data_health,
        )

    def _get_data_health(self) -> dict:
        try:
            self.data_manager.connect()
            return self.data_manager.health_check()
        finally:
            self.data_manager.disconnect()

    def stop(self):
        self.logger.info("系统停止中...")
        if self.state_config.get('save_on_stop', True):
            try:
                self.save_state()
            except Exception as e:
                self.logger.error(f"状态保存失败: {e}")

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
