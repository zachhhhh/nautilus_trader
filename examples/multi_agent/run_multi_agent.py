"""
Run script for the multi-agent trading system.
Sets up a TradingNode with ResearchAgent, BacktestAgent, and TradingAgent.
Uses a simulated venue for initial testing; extend to live clients as needed.
"""

import os
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

from nautilus_trader.model import Venue, Symbol, Price, Quantity
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from nautilus_trader.config import (
    TradingNodeConfig,
    CacheConfig,
    ExecEngineConfig,
    TradingNode,
)
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.model import Venue, Currency, Money
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.adapters.binance.config import (
    BinanceDataClientConfig,
    BinanceExecClientConfig,
)

# Assuming data catalog is set up; for demo, use in-memory or local
CATALOG_PATH = Path("./catalog")

# Configurations
cache_config = CacheConfig()

exec_config = ExecEngineConfig(
    load_cache=True,
    bypass=True,  # For sim fallback
)

# Binance configs for testnet
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

use_live = bool(api_key and secret_key)

if use_live:
    from nautilus_trader.adapters.binance.config import (
        BinanceDataClientConfig,
        BinanceExecClientConfig,
    )
    binance_data_config = BinanceDataClientConfig(
        api_key=api_key,
        api_secret=secret_key,
        testnet=True,
    )
    binance_exec_config = BinanceExecClientConfig(
        api_key=api_key,
        api_secret=secret_key,
        testnet=True,
        account_type=AccountType.MARGIN,
    )
else:
    # Fallback to sim
    from nautilus_trader.adapters.sim import SimExecutorConfig
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model import Currency, Money
    binance_data_config = None
    binance_exec_config = SimExecutorConfig(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=Currency.from_str("USDT"),
        starting_balances=[Money(10_000, Currency.from_str("USDT"))],
    )
    print("No Binance API keys found, falling back to simulation mode for testing.")

# Strategy configurations
research_config = ImportableStrategyConfig(
    strategy_path="examples.multi_agent.research_agent:ResearchAgent",
    config_path="examples.multi_agent.research_agent:ResearchAgentConfig",
    config={
        "instrument_id": "ETHUSDT-PERP.BINANCE",
        "bar_type": "ETHUSDT-PERP.BINANCE-15-MINUTE-LAST@BINANCE",
        "fast_ema_period": 10,
        "slow_ema_period": 20,
        "research_interval": 15,
        "order_id_tag": "RESEARCH",
        "api_key": os.getenv("ALPHA_VANTAGE_API_KEY", "demo"),  # Placeholder
    },
)

backtest_config = ImportableStrategyConfig(
    strategy_path="examples.multi_agent.backtest_agent:BacktestAgent",
    config_path="examples.multi_agent.backtest_agent:BacktestAgentConfig",
    config={
        "catalog_path": str(CATALOG_PATH),
        "instrument_id": "ETHUSDT-PERP.BINANCE",
        "bar_type": "ETHUSDT-PERP.BINANCE-15-MINUTE-LAST@BINANCE",
        "backtest_period_days": 30,
        "min_sharpe": 1.5,
        "strategy_module": "nautilus_trader.examples.strategies.ema_cross",
        "order_id_tag": "BACKTEST",
    },
)

trading_config = ImportableStrategyConfig(
    strategy_path="examples.multi_agent.trading_agent:TradingAgent",
    config_path="examples.multi_agent.trading_agent:TradingAgentConfig",
    config={
        "instrument_id": "ETHUSDT-PERP.BINANCE",
        "trade_size": "0.01",
        "max_position_size": "0.1",
        "venue": "BINANCE",
        "order_id_tag": "TRADING",
    },
)

# Node configuration
node_config = TradingNodeConfig(
    trader_id="MULTI_AGENT-001",
    log_level="INFO",
    cache=cache_config,
    exec_engine=exec_config,
    data_clients={"BINANCE": binance_data_config} if use_live else {},
    exec_clients={"BINANCE": binance_exec_config} if use_live else {"SIM": binance_exec_config},
    strategies=[research_config, backtest_config, trading_config],
)

def main():
    # Ensure catalog exists (create if not)
    if not CATALOG_PATH.exists():
        CATALOG_PATH.mkdir(parents=True)
        print(f"Created catalog directory: {CATALOG_PATH}")

    catalog = ParquetDataCatalog(CATALOG_PATH)

    # For live, instrument will be loaded from data client
    # Optionally add instrument manually if needed for backtests
    instrument_id = InstrumentId.from_str("ETHUSDT-PERP.BINANCE")
    if not catalog.instruments():
        from nautilus_trader.model.instruments.crypto import CryptoPerpetual
        from decimal import Decimal
        instrument = CryptoPerpetual(
            instrument_id=instrument_id,
            base_increment=Quantity.from_str("0.001"),
            quote_increment=Price.from_str("0.01"),
            price_precision=2,
            size_precision=3,
            ts_event=0,
            ts_init=0,
            maker_fee="0.0002",
            taker_fee="0.0004",
            settlement_currency=Currency.from_str("USDT"),
            max_quantity=Quantity.from_str("10000"),
            max_notional=Quantity.from_str("1000000"),
            max_leverage=Decimal("125"),
            margin_init=Decimal("0.01"),
            margin_maint=Decimal("0.005"),
        )
        catalog.write_instrument(instrument)
        print("Added instrument to catalog")

    # For backtests, you may want to load historical data from Binance or external source
    # For now, skip sample bars as live data will be used

    # Prompt for live mode confirmation (only if keys available)
    if use_live:
        confirm = input("Enable live investing mode? (yes/no): ").strip().lower()
        if confirm == 'yes':
            print("Running in live mode with Binance testnet.")
            live_mode = True
        else:
            print("Running in paper trading mode (simulated executions).")
            live_mode = False
            # Override to sim
            node_config.data_clients = {}
            node_config.exec_clients = {"SIM": binance_exec_config}
    else:
        live_mode = False
        print("Running in simulation mode (no API keys).")

    # Run the node
    node = TradingNode(config=node_config)
    node.run()

if __name__ == "__main__":
    main()