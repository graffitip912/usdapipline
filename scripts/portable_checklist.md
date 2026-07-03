# 데스크톱 이전 체크리스트

## 필수 복사 대상 (Git tracked)
```
usda-grain-pipeline/
  common/          # 공유 모듈
  collector/       # 수집기
  api/             # FastAPI
  dashboard/       # Next.js
  scripts/         # 설정 스크립트
  docs/            # 변경 이력
  pyproject.toml   # Python 의존성
  requirements-lock.txt  # 고정 버전
  harness.yaml     # 하네스 설정
  seed.yaml        # Ouroboros 명세
  .env.example     # 환경변수 템플릿
  .gitignore
  CLAUDE.md / AGENTS.md
```

## 복사하지 않는 것 (gitignored, 재생성 가능)
```
.venv/             # setup_env 스크립트로 재생성
node_modules/      # npm install로 재생성
data/              # 수집기 실행으로 재생성
.env               # .env.example에서 복사 후 키 입력
```

## 선택 복사 (시간 절약)
```
data/raw/          # 재수집에 시간이 걸리는 원본 데이터
data/assets/       # 이미지 등 가공된 자산
data/curated/      # 큐레이션 완료 ML 데이터셋
```

## 새 환경 설정 순서
1. `git clone` 또는 폴더 복사
2. `.\scripts\setup_env.ps1` (Windows) 또는 `bash scripts/setup_env.sh` (Linux/Mac)
3. `.env` 파일에 API 키 입력
4. (선택) Tesseract OCR 설치
5. (선택) `data/` 폴더 복사 또는 수집기 재실행

## 환경 요구사항
- Python 3.10+
- Node.js 18+
- (선택) Tesseract OCR — 이미지 텍스트 추출용
- (선택) CUDA GPU — Hugging Face 모델 추론 가속용
