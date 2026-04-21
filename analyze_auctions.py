import argparse
import csv
import math
import re
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_INPUT = "liquidation_results.csv"
DEFAULT_OUTPUT = "liquidation_scored.csv"

CONDITION_MULTIPLIERS = {
    "new": 0.85,
    "like new": 0.75,
    "used": 0.6,
    "returns": 0.45,
    "refurbished": 0.55,
    "shelf pulls": 0.55,
    "scratch and dent": 0.35,
    "damaged": 0.25,
    "salvage": 0.15,
}

BASE_RESALE_BY_KEYWORD = [
    (("airpods", "headphones", "earbuds"), 45.0),
    (("iphone", "ipad", "macbook", "laptop"), 125.0),
    (("tv", "monitor"), 90.0),
    (("tool", "drill", "saw"), 55.0),
    (("appliance", "ninja", "keurig", "vacuum"), 45.0),
    (("jewelry", "watch"), 35.0),
    (("cosmetic", "health", "beauty"), 12.0),
    (("apparel", "clothing", "shoes"), 18.0),
    (("furniture",), 60.0),
    (("package", "packages", "lost mail", "undelivered post", "mystery"), 20.0),
]

LOW_CONFIDENCE_KEYWORDS = (
    "mystery",
    "unclaimed",
    "undelivered",
    "lost mail",
    "returns",
    "uninspected",
)

HIGH_CONFIDENCE_KEYWORDS = (
    "tested",
    "retail ready",
    "new",
    "manifested",
    "exact photos",
)


def parse_money(value):
    text = str(value or "").strip()
    if not text:
        return 0.0
    text = text.replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_int(value, default=0):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else default


def parse_closing(value, now=None):
    now = now or datetime.now()
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.lower() == "closed":
        return None

    match = re.match(r"Today\s+(\d{1,2}):(\d{2})(AM|PM)", text, re.IGNORECASE)
    if match:
        hour, minute, meridian = match.groups()
        hour = int(hour)
        if meridian.upper() == "PM" and hour != 12:
            hour += 12
        if meridian.upper() == "AM" and hour == 12:
            hour = 0
        return now.replace(hour=hour, minute=int(minute), second=0, microsecond=0)

    match = re.match(
        r"([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{1,2}):(\d{2})(AM|PM)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    month_name, day, hour, minute, meridian = match.groups()
    month = datetime.strptime(month_name[:3].title(), "%b").month
    hour = int(hour)
    if meridian.upper() == "PM" and hour != 12:
        hour += 12
    if meridian.upper() == "AM" and hour == 12:
        hour = 0

    closing = datetime(now.year, month, int(day), hour, int(minute))
    if closing < now - timedelta(days=30):
        closing = closing.replace(year=now.year + 1)
    return closing


def hours_until_close(closing_text, now=None):
    closing = parse_closing(closing_text, now=now)
    if closing is None:
        return None
    return max((closing - (now or datetime.now())).total_seconds() / 3600, 0.0)


def final_bid_multiplier(hours_remaining, bid_count):
    if hours_remaining is None:
        base = 1.35
    elif hours_remaining <= 2:
        base = 1.08
    elif hours_remaining <= 8:
        base = 1.18
    elif hours_remaining <= 24:
        base = 1.3
    else:
        base = 1.45

    if bid_count >= 8:
        base += 0.12
    elif bid_count >= 3:
        base += 0.06
    elif bid_count == 0:
        base -= 0.05

    return max(base, 1.05)


def estimate_base_resale_per_item(title):
    title_lower = str(title or "").lower()
    for keywords, value in BASE_RESALE_BY_KEYWORD:
        if any(keyword in title_lower for keyword in keywords):
            return value
    return 25.0


def confidence_score(row):
    title = str(row.get("title", "")).lower()
    condition = str(row.get("condition", "")).lower()
    qty = parse_int(row.get("qty"), default=1)

    score = 0.55
    if any(keyword in title for keyword in HIGH_CONFIDENCE_KEYWORDS):
        score += 0.12
    if any(keyword in title for keyword in LOW_CONFIDENCE_KEYWORDS):
        score -= 0.15
    if condition in {"new", "like new", "retail ready"}:
        score += 0.1
    if condition in {"returns", "damaged", "salvage"}:
        score -= 0.12
    if qty >= 25:
        score -= 0.05
    return min(max(score, 0.2), 0.95)


def risk_score(row, confidence):
    condition = str(row.get("condition", "")).lower()
    title = str(row.get("title", "")).lower()
    risk = 1.0 + (1.0 - confidence)
    if condition in {"returns", "damaged", "salvage"}:
        risk += 0.35
    if any(keyword in title for keyword in LOW_CONFIDENCE_KEYWORDS):
        risk += 0.25
    return round(risk, 3)


def score_row(row, args, now=None):
    now = now or datetime.now()
    current_bid = parse_money(row.get("current_bid"))
    bid_count = parse_int(row.get("bid_count"))
    qty = max(parse_int(row.get("qty"), default=1), 1)
    condition = str(row.get("condition", "")).strip().lower()
    hours_remaining = hours_until_close(row.get("closing"), now=now)
    bid_multiplier = final_bid_multiplier(hours_remaining, bid_count)
    expected_final_bid = current_bid * bid_multiplier

    condition_multiplier = CONDITION_MULTIPLIERS.get(condition, args.default_condition_multiplier)
    base_resale_per_item = estimate_base_resale_per_item(row.get("title"))
    estimated_raw_resale = base_resale_per_item * qty
    estimated_resale = estimated_raw_resale * condition_multiplier

    buyer_premium = expected_final_bid * args.buyer_premium_rate
    taxes = (expected_final_bid + buyer_premium) * args.tax_rate
    shipping = args.shipping_base + (qty * args.shipping_per_item)
    handling_buffer = estimated_resale * args.risk_buffer_rate
    total_cost = expected_final_bid + buyer_premium + taxes + shipping + handling_buffer
    expected_profit = estimated_resale - total_cost
    roi = expected_profit / total_cost if total_cost else 0.0
    confidence = confidence_score(row)
    risk = risk_score(row, confidence)
    opportunity_score = (roi * 100 * confidence) / risk

    enriched = dict(row)
    enriched.update(
        {
            "base_resale_per_item": round(base_resale_per_item, 2),
            "condition_multiplier": round(condition_multiplier, 3),
            "estimated_resale": round(estimated_resale, 2),
            "expected_final_bid": round(expected_final_bid, 2),
            "bid_multiplier": round(bid_multiplier, 3),
            "estimated_shipping": round(shipping, 2),
            "buyer_premium": round(buyer_premium, 2),
            "estimated_taxes": round(taxes, 2),
            "risk_buffer": round(handling_buffer, 2),
            "total_cost": round(total_cost, 2),
            "expected_profit": round(expected_profit, 2),
            "roi": round(roi, 4),
            "confidence_score": round(confidence, 3),
            "risk_score": risk,
            "opportunity_score": round(opportunity_score, 3),
            "hours_until_close": (
                round(hours_remaining, 2) if hours_remaining is not None else ""
            ),
        }
    )
    return enriched


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    if not rows:
        print("No rows to write.")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} scored rows to {path}")


def print_summary(rows, limit):
    print("\nTop opportunities by score:")
    for index, row in enumerate(rows[:limit], start=1):
        roi_percent = float(row["roi"]) * 100
        print(
            f"{index}. score={row['opportunity_score']} "
            f"roi={roi_percent:.1f}% "
            f"profit=${row['expected_profit']} "
            f"cost=${row['total_cost']} "
            f"title={row.get('title', '')}"
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Score Liquidation.com auction CSV rows for estimated profitability."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--buyer-premium-rate", type=float, default=0.11)
    parser.add_argument("--tax-rate", type=float, default=0.08)
    parser.add_argument("--shipping-base", type=float, default=75.0)
    parser.add_argument("--shipping-per-item", type=float, default=1.5)
    parser.add_argument("--risk-buffer-rate", type=float, default=0.12)
    parser.add_argument("--default-condition-multiplier", type=float, default=0.45)
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    rows = read_rows(input_path)
    if not rows:
        print(f"No rows found in {input_path}")
        return 1

    now = datetime.now()
    scored_rows = [score_row(row, args, now=now) for row in rows]
    scored_rows.sort(
        key=lambda row: (
            float(row["opportunity_score"]),
            float(row["roi"]),
            float(row["expected_profit"]),
        ),
        reverse=True,
    )

    write_rows(output_path, scored_rows)
    print_summary(scored_rows, args.top)

    if any(not math.isfinite(float(row["roi"])) for row in scored_rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
