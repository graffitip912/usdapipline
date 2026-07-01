# Image Extraction Pipeline

## 4단계 필터링

```
PDF → PyMuPDF 추출 → Stage 1 규칙 → Stage 2 해시 → Stage 3 OCR → 최종 이미지
                                                                        ↓
                                                              Stage 4: curation.json (수동)
```

### Stage 1: 규칙 기반 필터
- 크기: 150x150 미만 제외, 10KB 미만 제외
- 비율: aspect_ratio > 4.0 제외
- 위치: 첫 페이지 제외
- 키워드: satellite, drought 등 + 250,000px 면적 → 우선 포함

### Stage 2: 퍼셉추얼 해시
- `imagehash.phash()` 로 이미지 해시 생성
- `curation.json`의 blocklist_hashes와 hamming distance ≤ 5 비교
- 관리자가 "제외" 표시한 이미지의 해시가 자동으로 blocklist에 추가

### Stage 3: Tesseract OCR
- 이미지 내부 텍스트 추출
- 분류: satellite, weather_map, chart, unknown
- Tesseract 미설치 시 경고만 출력하고 건너뜀

### Stage 4: 수동 큐레이션
- `data/assets/wwcb/curation.json`에서 관리
- 수동 판정: `manual_decisions` → `{filename: {keep: bool, note: str}}`
- Phase 2에서 웹 UI로 편집 가능

## 설정 파일: curation.json

```json
{
  "rules": {
    "min_width": 150, "min_height": 150,
    "min_area": 250000, "min_size_kb": 10,
    "max_aspect_ratio": 4.0, "exclude_first_page": true,
    "keywords": ["satellite", "drought", ...]
  },
  "blocklist_hashes": [],
  "manual_decisions": {}
}
```

## 검증 기준

- 정밀도 ≥ 85%, 재현율 ≥ 90%
- Blocklist 정확도 ≥ 95%
- 위성/기상 지도 잘못 제외 = 0건
