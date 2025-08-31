# Market Mint — Feature Engineering Pipeline

Standalone Python CLI and optional Jupyter notebook for CoinGecko-powered OHLCV ingestion and leakage-safe feature engineering.

## Quick start

Install dependencies:

```bash
pip install -r requirements.txt
```

Health check CoinGecko and preview last 30 days:

```bash
python feature_engineering.py --health
```

Run pipeline for BTC/USD with defaults and save outputs in `data/`:

```bash
python feature_engineering.py --coin-id bitcoin --vs usd --start 2020-01-01 --end 2024-12-31 --baseline
```

Key flags:

- `--coin-id` Coin id (e.g., `bitcoin`, `ethereum`)
- `--vs` Quote currency (e.g., `usd`)
- `--start` / `--end` Date range (UTC, `YYYY-MM-DD`)
- `--horizon` Target horizon (days)
- `--short` `--medium` `--long` Feature windows
- `--regression` Use regression target (default is classification)
- `--threshold` Classification threshold (0 for up/down)
- `--baseline` Run a simple baseline if `scikit-learn` is installed
- `--no-save` Do not write CSV outputs

Outputs:

- `data/features.csv` — Engineered features
- `data/target.csv` — Target vector

See `feature_engineering.ipynb` for a step-by-step walkthrough.

## Test run (weekly gold with features)

Fetch last 28 days of PAX Gold (alias: `gold`) in weekly candles and include simple features (SMA/RSI/signals):

```bash
python coingecko_fetch.py --coin-id gold --vs usd --days 28 --freq weekly --features --out data/gold_weekly_features.csv
```

Output CSV columns include: `date, open, high, low, close, volume, pct_change, weekly_return, SMA_4, SMA_12, RSI_14, sma_cross_up, sma_cross_down`.


