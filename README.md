# dropshipping_scraper
messing around with web scraping on bulk sales sites like liquidation.com

## Setup

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```powershell
python webscraper_demo.py --mode browser --headed
```

`--headed` opens a real browser window. Use it if Liquidation.com shows a
manual challenge or blocks headless browser traffic.

## One-Command Pipeline

```powershell
python run_pipeline.py --keywords "unclaimed packages" "amazon returns" "electronics returns" --max-pages 3 --per-page 48
```

This runs the browser scraper, combines and de-duplicates results, scores
profitability, prints a ranked terminal dashboard, and writes:

```text
liquidation_results.csv
liquidation_scored.csv
auction_report.html
```

The pipeline runs with a visible browser by default because Liquidation.com has
blocked headless traffic in testing. To re-score an existing scrape without
opening the browser:

```powershell
python run_pipeline.py --use-existing
```

## Score Auction Profitability

```powershell
python analyze_auctions.py --input liquidation_results.csv --output liquidation_scored.csv
```

The scoring script estimates resale value, final bid, buyer premium, taxes,
shipping, risk buffer, expected profit, ROI, confidence, and a risk-adjusted
opportunity score. The first version uses conservative keyword heuristics, not
live eBay/Amazon sold-comps data.

Key assumptions can be tuned:

```powershell
python analyze_auctions.py --shipping-base 100 --shipping-per-item 2 --buyer-premium-rate 0.11 --tax-rate 0.08
```
