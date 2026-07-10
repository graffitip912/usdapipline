"""CLI entry point for the USDA grain data collection pipeline.

Usage:
    python -m collector.run --source all --since 2010
    python -m collector.run --source weekly          # cron: every Friday
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
    weekly  : gtr, quickstats, wwcb, wwcb_images
    monthly : wasde, psd, ers_feedgrains, wasde_pdf
    manual  : export_sales (FAS 장애로 자동 수집 제외, 2026-07-03)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from common import manifest
from common.storage import ensure_dirs
from common.schema import validate_with_report
from common.verification import VerificationHistory, VerificationStore

load_dotenv()

SOURCES = {
    "gtr": ("collector.m1_structured.gtr", "GTR xlsx", "weekly"),
    "quickstats": ("collector.m1_structured.quickstats", "NASS QuickStats API", "weekly"),
    "wasde": ("collector.m1_structured.wasde", "WASDE CSV", "monthly"),
    "psd": ("collector.m1_structured.psd", "FAS PSD bulk CSV", "monthly"),
    "ers_feedgrains": ("collector.m1_structured.ers_feedgrains", "ERS Feed Grains CSV", "monthly"),
    # USER-CONFIG: FAS opendata 전면 장애(HTTP 500, 2026-07-03 확인)로 주간 자동
    # 수집에서 제외. FAS 복구 확인 후 "manual" → "weekly"로 되돌릴 것.
    "export_sales": ("collector.m1_structured.export_sales", "FAS Export Sales API", "manual"),
    "wwcb": ("collector.m2_reports.wwcb", "WWCB PDF", "weekly"),
    "wasde_pdf": ("collector.m2_reports.wasde_pdf", "WASDE PDF archive", "monthly"),
    "wwcb_images": ("collector.m3_images.wwcb_images", "WWCB image extraction", "weekly"),
    "wwcb_narrative": ("collector.m2_reports.wwcb_narrative", "WWCB narrative text", "weekly"),
    "usdm_drought": ("collector.m1_structured.usdm_drought", "USDM drought area pct", "weekly"),
}

# Manifest SOURCE constant per run key (each collector module's SOURCE).
# The manifest stores both spellings: collectors write these canonical names,
# run_source() failure records use the run key — status views must merge both.
MANIFEST_SOURCES = {
    "gtr": "USDA_AMS_GTR",
    "quickstats": "USDA_NASS_QUICKSTATS",
    "wasde": "USDA_WASDE",
    "psd": "USDA_FAS_PSD",
    "ers_feedgrains": "USDA_ERS_FEEDGRAINS",
    "export_sales": "USDA_FAS_ESR",
    "wwcb": "USDA_WWCB",
    "wasde_pdf": "USDA_WASDE_PDF",
    "wwcb_images": "USDA_WWCB_IMAGES",
    "wwcb_narrative": "USDA_WWCB_NARRATIVE",
    "usdm_drought": "USDM_DROUGHT",
}

log = logging.getLogger("collector")


def run_source(
    source_key: str,
    since: int = 2010,
    force: bool = False,
) -> dict:
    """Run a single collection source programmatically.

    Returns a dict with keys: source, status ('ok'|'failed'|'stale'), error.
    Used by the API (T4) to trigger collection without CLI.
    """
    if source_key not in SOURCES:
        return {"source": source_key, "status": "failed", "error": f"Unknown source: {source_key}"}

    ensure_dirs()
    module_path, label, _schedule = SOURCES[source_key]
    log.info("─── %s (%s) ───", source_key.upper(), label)

    try:
        mod = __import__(module_path, fromlist=["collect"])
        mod.collect(since=since, force=force)
        manifest.record_success(source_key)

        result: dict = {"source": source_key, "status": "ok", "error": None,
                        "validation_report": None, "needs_user_review": True}

        if source_key in ("wwcb", "wasde_pdf", "wwcb_images"):
            result["needs_user_review"] = True
            return result

        try:
            from common.data_access import get_backend
            backend = get_backend()
            norm_path = f"normalized/structured/{source_key}.parquet"
            if backend.exists(norm_path):
                df = backend.read_parquet(norm_path)
                _, report = validate_with_report(df, source_key)
                result["validation_report"] = report
                if not report["schema_pass"]:
                    store = VerificationStore()
                    store.add_history(VerificationHistory(
                        source=source_key,
                        failure_reason=f"Schema validation failed: {report['dropped_count']} rows dropped",
                        as_is={
                            "row_count": report["row_count_before"],
                            "dropped": report["dropped_count"],
                            "errors": report["error_details"][:5],
                        },
                    ))
        except Exception as val_exc:
            log.warning("Post-collect validation for %s: %s", source_key, val_exc)

        return result
    except Exception as exc:
        error_msg = traceback.format_exc()
        log.exception("FAILED: %s", source_key)
        result_status = manifest.record_failure(source_key, str(exc))

        try:
            store = VerificationStore()
            store.add_history(VerificationHistory(
                source=source_key,
                failure_reason=f"Collection failed: {exc}",
                as_is={"error": str(exc), "traceback": error_msg[:500]},
            ))
        except Exception:
            pass

        return {"source": source_key, "status": result_status, "error": error_msg,
                "validation_report": None, "needs_user_review": False}


def _resolve_targets(source_arg: str) -> list[str]:
    if source_arg == "all":
        return list(SOURCES.keys())
    if source_arg == "structured":
        return ["gtr", "quickstats", "wasde", "psd", "ers_feedgrains", "export_sales"]
    if source_arg == "reports":
        return ["wwcb", "wasde_pdf"]
    if source_arg == "weekly":
        return [k for k, v in SOURCES.items() if v[2] == "weekly"]
    if source_arg == "monthly":
        return [k for k, v in SOURCES.items() if v[2] == "monthly"]
    return [source_arg]


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
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also retry sources in 'failed' status",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ensure_dirs()

    targets = _resolve_targets(args.source)

    if args.retry_failed:
        failed = manifest.get_failed_sources()
        for s in failed:
            if s not in targets:
                targets.append(s)
                log.info("Adding failed source for retry: %s", s)

    log.info(
        "Starting collection: sources=%s, since=%d, force=%s",
        targets, args.since, args.force,
    )
    t0 = time.time()
    results: dict[str, str] = {}

    for source_key in targets:
        result = run_source(source_key, since=args.since, force=args.force)
        results[source_key] = result["status"]

    manifest.flush()
    elapsed = time.time() - t0
    log.info("═══ Collection finished in %.1fs ═══", elapsed)
    for k, v in results.items():
        status = "✓" if v == "ok" else "✗"
        log.info("  %s %s (%s)", status, k, v)

    if any(v != "ok" for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
