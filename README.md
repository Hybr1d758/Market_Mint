## Market Mint — Simple OHLCV Fetcher (Beginner Friendly)

This project downloads daily or weekly OHLCV price data from CoinGecko and saves it as CSV files you can use in Power BI (or Excel).

You control what gets fetched using a simple `config.yaml` file. No coding required.

---

### 1) Requirements
- Python 3.11 or newer
- Internet connection
- Git (optional, if you plan to clone the repo)

---

### 2) Get the code
- If you already have the folder locally, skip this.
- Otherwise, clone it:

```bash
git clone https://github.com/Hybr1d758/Market_Mint.git
cd Market_Mint
```

---

### 3) Create a virtual environment and install

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows (PowerShell):
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If activation worked, your prompt will show `(.venv)`.

---

### 4) Configure what to download (edit `config.yaml`)

Open `config.yaml` in any text editor. Here is a beginner-safe example that fetches 90 days of daily data for Gold, Bitcoin, and Ethereum, and writes one CSV per asset:

```yaml
tickers: [gold, bitcoin, ethereum]   # 'gold' is mapped to CoinGecko id 'pax-gold'
vs_currency: usd
date:
  lookback_days: 90                   # Or use start/end: YYYY-MM-DD
frequency: daily                      # daily or weekly
features: false                       # keep false if you just want the raw OHLCV
cache_seconds: 3600                   # helps avoid API rate limits during repeats
output_path: data/{ticker}.csv        # one CSV per asset (e.g., data/bitcoin.csv)
```

Notes:
- You can use either `lookback_days` OR both `start` and `end`:
  ```yaml
  date:
    start: 2024-01-01
    end: 2024-12-31
  ```
- Supported tickers are CoinGecko IDs (e.g., `bitcoin`, `ethereum`). The alias `gold` is automatically mapped to `pax-gold`.

---

### 5) Run the fetcher

From the project folder:
```bash
python coingecko_fetch.py --config config.yaml
```

What you should see:
- Progress printed for each asset
- CSV files saved into the `data/` folder (e.g., `data/bitcoin.csv`, `data/ethereum.csv`, `data/pax-gold.csv`)

CSV columns:
- `date, open, high, low, close, volume`

Optional CLI overrides (advanced, you can skip this):
```bash
# Override tickers and output without editing the file
python coingecko_fetch.py --config config.yaml --tickers bitcoin,ethereum --out data/{ticker}.csv

# Force weekly aggregation
python coingecko_fetch.py --config config.yaml --freq weekly
```

---

### 6) Use in Power BI

Windows (Power BI Desktop):
1. Open Power BI Desktop
2. Get Data → Folder → browse to this repo’s `data/` folder
3. Combine & Transform
4. Add a column to extract the ticker from the file name (e.g., split by `/` and `.`)
5. Make sure data types are correct (`date` = Date, prices/volume = Decimal)
6. Build visuals (line chart for Close, bar/area for Volume). Add a slicer for ticker.

macOS:
- Power BI Desktop is Windows-only. Use Power BI Service (web): put the CSVs in OneDrive/SharePoint and connect from Power BI Service, or run Desktop via a Windows VM/Parallels.

Refreshing data:
- Just run the script again to regenerate CSVs. If files live in OneDrive/SharePoint, you can enable scheduled refresh.

---

### 7) Troubleshooting
- `ModuleNotFoundError` (e.g., `yaml` or `pandas`): make sure your virtual environment is activated and run `pip install -r requirements.txt`.
- Python not found: on macOS/Linux use `python3` instead of `python`.
- Rate limits (`429`): wait a bit and try again; keep `cache_seconds` > 0 to avoid refetching the same range repeatedly during testing.
- SSL/Proxy issues: ensure your network allows HTTPS to `api.coingecko.com`.

---

### 8) (Optional) Schedule automatic runs

macOS/Linux (cron example, runs daily at 06:00):
```cron
0 6 * * * cd /path/to/Market_Mint && source .venv/bin/activate && python coingecko_fetch.py --config config.yaml
```

Windows (Task Scheduler):
1. Create Task → set trigger (daily)
2. Action: `Program/script`: `python`
3. Arguments: `coingecko_fetch.py --config config.yaml`
4. Start in: the project folder path

---

### 9) Continuous Integration (GitHub Actions)
This repo includes a simple workflow at `.github/workflows/ci.yml` that:
- Sets up Python
- Installs dependencies
- Compiles and imports the script (no external API calls)

---

### 10) Project structure
```
Market_Mint/
  coingecko_fetch.py     # main script
  config.yaml            # edit me to choose tickers/date/output
  requirements.txt       # Python dependencies
  data/                  # CSV outputs (kept empty in git via .gitkeep)
  .github/workflows/     # CI config (optional)
  README.md              # this file
```

You’re ready! Edit `config.yaml`, run the command in step 5, and build your visuals in Power BI.


