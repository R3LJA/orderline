"""Command line: ``orderline demo``, ``orderline run`` and ``orderline cost``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .cost import PRICES_PER_MTOK, estimate
from .erp import ErpData
from .extract.mock import MockExtractor
from .mail.folder import FolderMailSource
from .output import CsvSpec, review_status
from .pipeline import BatchResult, run_batch
from .prepare import SeenOrders
from .report import write_report

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orderline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Run the sample inbox offline with replayed model responses.")
    demo.add_argument("--out", default="out")

    run = sub.add_parser("run", help="Process an inbox with Claude.")
    run.add_argument("--source", choices=["folder", "graph"], default="folder")
    run.add_argument("--inbox", default=str(SAMPLES / "inbox"))
    run.add_argument("--erp", default=str(ROOT / "data" / "erp"))
    run.add_argument("--spec", default=str(ROOT / "config" / "columns.yaml"))
    run.add_argument("--out", default="out")
    run.add_argument("--model", default=None)

    cost = sub.add_parser("cost", help="Estimate model cost per 1,000 orders.")
    cost.add_argument("--text-pages", type=int, default=1)
    cost.add_argument("--image-pages", type=int, default=1)
    cost.add_argument("--lines", type=int, default=6)

    args = parser.parse_args(argv)
    if args.command == "demo":
        return _demo(Path(args.out))
    if args.command == "run":
        return _run(args)
    return _cost(args)


def _demo(out: Path) -> int:
    if out.exists():
        shutil.rmtree(out)
    batch = run_batch(
        source=FolderMailSource(SAMPLES / "inbox"),
        erp=ErpData.load(ROOT / "data" / "erp"),
        extractor=MockExtractor(SAMPLES / "mock_responses"),
        spec=CsvSpec.load(ROOT / "config" / "columns.yaml"),
        out_dir=out / "erp-import",
        seen=SeenOrders(out / "state" / "seen.json"),
    )
    report = write_report(batch, out / "erp-import", "replayed mock responses (offline demo)")
    _print_summary(batch, report, mock=True)
    return 0


def _run(args) -> int:
    from .extract.claude import ClaudeExtractor

    if args.source == "graph":
        from .mail.graph import GraphMailSource

        source = GraphMailSource(
            tenant_id=os.environ["GRAPH_TENANT_ID"],
            client_id=os.environ["GRAPH_CLIENT_ID"],
            client_secret=os.environ["GRAPH_CLIENT_SECRET"],
            mailbox=os.environ["GRAPH_MAILBOX"],
            folder=os.getenv("GRAPH_FOLDER", "Inbox"),
        )
    else:
        source = FolderMailSource(args.inbox, state_file=Path(args.out) / "state" / "inbox.json")
    extractor = ClaudeExtractor(model=args.model)
    out = Path(args.out)
    batch = run_batch(
        source=source,
        erp=ErpData.load(args.erp),
        extractor=extractor,
        spec=CsvSpec.load(args.spec),
        out_dir=out / "erp-import",
        seen=SeenOrders(out / "state" / "seen.json"),
    )
    report = write_report(batch, out / "erp-import", f"Claude ({extractor.model})")
    _print_summary(batch, report, mock=False)
    return 0


def _cost(args) -> int:
    print("Estimated model cost per 1,000 orders (first-party API prices; an estimate, measure with `python evals/run_eval.py --yes`)")
    print(f"  pages per order: {args.text_pages} text + {args.image_pages} scanned, {args.lines} lines\n")
    print(f"  {'Model':<20}{'Input tok':>11}{'Output tok':>12}{'Per order':>12}{'Per 1,000':>12}")
    for model in PRICES_PER_MTOK:
        e = estimate(model, args.text_pages, args.image_pages, lines_per_order=args.lines)
        print(f"  {model:<20}{e.input_tokens_per_order:>11,}{e.output_tokens_per_order:>12,}{e.usd_per_order:>12.4f}{e.usd_per_1000:>12.2f}")
    print("\n  Hosting (an Azure Functions app, storage, Key Vault) is billed separately by Azure; there is no per-order fee.")
    return 0


def _print_summary(batch: BatchResult, report: Path, mock: bool) -> None:
    rule = "─" * 96
    print("\nOrderline  emailed purchase orders to ERP-ready CSVs")
    print("Extraction: replayed mock responses, offline. Set ANTHROPIC_API_KEY and run `orderline run` for Claude.\n" if mock else "")
    print("Orders prepared")
    print(rule)
    print(f"  {'Status':<9}{'Customer':<30}{'PO':<14}{'Lines':>6}  {'Mode':<7}  Flags")
    for p in sorted(batch.orders, key=lambda p: ("blocked", "check", "clean").index(review_status(p.order))):
        o = p.order
        codes = ", ".join(sorted({f.code.value for f in o.flags if f.severity.value != "info"})) or "-"
        print(f"  {review_status(o):<9}{(o.customer_name or 'unknown')[:28]:<30}{(o.po_number or 'missing')[:12]:<14}{len(o.lines):>6}  {o.extraction_mode:<7}  {codes}")
    print()
    if batch.skipped:
        print("Skipped as not purchase orders")
        print(rule)
        for s in batch.skipped:
            print(f"  {s.subject[:44]:<46}{s.reason[:64]}")
        print()
    blocked = sum(review_status(p.order) == "blocked" for p in batch.orders)
    check = sum(review_status(p.order) == "check" for p in batch.orders)
    print(f"  {len(batch.orders)} orders, {sum(len(p.order.lines) for p in batch.orders)} lines: "
          f"{len(batch.orders) - blocked - check} clean, {check} to check, {blocked} blocked. Nothing was released.")
    print(f"  CSVs and JSON sidecars: {report.parent}")
    print(f"  Review report: {report}\n")


if __name__ == "__main__":
    sys.exit(main())
