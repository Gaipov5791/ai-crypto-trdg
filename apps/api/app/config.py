from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_API_DIR = Path(__file__).resolve().parents[1]
_ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "CryptoAI Trader"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    starting_balance: float = 10_000.0
    taker_fee: float = 0.0005
    slippage: float = 0.0002
    max_risk_per_trade: float = 0.015
    max_daily_drawdown: float = 0.03
    signal_timeframe: str = "5m"
    chart_timeframe: str = "1m"
    binance_rest: str = "https://api.binance.com"
    binance_ws: str = "wss://stream.binance.com:443/stream"
    db_path: str = "paper.db"
    boot_binance: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CRYPTOAI_",
        env_file=(_API_DIR / ".env", _ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
