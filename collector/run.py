"""CLI entry point for the USDA grain data collection pipeline.

Usage:
    python -m collector.run --source all --since 2010
    python -m collector.run --source weekly          # cron: every Monday
    python -m collector.run --source monthly         # cron: 15th of each month
    python -m collector.run --source gtr
    python -m collector.run --source quickstats --since 2020
    python -m collector.run --source wasde --force
    python -m collector.run --source wwcb
    python -m collector.run --source wasde_pdf --since 2024
    python -m collector.run --source psd --since 2015
    python -m collector.run --source ers_feedgrains
    python -m collector.run --source export_sales --since 2020
    python -m collector.run --source wwcb_images

Schedule groups:
    weekly  : gtr, quickstats, export_sales, wwcb, wwcb_images
    monthly : wasde, psd, ers_feedgrains, wasde_pdf
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from common import manifest
from common.storage import ensure_dirs

load_dotenv()

SOURCES = {
    "gtr": ("collector.m1_structured.gtr", "GTR xlsx", "weekly"),
    "quickstats": ("collector.m1_structured.quickstats", "NASS QuickStats API", "weekly"),
    "wasde": ("collector.m1_structured.wasde", "WASDE CSV", "monthly"),
    "psd": ("collector.m1_structured.psd", "FAS PSD bulk CSV", "monthly"),
    "ers_feedgrains": ("collector.m1_structured.ers_feedgrains", "ERS Feed Grains CSV", "monthly"),
    "export_sales": ("collector.m1_structured.export_sales", "FAS Export Sales API", "weekly"),
    "wwcb": ("collector.m2_reports.wwcb", "WWCB PDF", "weekly"),
    "wasde_pdf": ("collector.m2_reports.wasde_pdf", "WASDE PDF archive", "monthly"),
    "wwcb_images": ("collector.m3_images.wwcb_images", "WWCB image extraction", "weekly"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="USDA Grain Data Collection Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", "-s",
        choices=list(SOURCES.keys()) + ["all", "structured", "reports", "weekly", "monthly"],
        default="all",
        help="Data source to collect (default: all). Use 'weekly' or 'monthly' for scheduled runs.",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=2010,
        help="Start year for historical backfill (default: 2010)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if sha256 is unchanged",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("collector")

    ensure_dirs()

    if args.source == "all":
        targets = list(SOURCES.keys())
    elif args.source == "structured":
        targets = ["gtr", "quickstats", "wasde", "psd", "ers_feedgrains", "export_sales"]
    elif args.source == "reports":
        targets = ["wwcb", "wasde_pdf"]
    elif args.source == "weekly":
        targets = [k for k, v in SOURCES.items() if v[2] == "weekly"]
    elif args.source == "monthly":
        targets = [k for k, v in SOURCES.items() if v[2] == "monthly"]
    else:
        targets = [args.source]

    log.info(
        "Starting collection: sources=%s, since=%d, force=%s",
        targets, args.since, args.force,
    )
    t0 = time.time()
    results: dict[str, str] = {}

    for source_key in targets:
        module_path, label, _schedule = SOURCES[source_key]
        log.info("─── %s (%s) ───", source_key.upper(), label)
        try:
            mod = __import__(module_path, fromlist=["collect"])
            mod.collect(since=args.since, force=args.force)
            results[source_key] = "ok"
        except Exception:
            log.exception("FAILED: %s", source_key)
            results[source_key] = "failed"

    manifest.flush()
    elapsed = time.time() - t0
    log.info("═══ Collection finished in %.1fs ═══", elapsed)
    for k, v in results.items():
        status = "✓" if v == "ok" else "✗"
        log.info("  %s %s", status, k)

    if any(v == "failed" for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
