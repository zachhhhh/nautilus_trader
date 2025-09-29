from decimal import Decimal
from typing import Dict, Any, Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy

from .data import BacktestResultData


class TradingAgentConfig(StrategyConfig):
    """
    Configuration for TradingAgent.
    """
    instrument_id: InstrumentId = InstrumentId.from_str("ETHUSDT-PERP.BINANCE")
    trade_size: Decimal = Decimal("0.01")  # ETH quantity
    max_position_size: Decimal = Decimal("0.1")  # Max exposure
    venue: str = "BINANCE"  # Execution venue
    max_daily_loss: Decimal = Decimal("500")  # Max daily loss in USDT


class TradingAgent(Strategy):
    """
    Trading Agent that receives backtest results and deploys live trades if approved.
    Subscribes to BacktestResultData, checks approval, and executes orders.
    Manages positions to avoid over-exposure and basic risk controls (max daily loss).
    """

    def __init__(self, config: TradingAgentConfig) -> None:
        super().__init__(config)

        self.instrument_id = config.instrument_id
        self.trade_size = config.trade_size
        self.max_position_size = config.max_position_size
        self.venue = config.venue
        self.max_daily_loss = config.max_daily_loss

        self.current_position = Decimal("0")
        self.active_strategy_params = None  # From backtest metadata
        self.daily_pnl = Decimal("0")
        self.current_day = None
        self.trading_stopped = False

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument {self.instrument_id}")
            self.stop()
            return

        # Subscribe to backtest results
        from .data import BacktestResultData
        self.subscribe_data_type(BacktestResultData)

        # Initialize daily tracking
        self._update_daily_reset()

        self.log.info(f"Trading Agent started for {self.instrument_id} on {self.venue}")

    def on_data(self, data: BacktestResultData) -> None:
        if not isinstance(data, BacktestResultData):
            return

        self.log.info(f"Received backtest result: approved={data.approved}, sharpe={data.sharpe_ratio} for {data.instrument_id}")

        if data.instrument_id != self.instrument_id:
            self.log.warning(f"Backtest instrument {data.instrument_id} does not match expected {self.instrument_id}")
            return

        if not data.approved:
            self.log.info("Backtest not approved, skipping live trade")
            return

        # Deploy live trade based on backtest
        self._execute_trade(data)

    def _execute_trade(self, result: BacktestResultData) -> None:
        if self.trading_stopped:
            self.log.warning("Trading stopped due to daily loss limit")
            return

        # Get current position
        position = self.cache.position_for_instrument(self.instrument_id)
        self.current_position = position.net_qty.as_decimal() if position else Decimal("0")

        if abs(self.current_position) >= self.max_position_size:
            self.log.warning("Max position size reached, skipping trade")
            return

        # Check daily loss
        if self.daily_pnl <= -self.max_daily_loss:
            self._stop_trading()
            return

        # Determine side based on strategy (simplified: assume BUY for positive return)
        if result.total_return and result.total_return > 0:
            side = OrderSide.BUY
            reason = "Approved backtest with positive return"
        else:
            side = OrderSide.SELL
            reason = "Approved backtest with negative return (reduce)"

        # Adjust quantity based on position
        qty = self.trade_size if side == OrderSide.BUY else min(self.trade_size, abs(self.current_position))

        # Create market order
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(qty),
            time_in_force=TimeInForce.GTC,
        )

        self.submit_order(order)
        self.log.info(f"Submitted {side} order for {qty} {self.instrument_id.symbol} based on approved backtest")

        # Store params for ongoing management (e.g., from metadata)
        self.active_strategy_params = result.metadata

    def on_order_filled(self, event) -> None:
        # Update position tracking
        position = self.cache.position_for_instrument(self.instrument_id)
        if position:
            self.current_position = position.net_qty.as_decimal()
            self.log.info(f"Position updated: {self.current_position} {self.instrument_id.symbol}")

        # Update daily PnL on fills
        self._update_daily_pnl()
        if self.daily_pnl <= -self.max_daily_loss:
            self._stop_trading()

    def on_position_changed(self, event) -> None:
        self.log.info(f"Position changed: {event.position.net_qty} {self.instrument_id.symbol}")

        # Update daily PnL on position changes
        self._update_daily_pnl()
        if self.daily_pnl <= -self.max_daily_loss:
            self._stop_trading()

    def on_position_closed(self, event) -> None:
        self.current_position = Decimal("0")
        self.log.info(f"Position closed for {self.instrument_id.symbol}")

        # Update daily PnL on close
        self._update_daily_pnl()
        if self.daily_pnl <= -self.max_daily_loss:
            self._stop_trading()

    def on_stop(self) -> None:
        # Cancel all orders on stop
        self.cancel_all_orders()
        self.log.info("Trading Agent stopped, all orders canceled")

    def _update_daily_reset(self):
        today = self.cache.timestamp_ns() // (24 * 60 * 60 * 10**9)  # Daily timestamp
        if self.current_day != today:
            self.daily_pnl = Decimal("0")
            self.current_day = today
            self.trading_stopped = False
            self.log.info("Daily PnL reset")

    def _update_daily_pnl(self):
        self._update_daily_reset()
        # Get realized PnL for the day (simplified: use portfolio realized PnL)
        portfolio = self.cache.portfolio()
        if portfolio:
            # Approximate daily PnL from realized PnLs (in real, filter by day)
            realized_pnls = list(portfolio.realized_pnls())
            if realized_pnls:
                self.daily_pnl = sum(pnl.value for pnl in realized_pnls[-10:])  # Last few for approx
                self.log.debug(f"Updated daily PnL: {self.daily_pnl}")

    def _stop_trading(self):
        if not self.trading_stopped:
            self.trading_stopped = True
            self.cancel_all_orders()
            self.log.warning(f"Trading stopped: Daily loss limit {self.max_daily_loss} reached. Current PnL: {self.daily_pnl}")