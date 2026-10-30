"""Measure extraction accuracy and token cost with the real model on the sample set.

    ANTHROPIC_API_KEY=... python evals/run_eval.py --yes

This calls the API once per sample PDF (12 calls) and costs real money, so it refuses to run
without --yes. It prints field-level accuracy per document, measured tokens, and the cost per
1,000 orders computed from those measured tokens, and saves the run to evals/results/.

The sample set is synthetic and small. Treat the number as a smoke test of the pipeline, and
re-run it on a few hundred of your own past orders before trusting it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orderline.cost import PRICES_PER_MTOK, estimate, measured_cost  # noqa: E402
from orderline.evaluate import score_order  # noqa: E402
from orderline.extract.base import Usage  # noqa: E402
from orderline.extract.claude import ClaudeExtractor  # noqa: E402
from orderline.pages import prepare_pdf  # noqa: E402

SAMPLES = ROOT / "data" / "samples"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="really call the API")
    parser.add_argument("--model", default=os.getenv("ORDERLINE_MODEL", "claude-opus-5-5"))
    args = parser.parse_args()

    truths = sorted((SAMPLES / "truth").glob("*.json"))
    if not args.yes:
        est = estimate(args.model) if args.model in PRICES_PER_MTOK else None
        guess = f" (roughly ${est.usd_per_order * len(truths):.2f} for this run)" if est else ""
        print(f"This sends {len(truths)} documents to {args.model}{guess}. Re-run with --yes to proceed.")
        return 1
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_FOUNDRY_API_KEY")):
        print("Set ANTHROPIC_API_KEY (or the Foundry variables) first.")
        return 1

    extractor = ClaudeExtractor(model=args.model)
    usage, rows, correct, total = Usage(), [], 0, 0
    for path in truths:
        truth = json.loads(path.read_text())
        doc = prepare_pdf((SAMPLES / "pdf" / truth["file"]).read_bytes(), truth["file"])
        result = extractor.extract(doc)
        usage.add(result.usage)
        if result.order is None:
            rows.append({"file": truth["file"], "accuracy": 0.0, "misses": [f"no extraction: {result.decline_reason}"]})
            continue
        s = score_order(result.order, truth)
        correct, total = correct + s.correct, total + s.total
        rows.append({"file": truth["file"], "mode": result.mode, "accuracy": round(s.accuracy, 4), "misses": s.misses,
                     "input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens})
        print(f"  {truth['file']:<44} {s.accuracy:>7.1%}  {result.mode:<7} {len(s.misses)} misses")

    overall = correct / total if total else 0.0
    per_1000 = measured_cost(args.model, usage.input_tokens, usage.output_tokens, len(truths)) if args.model in PRICES_PER_MTOK else None
    print(f"\n  Field accuracy: {overall:.1%} ({correct}/{total} fields)")
    print(f"  Tokens: {usage.input_tokens:,} in, {usage.output_tokens:,} out")
    if per_1000 is not None:
        print(f"  Measured cost: ${per_1000:.2f} per 1,000 orders like these")

    out = ROOT / "evals" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.model}.json"
    out.write_text(json.dumps({"model": args.model, "field_accuracy": overall, "usd_per_1000": per_1000,
                               "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                               "documents": rows}, indent=2))
    print(f"  Saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
