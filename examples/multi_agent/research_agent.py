from decimal import Decimal
from typing import Dict, Any, Optional
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from .data import SignalData


class ResearchAgentConfig(StrategyConfig):
    """
    Configuration for ResearchAgent.
    """
    instrument_id: InstrumentId = InstrumentId.from_str("ETHUSDT-PERP.BINANCE")
    bar_type: BarType = BarType.from_str("ETHUSDT-PERP.BINANCE-15-MINUTE-LAST@BINANCE")
    fast_ema_period: int = 10
    slow_ema_period: int = 20
    research_interval: int = 15  # Minutes between research cycles
    api_key: Optional[str] = None  # Alpha Vantage API key


class ResearchAgent(Strategy):
    """
    Research Agent that analyzes market data and generates trading signals.
    Subscribes to bars, performs simple analysis (EMA cross + external news sentiment),
    and publishes SignalData.
    """

    def __init__(self, config: ResearchAgentConfig) -> None:
        super().__init__(config)

        # Custom state
        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.fast_ema_period = config.fast_ema_period
        self.slow_ema_period = config.slow_ema_period
        self.research_interval = config.research_interval
        self.api_key = config.api_key

        self.fast_ema = None  # Will be initialized in on_start
        self.slow_ema = None
        self.sentiment_analyzer = SentimentIntensityAnalyzer()
        self.current_sentiment = 0.0  # -1 to 1, neutral 0
        self.last_research_time = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument {self.instrument_id}")
            self.stop()
            return

        # Initialize EMAs
        from nautilus_trader.indicators.ema import ExponentialMovingAverage
        self.fast_ema = ExponentialMovingAverage(self.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(self.slow_ema_period)

        # Register indicators for bar updates
        self.register_indicator_for_bars(self.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.bar_type, self.slow_ema)

        # Request historical data to warm up indicators
        self.request_bars(self.bar_type)

        # Subscribe to live bars
        self.subscribe_bars(self.bar_type)

        # Set timer for periodic research (e.g., news fetch)
        self.clock.set_timer(
            name="research_timer",
            interval=Decimal(self.research_interval * 60),  # Seconds
        )

        self.log.info(f"Research Agent started for {self.instrument_id}")

    def on_bar(self, bar: Bar) -> None:
        # Simple EMA cross signal generation
        if self.fast_ema.value is None or self.slow_ema.value is None:
            return

        current_fast = self.fast_ema.value
        current_slow = self.slow_ema.value
        prev_fast = self.fast_ema.value_at_offset(1)
        prev_slow = self.slow_ema.value_at_offset(1)

        if prev_fast <= prev_slow and current_fast > current_slow:
            # Bullish cross
            signal_type = "BUY"
            confidence = min(0.8, abs(current_fast - current_slow) / current_slow)
            reason = "EMA fast cross above slow"
        elif prev_fast >= prev_slow and current_fast < current_slow:
            # Bearish cross
            signal_type = "SELL"
            confidence = min(0.8, abs(current_fast - current_slow) / current_slow)
            reason = "EMA fast cross below slow"
        else:
            signal_type = "HOLD"
            confidence = 0.5
            reason = "No clear signal"

        # Adjust confidence with sentiment
        adjusted_confidence = confidence * (0.5 + (self.current_sentiment + 1) / 2)  # Scale sentiment -1 to 1 to 0-1 boost
        adjusted_confidence = min(1.0, max(0.0, adjusted_confidence))

        reason += f" (sentiment: {self.current_sentiment:.2f})"

        # Publish signal
        signal = SignalData(
            instrument_id=self.instrument_id,
            signal_type=signal_type,
            confidence=adjusted_confidence,
            reason=reason,
            ts_event=bar.ts_event,
            ts_init=self.cache.timestamp_ns(),
        )
        self.publish_data(signal)

        self.log.info(f"Published signal: {signal_type} (conf: {adjusted_confidence:.2f}) for {bar.close}")

    def on_timer(self, event) -> None:
        if event.name == "research_timer":
            self.log.info("Performing external research (Alpha Vantage news + VADER sentiment)...")
            try:
                # Fetch news from Alpha Vantage
                url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=ETH&apikey={self.api_key}&limit=10"
                response = requests.get(url, timeout=10)
                data = response.json()
    
                if "feed" in data and data["feed"]:
                    # Use VADER on titles or use built-in sentiment if available
                    sentiments = []
                    for article in data["feed"]:
                        title = article.get("title", "")
                        score = self.sentiment_analyzer.polarity_scores(title)
                        sentiments.append(score["compound"])  # -1 to 1
    
                    if sentiments:
                        self.current_sentiment = sum(sentiments) / len(sentiments)
                        self.log.info(f"Updated sentiment score: {self.current_sentiment:.2f} from {len(sentiments)} articles")
                    else:
                        self.current_sentiment = 0.0
                else:
                    # Fallback to keyword-based simple sentiment
                    self._simple_sentiment_analysis()
                    self.log.warning("No news feed, using simple keyword analysis")
    
            except Exception as e:
                self.log.error(f"Error in research: {e}")
                self.current_sentiment = 0.0
    
    def _simple_sentiment_analysis(self):
        # Simple keyword-based for ETH news simulation
        positive_keywords = ["bullish", "rise", "gain", "positive", "uptrend"]
        negative_keywords = ["bearish", "fall", "loss", "negative", "downtrend"]
        # Simulate fetching some text, for demo
        sample_text = "ETH price is showing bullish signs with potential gains."
        pos_count = sum(1 for word in positive_keywords if word in sample_text.lower())
        neg_count = sum(1 for word in negative_keywords if word in sample_text.lower())
        self.current_sentiment = (pos_count - neg_count) / max(pos_count + neg_count, 1)
        self.log.info(f"Simple sentiment: {self.current_sentiment:.2f}")

    def on_stop(self) -> None:
        self.unsubscribe_bars(self.bar_type)
        self.log.info("Research Agent stopped")