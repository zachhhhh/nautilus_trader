from decimal import Decimal
from typing import Dict, Any, Optional
import pandas as pd

from nautilus_trader.config import StrategyConfig, BacktestRunConfig, BacktestDataConfig, BacktestVenueConfig, ImportableStrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.analysis.portfolio import PortfolioAnalyzer

from .data import SignalData, BacktestResultData


class BacktestAgentConfig(StrategyConfig):
    """
    Configuration for BacktestAgent.
    """
    catalog_path: str = "./catalog"  # Path to data catalog
    instrument_id: InstrumentId = InstrumentId.from_str("ETHUSDT-PERP.BINANCE")
    bar_type: BarType = BarType.from_str("ETHUSDT-PERP.BINANCE-15-MINUTE-LAST@BINANCE")
    backtest_period_days: int = 30  # Days of historical data for backtest
    min_sharpe: float = 1.5  # Minimum Sharpe to approve live deployment
    strategy_module: str = "nautilus_trader.examples.strategies.ema_cross"  # Default strategy to test


class BacktestAgent(Strategy):
    """
    Backtest Agent that receives signals, runs backtests using BacktestNode,
    analyzes results, and publishes BacktestResultData.
    Uses historical data from catalog populated by live data client.
    """

    def __init__(self, config: BacktestAgentConfig) -> None:
        super().__init__(config)

        self.catalog_path = config.catalog_path
        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.backtest_period_days = config.backtest_period_days
        self.min_sharpe = config.min_sharpe
        self.strategy_module = config.strategy_module

        self.catalog: Optional[ParquetDataCatalog] = None
        self.analyzer = PortfolioAnalyzer()

    def on_start(self) -> None:
        # Initialize catalog
        self.catalog = ParquetDataCatalog(self.catalog_path)

        # Subscribe to signals
        from .data import SignalData
        self.subscribe_data_type(SignalData)

        self.log.info(f"Backtest Agent started, subscribed to signals for {self.instrument_id}")

    def on_data(self, data: SignalData) -> None:
        if not isinstance(data, SignalData):
            return

        self.log.info(f"Received signal: {data.signal_type} (conf: {data.confidence:.2f}) for {data.instrument_id}")

        if data.instrument_id != self.instrument_id:
            self.log.warning(f"Signal instrument {data.instrument_id} does not match expected {self.instrument_id}")
            return

        # Run backtest based on signal
        result = self._run_backtest(data)
        if result:
            self.publish_data(result)
            self.log.info(f"Published backtest result: approved={result.approved}, sharpe={result.sharpe_ratio}")

    def _run_backtest(self, signal: SignalData) -> Optional[BacktestResultData]:
        try:
            # Calculate time range
            end_time = pd.Timestamp.now(tz="UTC")
            start_time = end_time - pd.Timedelta(days=self.backtest_period_days)

            start_time_ns = start_time.value
            end_time_ns = end_time.value

            # Data config (assume bars are in catalog)
            data_config = BacktestDataConfig(
                catalog_path=str(self.catalog.path),
                data_cls="nautilus_trader.model.data.Bar",
                instrument_id=self.instrument_id,
                bar_type=self.bar_type,
                start_time=start_time_ns,
                end_time=end_time_ns,
            )

            # Venue config (sim for backtest)
            venue_config = BacktestVenueConfig(
                name="SIM",
                oms_type=OmsType.NETTING,
                account_type=AccountType.CASH,
                base_currency="USDT",
                starting_balances=["10000 USDT"],
            )

            # Strategy config based on signal (e.g., adjust EMA periods by confidence)
            fast_period = int(10 / max(signal.confidence, 0.1))  # Shorter EMA for higher confidence
            slow_period = int(20 / max(signal.confidence, 0.1))
            strategy_config = ImportableStrategyConfig(
                strategy_path=f"{self.strategy_module}:EMACross",
                config_path=f"{self.strategy_module}:EMACrossConfig",
                config={
                    "instrument_id": str(self.instrument_id),
                    "bar_type": str(self.bar_type),
                    "fast_ema_period": fast_period,
                    "slow_ema_period": slow_period,
                    "trade_size": Decimal("10"),
                    "order_id_tag": "BACKTEST",
                },
            )

            # Backtest run config
            run_config = BacktestRunConfig(
                name="signal_backtest",
                data=[data_config],
                venues=[venue_config],
                strategies=[strategy_config],
                start_time=start_time_ns,
                end_time=end_time_ns,
            )

            # Run backtest
            node = BacktestNode(configs=[run_config])
            result = node.run()

            if not result:
                self.log.error("Backtest failed to run")
                return None

            # Analyze results
            bt_result = result[0]
            engine = bt_result.engine  # Access the BacktestEngine result

            # Calculate metrics using PortfolioAnalyzer
            pnls = list(engine.portfolio.realized_pnls())
            for pnl in pnls:
                self.analyzer.process(pnl)
            sharpe = self.analyzer.sharpe_ratio.value
            max_dd = self.analyzer.max_drawdown.value
            total_ret = sum(pnl.value for pnl in pnls) if pnls else Decimal("0")

            approved = sharpe >= self.min_sharpe if sharpe is not None else False

            backtest_result = BacktestResultData(
                strategy_id=bt_result.config.name,
                instrument_id=self.instrument_id,
                sharpe_ratio=sharpe,
                max_drawdown=max_dd,
                total_return=total_ret,
                trades_count=len(list(engine.trades.closed_trades())),
                approved=approved,
                metadata={"signal_confidence": signal.confidence, "signal_reason": signal.reason},
                ts_event=self.cache.timestamp_ns(),
                ts_init=self.cache.timestamp_ns(),
            )

            return backtest_result

        except Exception as e:
            self.log.error(f"Backtest failed: {e}")
            return None

    def on_stop(self) -> None:
        self.log.info("Backtest Agent stopped")