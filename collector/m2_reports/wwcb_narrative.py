"""WWCB narrative text extraction — 리포트 본문을 섹션 단위 JSON으로 정규화.

as-is: wwcb.py가 raw PDF 다운로드까지만 수행 (본문 추출은 "Phase 2 예정"으로 미구현),
       data/normalized/wwcb_narrative/ 빈 디렉토리만 존재
to-be: raw PDF → 페이지 텍스트 추출 → TOC 섹션 매핑 → 섹션 단위 JSON
       (predict-models TB2 v2가 이미지 도메인 서술에 리포트 본문을 결합하는 데 사용,
        REST 계약: api/routers/reports.py)

출력: normalized/wwcb_narrative/wwcb_YYYYMMDD.json
  {report_id, kind, date, n_pages, sections: [{title, pages, text}]}

기존 자산 재사용: m3_images.ocr_classifier의 parse_wwcb_toc / lookup_toc_section,
raw PDF 46부(재다운로드 없음).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

from common import manifest
from common.data_access import get_backend
from common.storage import RAW_DIR, ensure_dirs, sha256_file

from collector.m3_images.ocr_classifier import lookup_toc_section, parse_wwcb_toc

log = logging.getLogger(__name__)

SOURCE = "USDA_WWCB_NARRATIVE"

OUT_REL_DIR = "normalized/wwcb_narrative"

# USER-CONFIG: 페이지 머리글/바닥글 제거 패턴 (m3_images.wwcb_images와 동일 계열)
_HEADER_RE = re.compile(
    r"^\s*\d+\s*$|"
    r"^Weekly Weather and Crop Bulletin|"
    r"^\w+ \d+, \d{4}\s*$",
    re.IGNORECASE,
)

# USER-CONFIG: 섹션 텍스트가 이 길이 미만이면 이미지 전용 섹션으로 보고 text를 비움
MIN_SECTION_CHARS = 40


def _clean_page_text(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER_RE.match(stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def extract_narrative(pdf_path: Path) -> dict:
    """WWCB PDF 1부에서 섹션 단위 본문을 추출한다."""
    doc = fitz.open(pdf_path)
    try:
        page_texts = [_clean_page_text(page.get_text("text")) for page in doc]
    finally:
        doc.close()

    toc = parse_wwcb_toc(page_texts[0]) if page_texts else {}

    # 페이지 → TOC 섹션 매핑 후 섹션 순서 유지 병합
    sections: list[dict] = []
    current: dict | None = None
    for page_num, text in enumerate(page_texts, start=1):
        title = lookup_toc_section(toc, page_num) or ""
        if current is None or current["title"] != title:
            current = {"title": title, "pages": [page_num], "_texts": [text]}
            sections.append(current)
        else:
            current["pages"].append(page_num)
            current["_texts"].append(text)

    for sec in sections:
        text = "\n".join(t for t in sec.pop("_texts") if t)
        sec["text"] = text if len(text) >= MIN_SECTION_CHARS else ""

    date_str = pdf_path.stem.replace("wwcb_", "")
    return {
        "report_id": pdf_path.stem,
        "kind": "wwcb",
        "date": date_str,
        "n_pages": len(page_texts),
        "sections": sections,
    }


def collect(since: int = 2010, force: bool = False) -> None:
    """raw/wwcb/*.pdf 전체에서 본문 JSON을 생성한다 (증분: 기존 JSON은 건너뜀)."""
    ensure_dirs()
    backend = get_backend()
    raw_dir = RAW_DIR / "wwcb"
    pdfs = sorted(raw_dir.glob("wwcb_*.pdf"))
    if not pdfs:
        log.warning("WWCB narrative: raw PDF 없음 (%s)", raw_dir)
        return

    existing = set(backend.list_files(OUT_REL_DIR, "*.json"))
    done = 0
    skipped = 0
    for pdf in pdfs:
        rel_out = f"{OUT_REL_DIR}/{pdf.stem}.json"
        if not force and any(rel_out.endswith(name) or name.endswith(f"{pdf.stem}.json")
                             for name in existing):
            skipped += 1
            continue
        try:
            data = extract_narrative(pdf)
        except Exception:
            log.exception("WWCB narrative: 추출 실패 %s", pdf.name)
            continue

        backend.write_json(rel_out, data)
        manifest.upsert(
            source=SOURCE,
            artifact_type="normalized_json",
            period=f"week_{data['date']}",
            path=Path(rel_out),
            sha256=sha256_file(pdf),
        )
        done += 1
        log.info("WWCB narrative: %s (%d sections)", pdf.stem, len(data["sections"]))

    log.info("WWCB narrative: %d 생성, %d 건너뜀 (기존)", done, skipped)
