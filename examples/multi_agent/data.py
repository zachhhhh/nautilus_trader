from nautilus_trader.core import Data
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.identifiers import ClientId
from typing import Optional, Dict, Any
from decimal import Decimal
import msgspec

@msgspec.Struct
class SignalData(Data):
    """
    Custom data for research signals.
    """
    instrument_id: InstrumentId
    signal_type: str  # e.g., "BUY", "SELL", "HOLD"
    confidence: float  # 0.0 to 1.0
    reason: str  # Brief explanation
    metadata: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        instrument_id: InstrumentId,
        signal_type: str,
        confidence: float,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> None:
        super().__init__(ts_event=ts_event, ts_init=ts_init)
        self.instrument_id = instrument_id
        self.signal_type = signal_type
        self.confidence = confidence
        self.reason = reason
        self.metadata = metadata or {}

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.value,
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "metadata": self.metadata,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalData":
        return cls(
            instrument_id=InstrumentId.from_str(data["instrument_id"]),
            signal_type=data["signal_type"],
            confidence=data["confidence"],
            reason=data["reason"],
            metadata=data.get("metadata"),
            ts_event=data["ts_event"],
            ts_init=data["ts_init"],
        )


@msgspec.Struct
class BacktestResultData(Data):
    """
    Custom data for backtest results.
    """
    strategy_id: str
    instrument_id: InstrumentId
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[Decimal] = None
    total_return: Optional[Decimal] = None
    trades_count: int = 0
    approved: bool = False  # Whether to deploy live
    metadata: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        strategy_id: str,
        instrument_id: InstrumentId,
        sharpe_ratio: Optional[float] = None,
        max_drawdown: Optional[Decimal] = None,
        total_return: Optional[Decimal] = None,
        trades_count: int = 0,
        approved: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> None:
        super().__init__(ts_event=ts_event, ts_init=ts_init)
        self.strategy_id = strategy_id
        self.instrument_id = instrument_id
        self.sharpe_ratio = sharpe_ratio
        self.max_drawdown = max_drawdown
        self.total_return = total_return
        self.trades_count = trades_count
        self.approved = approved
        self.metadata = metadata or {}

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "instrument_id": self.instrument_id.value,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": str(self.max_drawdown) if self.max_drawdown else None,
            "total_return": str(self.total_return) if self.total_return else None,
            "trades_count": self.trades_count,
            "approved": self.approved,
            "metadata": self.metadata,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BacktestResultData":
        return cls(
            strategy_id=data["strategy_id"],
            instrument_id=InstrumentId.from_str(data["instrument_id"]),
            sharpe_ratio=data.get("sharpe_ratio"),
            max_drawdown=Decimal(data["max_drawdown"]) if data.get("max_drawdown") else None,
            total_return=Decimal(data["total_return"]) if data.get("total_return") else None,
            trades_count=data["trades_count"],
            approved=data["approved"],
            metadata=data.get("metadata"),
            ts_event=data["ts_event"],
            ts_init=data["ts_init"],
        )