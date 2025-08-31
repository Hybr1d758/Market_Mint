import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
try:
	import requests_cache as _requests_cache
except Exception:
	_requests_cache = None

try:
	import yaml  # YAML configuration support
except Exception:
	yaml = None


COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_SESSION = None  # lazily-initialized requests.Session with retries


def to_unix(date_str: str) -> int:
	"""Convert a YYYY-MM-DD date string to a UTC Unix timestamp (seconds)."""
	# Parse with UTC timezone to avoid local-time ambiguity
	return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def fetch_market_chart_range(coin_id: str, vs_currency: str, from_ts: int, to_ts: int) -> dict:
	"""Call CoinGecko market_chart/range.

	Parameters:
	- coin_id: Coin id string on CoinGecko (e.g., "bitcoin")
	- vs_currency: Quote currency (e.g., "usd")
	- from_ts: Start time in Unix seconds (UTC)
	- to_ts: End time in Unix seconds (UTC)

	Returns: API JSON with keys: prices, market_caps, total_volumes
	Raises: HTTPError if request fails
	"""
	url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
	params = {"vs_currency": vs_currency, "from": from_ts, "to": to_ts}

	# Use a single session with retries/backoff and a polite User-Agent
	global _SESSION
	if _SESSION is None:
		_SESSION = requests.Session()
		_SESSION.headers.update({
			"User-Agent": "MarketMint/1.0 (+https://github.com/your/repo; contact: you@example.com)",
		})
		retry = Retry(
			total=5,
			backoff_factor=1.5,
			status_forcelist=[429, 500, 502, 503, 504],
			allowed_methods=["GET"],
		)
		adapter = HTTPAdapter(max_retries=retry)
		_SESSION.mount("https://", adapter)
		_SESSION.mount("http://", adapter)

	r = _SESSION.get(url, params=params, timeout=60)
	r.raise_for_status()
	return r.json()


def fetch_range_chunked(coin_id: str, vs_currency: str, from_ts: int, to_ts: int, chunk_days: int, sleep_seconds: float) -> dict:
	"""Fetch a long range by splitting into smaller date windows and merging results.

	Returns a dict with combined 'prices' and 'total_volumes' lists compatible with to_daily_ohlcv.
	"""
	seconds_per_day = 86400
	chunk_seconds = max(1, int(chunk_days * seconds_per_day))
	cur_start = from_ts
	all_prices = []
	all_vols = []
	while cur_start < to_ts:
		cur_end = min(cur_start + chunk_seconds, to_ts)
		resp = fetch_market_chart_range(coin_id, vs_currency, cur_start, cur_end)
		all_prices.extend(resp.get("prices", []))
		all_vols.extend(resp.get("total_volumes", []))
		cur_start = cur_end
		if cur_start < to_ts and sleep_seconds > 0:
			time.sleep(sleep_seconds)
	return {"prices": all_prices, "total_volumes": all_vols}


def fetch_market_chart_days(coin_id: str, vs_currency: str, days: str | int) -> dict:
	"""Fetch using CoinGecko market_chart with a days parameter (int or 'max')."""
	global _SESSION
	if _SESSION is None:
		_SESSION = requests.Session()
		_SESSION.headers.update({
			"User-Agent": "MarketMint/1.0 (+https://github.com/your/repo; contact: you@example.com)",
		})
		retry = Retry(
			total=5,
			backoff_factor=1.5,
			status_forcelist=[429, 500, 502, 503, 504],
			allowed_methods=["GET"],
		)
		adapter = HTTPAdapter(max_retries=retry)
		_SESSION.mount("https://", adapter)
		_SESSION.mount("http://", adapter)

	url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
	params = {"vs_currency": vs_currency, "days": days}
	r = _SESSION.get(url, params=params, timeout=60)
	r.raise_for_status()
	return r.json()


def to_daily_ohlcv(data: dict) -> pd.DataFrame:
	"""Convert CoinGecko market_chart JSON into a daily OHLCV DataFrame.

	Input format:
	- data["prices"]: list[[ms_timestamp, price], ...]
	- data["total_volumes"]: list[[ms_timestamp, volume], ...]

	Output columns:
	- date (datetime), open, high, low, close, volume
	"""
	prices = pd.DataFrame(data.get("prices", []), columns=["ms", "price"]).set_index("ms")
	volumes = pd.DataFrame(data.get("total_volumes", []), columns=["ms", "volume"]).set_index("ms")
	if prices.empty:
		return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
	# Convert ms timestamps to timezone-naive datetime in local calendar (UTC → naive)
	prices.index = pd.to_datetime(prices.index, unit="ms", utc=True).tz_convert(None)
	if not volumes.empty:
		volumes.index = pd.to_datetime(volumes.index, unit="ms", utc=True).tz_convert(None)
	else:
		volumes = pd.DataFrame(index=prices.index, data={"volume": 0.0})

	# Resample to daily bars: open, high, low, close
	ohlc = prices["price"].resample("1D").agg(["first", "max", "min", "last"]).rename(columns={"first": "open", "max": "high", "min": "low", "last": "close"})
	vol = volumes["volume"].resample("1D").sum()
	df = ohlc.join(vol.rename("volume"), how="left")
	df = df.dropna(subset=["close"]).reset_index()
	# After reset_index, the index column name may be 'ms' (from original index) or 'index' (if unnamed)
	if "ms" in df.columns:
		df = df.rename(columns={"ms": "date"})
	else:
		df = df.rename(columns={"index": "date"})
	return df


def _load_yaml_config(path: str) -> dict:
	"""Load YAML config if available, else return empty dict.

	Supported keys:
	- tickers: list[str]
	- vs_currency: str
	- date: { lookback_days: int } or { start: YYYY-MM-DD, end: YYYY-MM-DD }
	- frequency: "daily" | "weekly"
	- features: bool
	- cache_seconds: int
	- output_path: str
	"""
	if not path or not os.path.exists(path):
		return {}
	if yaml is None:
		raise RuntimeError("pyyaml is required to load YAML config, but not installed")
	with open(path, "r") as f:
		cfg = yaml.safe_load(f) or {}
	return cfg


def _effective_output_path(base_path: str, ticker: str, multi: bool) -> str:
	"""Resolve output path for a given ticker.

	If multiple tickers:
	- If base_path contains '{ticker}', format it.
	- Else if base_path is a directory or endswith '/', write '<dir>/<ticker>.csv'.
	- Else append '_<ticker>' before extension.
	"""
	if not multi:
		return base_path

	# Multiple tickers
	if "{ticker}" in base_path:
		return base_path.format(ticker=ticker)
	# Directory case
	if base_path.endswith(os.sep) or (os.path.exists(base_path) and os.path.isdir(base_path)):
		return os.path.join(base_path, f"{ticker}.csv")
	# Append suffix
	root, ext = os.path.splitext(base_path)
	if not ext:
		ext = ".csv"
	return f"{root}_{ticker}{ext}"


def main() -> int:
	"""Parse CLI args, load YAML config, fetch data, convert to OHLCV, and save CSV."""
	parser = argparse.ArgumentParser(description="Fetch OHLCV from CoinGecko and save CSV (daily/weekly)")
	parser.add_argument("--config", default="config.yaml", help="Path to YAML config file")
	# CLI overrides (optional; if omitted, YAML values are used)
	parser.add_argument("--coin-id", help="Single coin id (overrides tickers)")
	parser.add_argument("--tickers", help="Comma-separated list of coin ids (e.g., bitcoin,ethereum)")
	parser.add_argument("--vs", help="Quote currency, e.g., usd")
	parser.add_argument("--days", type=int, help="Lookback window in days")
	parser.add_argument("--start", help="Start date YYYY-MM-DD (UTC)")
	parser.add_argument("--end", help="End date YYYY-MM-DD (UTC)")
	parser.add_argument("--freq", choices=["daily", "weekly"], help="Output frequency")
	parser.add_argument("--features", action="store_true", help="Add analytics columns (SMA/RSI and signals)")
	parser.add_argument("--cache-seconds", type=int, help="Enable HTTP cache with TTL seconds (0 to disable)")
	parser.add_argument("--out", help="Output CSV path or directory; use {ticker} to template filename for multi-ticker")
	args = parser.parse_args()

	cfg = _load_yaml_config(args.config)

	# Determine tickers
	tickers: list[str]
	if args.coin_id:
		tickers = [args.coin_id]
	elif args.tickers:
		tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
	else:
		tickers = cfg.get("tickers") or ["pax-gold"]

	# Normalize alias for 'gold'
	def _normalize_coin(c: str) -> str:
		c = c.lower()
		return "pax-gold" if c in {"gold", "xau", "xauusd", "xau-usd"} else c
	
	tickers = [_normalize_coin(t) for t in tickers]

	vs = args.vs or cfg.get("vs_currency", "usd")
	freq = args.freq or cfg.get("frequency", "daily")
	features = bool(args.features) if args.features else bool(cfg.get("features", False))
	cache_seconds = args.cache_seconds if args.cache_seconds is not None else int(cfg.get("cache_seconds", 3600))
	out_path = args.out or cfg.get("output_path", "data/ohlcv.csv")

	# Optional HTTP caching to reduce API calls during development
	if _requests_cache is not None and cache_seconds > 0:
		_requests_cache.install_cache("coingecko_cache", expire_after=cache_seconds)

	# Resolve time range
	date_cfg = cfg.get("date", {}) if isinstance(cfg.get("date"), dict) else {}
	start_str = args.start or date_cfg.get("start")
	end_str = args.end or date_cfg.get("end")
	lookback_days = args.days if args.days is not None else date_cfg.get("lookback_days")

	if start_str and end_str:
		from_ts = to_unix(start_str)
		to_ts = to_unix(end_str)
	else:
		# Compute recent window using lookback_days (default 30)
		if lookback_days is None:
			lookback_days = 30
		now = datetime.now(tz=timezone.utc)
		from_ts = int((now - timedelta(days=int(lookback_days))).timestamp())
		to_ts = int(now.timestamp())

	multi = len(tickers) > 1
	all_outputs = []
	for coin_id in tickers:
		print(f"Fetching {coin_id.upper()} / {vs.upper()} from {from_ts} to {to_ts} ...")
		data = fetch_market_chart_range(coin_id, vs, from_ts, to_ts)
		df = to_daily_ohlcv(data)

		# weekly aggregation
		if freq == "weekly":
			# Week ending Sunday; aggregate OHLCV
			df = (
				df.set_index("date").resample("W-SUN").agg({
					"open": "first",
					"high": "max",
					"low": "min",
					"close": "last",
					"volume": "sum",
				}).dropna(subset=["close"]).reset_index()
			)

		# analytics features
		if features:
			# Compute on the chosen frequency (daily or weekly). Names assume weekly use-case.
			# Period return
			df["pct_change"] = df["close"].pct_change()
			if freq == "weekly":
				df["weekly_return"] = df["close"].pct_change()

			# Simple moving averages (4 and 12 periods)
			df["SMA_4"] = df["close"].rolling(window=4, min_periods=4).mean()
			df["SMA_12"] = df["close"].rolling(window=12, min_periods=12).mean()

			# RSI 14-period on close
			def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
				chg = prices.diff()
				gain = chg.clip(lower=0.0)
				loss = (-chg).clip(lower=0.0)
				avg_gain = gain.rolling(period, min_periods=period).mean()
				avg_loss = loss.rolling(period, min_periods=period).mean()
				rs = avg_gain / (avg_loss + 1e-12)
				return 100 - (100 / (1 + rs))

			df["RSI_14"] = _rsi(df["close"], 14)

			# Signals: SMA crossover
			prev_fast = df["SMA_4"].shift(1)
			prev_slow = df["SMA_12"].shift(1)
			cross_up = (df["SMA_4"] > df["SMA_12"]) & (prev_fast <= prev_slow)
			cross_dn = (df["SMA_4"] < df["SMA_12"]) & (prev_fast >= prev_slow)
			df["sma_cross_up"] = cross_up.astype(int)
			df["sma_cross_down"] = cross_dn.astype(int)

		print("Rows:", len(df))
		print(df.head().to_string(index=False))

		# Ensure output directory exists and write CSV
		resolved_out = _effective_output_path(out_path, coin_id, multi)
		os.makedirs(os.path.dirname(resolved_out) or ".", exist_ok=True)
		df.to_csv(resolved_out, index=False)
		print("Saved:", resolved_out)
		all_outputs.append(resolved_out)

	return 0


if __name__ == "__main__":
	sys.exit(main())


# ===== Import-friendly helpers =====

def fetch_ohlcv_df(coin_id: str = "pax-gold", vs: str = "usd", days: int = 28, freq: str = "weekly", features: bool = True) -> pd.DataFrame:
	"""Programmatic API: fetch OHLCV and optionally add simple features.

	Parameters:
	- coin_id: e.g., "pax-gold" or "bitcoin"
	- vs: e.g., "usd"
	- days: lookback window in days
	- freq: "daily" or "weekly" (weekly aggregates to week-ending Sunday)
	- features: if True, adds pct_change, SMA_4/12, RSI_14, crossover signals

	Returns: pandas DataFrame with columns [date, open, high, low, close, volume, ...]
	"""
	# Alias handling for gold
	coin = coin_id.lower()
	if coin in {"gold", "xau", "xauusd", "xau-usd"}:
		coin = "pax-gold"

	# Enable default caching for programmatic use if available (1 hour TTL)
	if _requests_cache is not None:
		_requests_cache.install_cache("coingecko_cache", expire_after=3600)

	now = datetime.now(tz=timezone.utc)
	from_ts = int((now - timedelta(days=days)).timestamp())
	to_ts = int(now.timestamp())

	data = fetch_market_chart_range(coin, vs, from_ts, to_ts)
	df = to_daily_ohlcv(data)

	if freq == "weekly":
		df = (
			df.set_index("date").resample("W-SUN").agg({
				"open": "first",
				"high": "max",
				"low": "min",
				"close": "last",
				"volume": "sum",
			}).dropna(subset=["close"]).reset_index()
		)

	if features:
		df["pct_change"] = df["close"].pct_change()
		if freq == "weekly":
			df["weekly_return"] = df["close"].pct_change()
		df["SMA_4"] = df["close"].rolling(window=4, min_periods=4).mean()
		df["SMA_12"] = df["close"].rolling(window=12, min_periods=12).mean()
		def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
			chg = prices.diff()
			gain = chg.clip(lower=0.0)
			loss = (-chg).clip(lower=0.0)
			avg_gain = gain.rolling(period, min_periods=period).mean()
			avg_loss = loss.rolling(period, min_periods=period).mean()
			rs = avg_gain / (avg_loss + 1e-12)
			return 100 - (100 / (1 + rs))
		df["RSI_14"] = _rsi(df["close"], 14)
		prev_fast = df["SMA_4"].shift(1)
		prev_slow = df["SMA_12"].shift(1)
		cross_up = (df["SMA_4"] > df["SMA_12"]) & (prev_fast <= prev_slow)
		cross_dn = (df["SMA_4"] < df["SMA_12"]) & (prev_fast >= prev_slow)
		df["sma_cross_up"] = cross_up.astype(int)
		df["sma_cross_down"] = cross_dn.astype(int)

	return df


def fetch_weekly_gold_features(days: int = 28) -> pd.DataFrame:
	"""Shortcut: weekly PAX Gold features for the past `days` days."""
	return fetch_ohlcv_df(coin_id="pax-gold", vs="usd", days=days, freq="weekly", features=True)


