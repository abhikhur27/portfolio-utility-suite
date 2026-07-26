#!/usr/bin/env python3
"""Normalize trade-export CSVs into one portable journal schema."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


COLUMN_ALIASES = {
    "date": {"date", "trade date", "filled at", "timestamp", "time", "executed at"},
    "symbol": {"symbol", "ticker", "instrument", "security", "asset"},
    "side": {"side", "action", "type", "instruction"},
    "quantity": {"quantity", "qty", "shares", "filled quantity", "size"},
    "price": {"price", "avg price", "average price", "fill price", "execution price"},
    "fees": {"fees", "fee", "commission", "commissions"},
    "note": {"note", "notes", "description", "memo"},
}

BUY_MARKERS = {"buy", "b", "bot", "bto", "buy to open", "buy to cover"}
SELL_MARKERS = {"sell", "s", "sold", "stc", "sell to close", "sell short", "sto", "sell to open"}


@dataclass
class NormalizedTrade:
    date: str
    symbol: str
    action: str
    quantity: float
    price: float
    fees: float
    signed_quantity: float
    gross_notional: float
    cash_flow: float
    note: str
    source_row: int

    def as_csv_row(self) -> dict[str, str]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": format_number(self.quantity),
            "price": format_number(self.price),
            "fees": format_number(self.fees),
            "signed_quantity": format_number(self.signed_quantity),
            "gross_notional": format_number(self.gross_notional),
            "cash_flow": format_number(self.cash_flow),
            "note": self.note,
            "source_row": str(self.source_row),
        }


@dataclass
class OpenLot:
    date: str
    quantity_remaining: float
    price: float
    fees: float
    original_quantity: float


@dataclass
class MatchedLotRow:
    symbol: str
    sell_date: str
    buy_date: str
    quantity: float
    entry_price: float
    exit_price: float
    holding_days: str
    buy_fees: float
    sell_fees: float
    realized_pnl: float
    status: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "sell_date": self.sell_date,
            "buy_date": self.buy_date,
            "quantity": format_number(self.quantity),
            "entry_price": format_number(self.entry_price),
            "exit_price": format_number(self.exit_price),
            "holding_days": self.holding_days,
            "buy_fees": format_number(self.buy_fees),
            "sell_fees": format_number(self.sell_fees),
            "realized_pnl": format_number(self.realized_pnl),
            "status": self.status,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize trade-export CSVs into a clean journal plus summary JSON."
    )
    parser.add_argument("input_csv", type=Path, help="Path to the raw broker/export CSV.")
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Where to write the normalized CSV. Defaults next to the input file.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Where to write per-symbol and whole-journal summary JSON.",
    )
    parser.add_argument(
        "--position-csv",
        type=Path,
        help="Optional CSV path for per-symbol open-position and basis snapshots.",
    )
    parser.add_argument(
        "--monthly-csv",
        type=Path,
        help="Optional CSV path for monthly trade, fee, and cash-flow rollups.",
    )
    parser.add_argument(
        "--realized-csv",
        type=Path,
        help="Optional CSV path for FIFO matched sell lots and realized PnL.",
    )
    parser.add_argument(
        "--drop-duplicates",
        action="store_true",
        help="Drop exact duplicate normalized rows after parsing.",
    )
    return parser.parse_args()


def normalize_header(header: str) -> str:
    return " ".join(header.strip().lower().replace("_", " ").split())


def find_column(columns: list[str], canonical_name: str) -> str | None:
    aliases = COLUMN_ALIASES[canonical_name]
    for column in columns:
        if normalize_header(column) in aliases:
            return column
    return None


def parse_float(raw: str, *, default: float = 0.0) -> float:
    cleaned = (raw or "").strip().replace(",", "").replace("$", "")
    if not cleaned:
        return default
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return float(cleaned)


def normalize_side(raw_side: str) -> str:
    side = normalize_header(raw_side)
    if side in BUY_MARKERS:
        return "BUY"
    if side in SELL_MARKERS:
        return "SELL"
    raise ValueError(f"Unsupported side/action value: {raw_side!r}")


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def infer_columns(reader: csv.DictReader) -> dict[str, str]:
    if not reader.fieldnames:
        raise ValueError("The CSV is missing a header row.")

    resolved = {}
    missing = []
    for canonical_name in ("date", "symbol", "side", "quantity", "price"):
        column = find_column(reader.fieldnames, canonical_name)
        if column is None:
            missing.append(canonical_name)
        else:
            resolved[canonical_name] = column

    if missing:
        available = ", ".join(reader.fieldnames)
        raise ValueError(
            "Could not infer required columns for "
            f"{', '.join(missing)}. Available headers: {available}"
        )

    resolved["fees"] = find_column(reader.fieldnames, "fees") or ""
    resolved["note"] = find_column(reader.fieldnames, "note") or ""
    return resolved


def normalize_trades(input_csv: Path) -> list[NormalizedTrade]:
    with input_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = infer_columns(reader)
        trades: list[NormalizedTrade] = []
        for row_index, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            action = normalize_side(row[columns["side"]])
            quantity = parse_float(row[columns["quantity"]])
            price = parse_float(row[columns["price"]])
            fees = parse_float(row.get(columns["fees"], ""), default=0.0) if columns["fees"] else 0.0
            signed_quantity = quantity if action == "BUY" else -quantity
            gross_notional = quantity * price
            cash_flow = -gross_notional - fees if action == "BUY" else gross_notional - fees
            trades.append(
                NormalizedTrade(
                    date=(row[columns["date"]] or "").strip(),
                    symbol=(row[columns["symbol"]] or "").strip().upper(),
                    action=action,
                    quantity=quantity,
                    price=price,
                    fees=fees,
                    signed_quantity=signed_quantity,
                    gross_notional=gross_notional,
                    cash_flow=cash_flow,
                    note=(row.get(columns["note"], "") or "").strip() if columns["note"] else "",
                    source_row=row_index,
                )
            )
    return trades


def dedupe_trades(trades: list[NormalizedTrade]) -> list[NormalizedTrade]:
    seen = set()
    unique: list[NormalizedTrade] = []
    for trade in trades:
        key = (
            trade.date,
            trade.symbol,
            trade.action,
            trade.quantity,
            trade.price,
            trade.fees,
            trade.note,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(trade)
    return unique


def build_summary(trades: list[NormalizedTrade]) -> dict[str, object]:
    by_symbol: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "trades": 0,
            "buy_quantity": 0.0,
            "sell_quantity": 0.0,
            "gross_notional": 0.0,
            "fees": 0.0,
            "net_cash_flow": 0.0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
        }
    )
    total_fees = 0.0
    total_notional = 0.0
    total_cash_flow = 0.0

    for trade in trades:
        bucket = by_symbol[trade.symbol]
        bucket["trades"] += 1
        if trade.action == "BUY":
            bucket["buy_quantity"] += trade.quantity
        else:
            bucket["sell_quantity"] += trade.quantity
        bucket["gross_notional"] += trade.gross_notional
        bucket["fees"] += trade.fees
        bucket["net_cash_flow"] += trade.cash_flow
        if trade.action == "BUY":
            bucket["buy_notional"] += trade.gross_notional
        else:
            bucket["sell_notional"] += trade.gross_notional
        total_fees += trade.fees
        total_notional += trade.gross_notional
        total_cash_flow += trade.cash_flow

    position_rows = []
    symbol_summary = {}
    for symbol, stats in sorted(by_symbol.items()):
        buy_quantity = float(stats["buy_quantity"])
        sell_quantity = float(stats["sell_quantity"])
        buy_notional = float(stats["buy_notional"])
        sell_notional = float(stats["sell_notional"])
        net_quantity = round(buy_quantity - sell_quantity, 4)
        avg_buy_price = round(buy_notional / buy_quantity, 4) if buy_quantity else 0.0
        avg_sell_price = round(sell_notional / sell_quantity, 4) if sell_quantity else 0.0
        row = {
            "trades": int(stats["trades"]),
            "buy_quantity": round(buy_quantity, 4),
            "sell_quantity": round(sell_quantity, 4),
            "net_quantity": net_quantity,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "gross_notional": round(float(stats["gross_notional"]), 4),
            "fees": round(float(stats["fees"]), 4),
            "net_cash_flow": round(float(stats["net_cash_flow"]), 4),
        }
        symbol_summary[symbol] = row
        position_rows.append({"symbol": symbol, **row})

    return {
        "trade_count": len(trades),
        "symbols": symbol_summary,
        "positions": position_rows,
        "monthly": build_monthly_rows(trades),
        "journal_totals": {
            "fees": round(total_fees, 4),
            "gross_notional": round(total_notional, 4),
            "net_cash_flow": round(total_cash_flow, 4),
        },
    }


def month_bucket(date_text: str) -> str:
    stripped = date_text.strip()
    if len(stripped) >= 7 and stripped[4] == "-":
        return stripped[:7]
    if len(stripped) >= 7 and stripped[2] == "/" and stripped[5] == "/":
        month, _, year = stripped.split("/", 2)
        return f"{year[:4]}-{month.zfill(2)}"
    return stripped[:7] if len(stripped) >= 7 else stripped


def build_monthly_rows(trades: list[NormalizedTrade]) -> list[dict[str, object]]:
    by_month: dict[str, dict[str, float | int | set[str]]] = defaultdict(
        lambda: {
            "trades": 0,
            "buy_quantity": 0.0,
            "sell_quantity": 0.0,
            "gross_notional": 0.0,
            "fees": 0.0,
            "net_cash_flow": 0.0,
            "symbols": set(),
        }
    )

    for trade in trades:
        bucket = by_month[month_bucket(trade.date)]
        bucket["trades"] += 1
        if trade.action == "BUY":
            bucket["buy_quantity"] += trade.quantity
        else:
            bucket["sell_quantity"] += trade.quantity
        bucket["gross_notional"] += trade.gross_notional
        bucket["fees"] += trade.fees
        bucket["net_cash_flow"] += trade.cash_flow
        bucket["symbols"].add(trade.symbol)

    rows = []
    for month in sorted(by_month):
        bucket = by_month[month]
        rows.append(
            {
                "month": month,
                "trades": int(bucket["trades"]),
                "symbols": len(bucket["symbols"]),
                "buy_quantity": round(float(bucket["buy_quantity"]), 4),
                "sell_quantity": round(float(bucket["sell_quantity"]), 4),
                "gross_notional": round(float(bucket["gross_notional"]), 4),
                "fees": round(float(bucket["fees"]), 4),
                "net_cash_flow": round(float(bucket["net_cash_flow"]), 4),
            }
        )
    return rows


def parse_iso_like_date(date_text: str) -> str:
    return date_text.strip().replace("/", "-")


def holding_days_between(buy_date: str, sell_date: str) -> str:
    try:
        buy = parse_iso_like_date(buy_date)
        sell = parse_iso_like_date(sell_date)
        from datetime import date

        buy_parts = [int(part) for part in buy.split("-")]
        sell_parts = [int(part) for part in sell.split("-")]
        if len(buy_parts) == 3 and len(sell_parts) == 3:
            return str((date(*sell_parts) - date(*buy_parts)).days)
    except ValueError:
        return ""
    return ""


def build_realized_rows(trades: list[NormalizedTrade]) -> list[MatchedLotRow]:
    inventory: dict[str, deque[OpenLot]] = defaultdict(deque)
    realized_rows: list[MatchedLotRow] = []

    for trade in trades:
        if trade.action == "BUY":
            inventory[trade.symbol].append(
                OpenLot(
                    date=trade.date,
                    quantity_remaining=trade.quantity,
                    price=trade.price,
                    fees=trade.fees,
                    original_quantity=trade.quantity,
                )
            )
            continue

        remaining_sell_qty = trade.quantity
        while remaining_sell_qty > 0 and inventory[trade.symbol]:
            lot = inventory[trade.symbol][0]
            matched_quantity = min(remaining_sell_qty, lot.quantity_remaining)
            buy_fee_share = lot.fees * (matched_quantity / lot.original_quantity) if lot.original_quantity else 0.0
            sell_fee_share = trade.fees * (matched_quantity / trade.quantity) if trade.quantity else 0.0
            realized_pnl = (trade.price - lot.price) * matched_quantity - buy_fee_share - sell_fee_share
            realized_rows.append(
                MatchedLotRow(
                    symbol=trade.symbol,
                    sell_date=trade.date,
                    buy_date=lot.date,
                    quantity=matched_quantity,
                    entry_price=lot.price,
                    exit_price=trade.price,
                    holding_days=holding_days_between(lot.date, trade.date),
                    buy_fees=buy_fee_share,
                    sell_fees=sell_fee_share,
                    realized_pnl=realized_pnl,
                    status="matched",
                )
            )
            lot.quantity_remaining -= matched_quantity
            remaining_sell_qty -= matched_quantity
            if lot.quantity_remaining <= 1e-9:
                inventory[trade.symbol].popleft()

        if remaining_sell_qty > 1e-9:
            sell_fee_share = trade.fees * (remaining_sell_qty / trade.quantity) if trade.quantity else 0.0
            realized_rows.append(
                MatchedLotRow(
                    symbol=trade.symbol,
                    sell_date=trade.date,
                    buy_date="",
                    quantity=remaining_sell_qty,
                    entry_price=0.0,
                    exit_price=trade.price,
                    holding_days="",
                    buy_fees=0.0,
                    sell_fees=sell_fee_share,
                    realized_pnl=0.0,
                    status="unmatched_sell",
                )
            )

    return realized_rows


def write_position_csv(path: Path, positions: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "trades",
        "buy_quantity",
        "sell_quantity",
        "net_quantity",
        "avg_buy_price",
        "avg_sell_price",
        "gross_notional",
        "fees",
        "net_cash_flow",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(positions)


def write_monthly_csv(path: Path, monthly_rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "month",
        "trades",
        "symbols",
        "buy_quantity",
        "sell_quantity",
        "gross_notional",
        "fees",
        "net_cash_flow",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(monthly_rows)


def write_realized_csv(path: Path, realized_rows: list[MatchedLotRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "sell_date",
        "buy_date",
        "quantity",
        "entry_price",
        "exit_price",
        "holding_days",
        "buy_fees",
        "sell_fees",
        "realized_pnl",
        "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in realized_rows:
            writer.writerow(row.as_csv_row())


def write_normalized_csv(path: Path, trades: list[NormalizedTrade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "symbol",
        "action",
        "quantity",
        "price",
        "fees",
        "signed_quantity",
        "gross_notional",
        "cash_flow",
        "note",
        "source_row",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.as_csv_row())


def main() -> int:
    args = parse_args()
    if not args.input_csv.exists():
        print(f"Input file not found: {args.input_csv}", file=sys.stderr)
        return 1

    try:
        trades = normalize_trades(args.input_csv)
        if args.drop_duplicates:
            trades = dedupe_trades(trades)
        if not trades:
            raise ValueError("No trade rows were parsed from the input file.")
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"Normalization failed: {exc}", file=sys.stderr)
        return 1

    output_csv = args.output_csv or args.input_csv.with_name(f"{args.input_csv.stem}.normalized.csv")
    summary_json = args.summary_json or args.input_csv.with_name(f"{args.input_csv.stem}.summary.json")
    summary_payload = build_summary(trades)
    write_normalized_csv(output_csv, trades)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    if args.position_csv:
        write_position_csv(args.position_csv, summary_payload["positions"])
    if args.monthly_csv:
        write_monthly_csv(args.monthly_csv, summary_payload["monthly"])
    if args.realized_csv:
        write_realized_csv(args.realized_csv, build_realized_rows(trades))

    print(f"Normalized {len(trades)} trades into {output_csv}")
    print(f"Wrote summary JSON to {summary_json}")
    if args.position_csv:
        print(f"Wrote position CSV to {args.position_csv}")
    if args.monthly_csv:
        print(f"Wrote monthly CSV to {args.monthly_csv}")
    if args.realized_csv:
        print(f"Wrote realized-lot CSV to {args.realized_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
