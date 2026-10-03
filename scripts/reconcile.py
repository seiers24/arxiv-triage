#!/usr/bin/env python3
"""Inspect and safely repair schema-2.0 run lifecycle state."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.storage.reconcile import Reconciler  # noqa: E402
from arxiv_triage.storage.sqlite import SQLiteIndex  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("investigation_id")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args(argv)
    index = None
    try:
        db_path = args.db or args.root / "data/triage-v2.db"
        if db_path.is_file():
            index = SQLiteIndex(db_path)
            index.initialize()
        reconciler = Reconciler(args.root, index=index)
        report = reconciler.inspect(args.investigation_id)
        if args.repair:
            reconciler.apply_safe_repairs(report)
            report = reconciler.inspect(args.investigation_id)
        payload = dataclasses.asdict(report)
        payload["clean"] = report.clean
        print(json.dumps(payload))
        return 1 if report.integrity_errors else 0
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if index is not None:
            index.close()


if __name__ == "__main__":
    raise SystemExit(main())
