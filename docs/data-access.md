# Data Access Abstraction

## 개요

모든 데이터 읽기/쓰기는 `DataBackend` 인터페이스를 통해 수행.
배포 환경 변경 시 구현체만 교체하면 코드 수정 불필요.

## 인터페이스

```python
class DataBackend(ABC):
    read_parquet(rel_path) → DataFrame
    write_parquet(rel_path, df)
    read_json(rel_path) → Any
    write_json(rel_path, data)
    read_image(rel_path) → bytes
    write_image(rel_path, data)
    list_files(rel_dir, pattern) → list[str]
    exists(rel_path) → bool
    resolve_path(rel_path) → str
    ensure_dir(rel_dir)
```

## 사용법

```python
from common.data_access import get_backend
backend = get_backend()
df = backend.read_parquet("normalized/structured/grain.parquet")
```

## 백엔드 전환

`.env` 파일에서 `DATA_BACKEND` 변경:
- `local` (기본값): 파일시스템
- `s3`: AWS S3 (Phase 2)
- `gcs`: Google Cloud Storage (Phase 2)

## Phase 2 구현 가이드

`common/data_access.py`에 `S3Backend(DataBackend)` 추가.
`get_backend()` 함수에 분기 추가.
기존 코드 수정 불필요.
