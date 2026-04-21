import argparse
import csv
import html
import textwrap
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from analyze_auctions import score_row, write_rows
from webscraper_demo import ScraperRequestError, save_to_csv, scrape_keyword_browser


DEFAULT_KEYWORDS = ["unclaimed packages", "amazon returns", "electronics returns"]


def parse_keywords(values):
    keywords = []
    for value in values:
        keywords.extend(part.strip() for part in value.split(","))
    return [keyword for keyword in keywords if keyword]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dedupe_rows(rows):
    seen = set()
    unique_rows = []
    for row in rows:
        key = row.get("url") or "|".join(
            [
                row.get("title", ""),
                row.get("current_bid", ""),
                row.get("closing", ""),
                row.get("seller", ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def scrape_keywords(args, raw_output):
    all_rows = []
    for keyword in args.keywords:
        print(f"\nScraping keyword: {keyword!r}")
        rows = scrape_keyword_browser(
            keyword=keyword,
            max_pages=args.max_pages,
            per_page=args.per_page,
            delay_seconds=args.delay_seconds,
            headless=args.headless,
            sort=args.sort,
        )
        print(f"Found {len(rows)} rows for {keyword!r}")
        for row in rows:
            row["search_keyword"] = keyword
        all_rows.extend(rows)

    all_rows = dedupe_rows(all_rows)
    save_to_csv(all_rows, filename=raw_output)
    return all_rows


def score_rows(rows, args):
    analyzer_args = SimpleNamespace(
        buyer_premium_rate=args.buyer_premium_rate,
        tax_rate=args.tax_rate,
        shipping_base=args.shipping_base,
        shipping_per_item=args.shipping_per_item,
        risk_buffer_rate=args.risk_buffer_rate,
        default_condition_multiplier=args.default_condition_multiplier,
    )
    now = datetime.now()
    scored_rows = [score_row(row, analyzer_args, now=now) for row in rows]
    scored_rows.sort(
        key=lambda row: (
            float(row["opportunity_score"]),
            float(row["roi"]),
            float(row["expected_profit"]),
        ),
        reverse=True,
    )
    return scored_rows


def truncate(text, max_width):
    text = str(text or "")
    if len(text) <= max_width:
        return text
    return text[: max_width - 3] + "..."


def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def percent(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def print_dashboard(scored_rows, args, raw_output, scored_output, report_output):
    if not scored_rows:
        print("\nNo scored rows to display.")
        return

    profitable_rows = [row for row in scored_rows if float(row["expected_profit"]) > 0]
    avg_roi = sum(float(row["roi"]) for row in scored_rows) / len(scored_rows)
    best = scored_rows[0]

    print("\nAuction Pipeline Summary")
    print("=" * 80)
    print(f"Rows scored:       {len(scored_rows)}")
    print(f"Profitable rows:  {len(profitable_rows)}")
    print(f"Average ROI:      {avg_roi * 100:.1f}%")
    print(f"Best score:       {best['opportunity_score']}")
    print(f"Raw CSV:          {raw_output}")
    print(f"Scored CSV:       {scored_output}")
    print(f"HTML report:      {report_output}")

    print(f"\nTop {min(args.top, len(scored_rows))} Opportunities")
    print("-" * 80)
    header = f"{'#':>2} {'Score':>7} {'ROI':>8} {'Profit':>11} {'Cost':>10} {'Title':<38}"
    print(header)
    print("-" * len(header))
    for index, row in enumerate(scored_rows[: args.top], start=1):
        print(
            f"{index:>2} "
            f"{float(row['opportunity_score']):>7.2f} "
            f"{percent(row['roi']):>8} "
            f"{money(row['expected_profit']):>11} "
            f"{money(row['total_cost']):>10} "
            f"{truncate(row.get('title'), 38):<38}"
        )

    print("\nUse the HTML report for clickable auction links and more detail.")


def render_report(scored_rows, args, raw_output, scored_output):
    generated_at = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    keywords = ", ".join(args.keywords)
    rows_html = []

    for row in scored_rows[: args.report_limit]:
        profit = float(row["expected_profit"])
        profit_class = "positive" if profit >= 0 else "negative"
        title = html.escape(str(row.get("title", "")))
        url = html.escape(str(row.get("url", "")))
        seller = html.escape(str(row.get("seller", "")))
        keyword = html.escape(str(row.get("search_keyword", "")))
        rows_html.append(
            f"""
            <tr>
              <td class="score">{float(row['opportunity_score']):.2f}</td>
              <td><a href="{url}" target="_blank" rel="noreferrer">{title}</a></td>
              <td>{html.escape(str(row.get('condition', '')))}</td>
              <td>{html.escape(str(row.get('qty', '')))}</td>
              <td>{money(row.get('expected_profit'))}</td>
              <td>{percent(row.get('roi'))}</td>
              <td>{money(row.get('total_cost'))}</td>
              <td>{money(row.get('estimated_resale'))}</td>
              <td>{row.get('confidence_score')}</td>
              <td class="{profit_class}">{'Profit' if profit >= 0 else 'Loss'}</td>
              <td>{seller}</td>
              <td>{keyword}</td>
            </tr>
            """
        )

    profitable_count = sum(1 for row in scored_rows if float(row["expected_profit"]) > 0)
    avg_roi = (
        sum(float(row["roi"]) for row in scored_rows) / len(scored_rows)
        if scored_rows
        else 0
    )
    best_score = scored_rows[0]["opportunity_score"] if scored_rows else "0"

    return textwrap.dedent(
        f"""\
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Liquidation Auction Report</title>
          <style>
            :root {{
              color-scheme: light;
              --ink: #17202a;
              --muted: #5d6d7e;
              --line: #d7dde5;
              --panel: #f7f9fb;
              --positive: #0d7a4f;
              --negative: #b42318;
              --accent: #1b5f9e;
            }}
            body {{
              margin: 0;
              font-family: Arial, Helvetica, sans-serif;
              color: var(--ink);
              background: white;
            }}
            main {{
              max-width: 1200px;
              margin: 0 auto;
              padding: 28px 20px 44px;
            }}
            h1 {{
              margin: 0 0 6px;
              font-size: 28px;
            }}
            .meta {{
              color: var(--muted);
              margin-bottom: 22px;
            }}
            .metrics {{
              display: grid;
              grid-template-columns: repeat(4, minmax(0, 1fr));
              gap: 12px;
              margin-bottom: 24px;
            }}
            .metric {{
              background: var(--panel);
              border: 1px solid var(--line);
              border-radius: 8px;
              padding: 14px;
            }}
            .metric strong {{
              display: block;
              font-size: 22px;
              margin-bottom: 4px;
            }}
            .metric span {{
              color: var(--muted);
              font-size: 13px;
            }}
            table {{
              width: 100%;
              border-collapse: collapse;
              font-size: 14px;
            }}
            th, td {{
              border-bottom: 1px solid var(--line);
              padding: 10px 8px;
              text-align: left;
              vertical-align: top;
            }}
            th {{
              background: var(--panel);
              position: sticky;
              top: 0;
            }}
            a {{
              color: var(--accent);
              text-decoration: none;
            }}
            a:hover {{
              text-decoration: underline;
            }}
            .score {{
              font-weight: 700;
            }}
            .positive {{
              color: var(--positive);
              font-weight: 700;
            }}
            .negative {{
              color: var(--negative);
              font-weight: 700;
            }}
            .notes {{
              margin-top: 18px;
              color: var(--muted);
              font-size: 13px;
              line-height: 1.45;
            }}
            @media (max-width: 800px) {{
              .metrics {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
              }}
              table {{
                display: block;
                overflow-x: auto;
                white-space: nowrap;
              }}
            }}
          </style>
        </head>
        <body>
          <main>
            <h1>Liquidation Auction Report</h1>
            <div class="meta">
              Generated {generated_at} for keywords: {html.escape(keywords)}
            </div>

            <section class="metrics">
              <div class="metric"><strong>{len(scored_rows)}</strong><span>Rows scored</span></div>
              <div class="metric"><strong>{profitable_count}</strong><span>Estimated profitable</span></div>
              <div class="metric"><strong>{avg_roi * 100:.1f}%</strong><span>Average ROI</span></div>
              <div class="metric"><strong>{best_score}</strong><span>Best opportunity score</span></div>
            </section>

            <table>
              <thead>
                <tr>
                  <th>Score</th>
                  <th>Auction</th>
                  <th>Condition</th>
                  <th>Qty</th>
                  <th>Profit</th>
                  <th>ROI</th>
                  <th>Total Cost</th>
                  <th>Resale Est.</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th>Seller</th>
                  <th>Keyword</th>
                </tr>
              </thead>
              <tbody>
                {''.join(rows_html)}
              </tbody>
            </table>

            <p class="notes">
              Raw CSV: {html.escape(str(raw_output))}<br>
              Scored CSV: {html.escape(str(scored_output))}<br>
              Scores are heuristic estimates. Verify manifests, shipping quotes,
              seller history, and sold comps before bidding.
            </p>
          </main>
        </body>
        </html>
        """
    )


def write_report(path, scored_rows, args, raw_output, scored_output):
    report_html = render_report(scored_rows, args, raw_output, scored_output)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"Saved HTML report to {path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape Liquidation.com results, score profitability, and generate a report."
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help="Search keywords. Accepts repeated values or comma-separated text.",
    )
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--per-page", type=int, default=48)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--sort", default="relevance")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless. Liquidation.com may return 403 in this mode.",
    )
    parser.add_argument(
        "--use-existing",
        action="store_true",
        help="Skip scraping and score the existing raw CSV.",
    )
    parser.add_argument("--raw-output", default="liquidation_results.csv")
    parser.add_argument("--scored-output", default="liquidation_scored.csv")
    parser.add_argument("--report-output", default="auction_report.html")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--report-limit", type=int, default=100)
    parser.add_argument("--buyer-premium-rate", type=float, default=0.11)
    parser.add_argument("--tax-rate", type=float, default=0.08)
    parser.add_argument("--shipping-base", type=float, default=75.0)
    parser.add_argument("--shipping-per-item", type=float, default=1.5)
    parser.add_argument("--risk-buffer-rate", type=float, default=0.12)
    parser.add_argument("--default-condition-multiplier", type=float, default=0.45)
    args = parser.parse_args()
    args.keywords = parse_keywords(args.keywords)
    if not args.keywords:
        parser.error("At least one keyword is required.")
    return args


def main():
    args = parse_args()
    raw_output = Path(args.raw_output)
    scored_output = Path(args.scored_output)
    report_output = Path(args.report_output)

    try:
        if args.use_existing:
            print(f"Using existing raw CSV: {raw_output}")
            rows = read_csv(raw_output)
        else:
            rows = scrape_keywords(args, raw_output)
    except ScraperRequestError as exc:
        print(f"Pipeline failed during scraping: {exc}")
        return 1

    if not rows:
        print("No auction rows found. Nothing to score.")
        return 1

    scored_rows = score_rows(rows, args)
    write_rows(scored_output, scored_rows)
    write_report(report_output, scored_rows, args, raw_output, scored_output)
    print_dashboard(scored_rows, args, raw_output, scored_output, report_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
