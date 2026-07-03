# 하드웨어 이전 체크리스트 (갱신: 2026-07-03)

대상: Windows 10, i5-10400F, RTX 3050 머신으로 전체 작업 환경 이전.
원칙: **git으로 가는 것 / 손으로 복사해야 하는 것 / 새로 설치하는 것** 3분류.

---

## A. git으로 가는 것 (새 머신에서 clone)

```
git clone https://github.com/graffitip912/usdapipline.git usda-grain-pipeline
```
- 최신 커밋 확인: `0c3ba4b` 이후. 코드·문서·하네스 명세·검증 스크립트 전부 포함.

## B. 손으로 복사해야 하는 것 (git에 없음 — USB/네트워크 공유)

| 우선순위 | 대상 | 이유 |
|----------|------|------|
| **필수** | `usda-grain-pipeline\.env` | API 키 (NASS, FAS) — git 금지 파일 |
| **필수 — 재생성 불가** | `usda-grain-pipeline\data\meta\` | manifest + **검증 승인 기록·CR 루프 이력** (Stage 3 exit condition의 증거) |
| **필수 — 재생성 불가** | `usda-grain-pipeline\data\curated\` | 큐레이션 176건 (사용자 전수 검토 산출물) |
| **강력 권장** | `usda-grain-pipeline\data\` 전체 (1.2GB) | 재수집 수 시간 + export_sales는 FAS 장애로 재수집 자체가 불가. 통째 복사가 안전 |
| **필수** | `C:\workspace\predict-client-dev\` 전체 | **git 저장소 아님** — 복사 누락 시 유실 |
| **필수** | `C:\workspace\predict-models\` 전체 | **git 저장소 아님** — 설계 기준서 포함 |
| **필수** | `C:\Users\<user>\.claude\projects\C--workspace\memory\` | Claude Code 지속 메모리 (작업 지침·프로젝트 기억 7건) |

> ⚠️ 경로 유지: 새 머신에서도 작업 폴더를 **`C:\workspace`** 로 유지할 것.
> Claude 메모리 디렉토리가 프로젝트 경로로 키잉(`C--workspace`)되므로 경로가 다르면 메모리가 연결되지 않음.
> 메모리 복사 위치도 동일하게 `C:\Users\<새유저>\.claude\projects\C--workspace\memory\`.

> 권장: predict-client-dev / predict-models도 이전 후 git init + 원격 push (현재 git 미관리 상태가 유실 리스크).

## C. 새 머신에 설치하는 것 (순서대로)

1. **Git**, **Python 3.14** (requirements-lock 기준 버전), **Node.js 22**
2. **Claude Code** 설치 → `claude login`
3. **uv**: `pip install uv` — ⚠️ Ouroboros MCP 서버 기동에 필수 (미설치 시 MCP "Failed to connect" — 2026-07-03 진단 사례)
4. Claude Code 플러그인 3종 재설치: `ouroboros`, `superpowers`, `huggingface-skills` (`/plugin`)
5. (선택) **Tesseract OCR** — wwcb_images OCR 분류용 (없으면 OCR 단계 자동 스킵)
6. (RTX 3050 활용 시) NVIDIA 드라이버 + CUDA 지원 llama.cpp/PyTorch — predict-models 단계에서 필요, 파이프라인 자체는 불필요

## D. 새 머신 셋업 순서

```powershell
# 1. clone + 복사물 배치 (B 항목들)
git clone https://github.com/graffitip912/usdapipline.git C:\workspace\usda-grain-pipeline
# .env, data\, predict-*, 메모리 폴더를 위 표의 위치에 복사

# 2. 환경 구성 (venv + pip + npm + 디렉토리 + 자가검증)
cd C:\workspace\usda-grain-pipeline
.\scripts\setup_env.ps1

# 3. 서버 기동
python -m uvicorn api.main:app --port 8000     # 별도 터미널
cd dashboard; npm run dev                       # 별도 터미널

# 4. 이전 성공 판정 (시맨틱 배포 게이트 — 8/8 통과해야 완료)
python scripts\verify_pipeline.py
```

## E. 이전 완료 판정 기준

1. `verify_pipeline.py` **8/8 통과** (UI→API 계약, Run 체인, preview, 스케줄 왕복, 대시보드)
2. admin(:3000/admin)에서 소스 상태·검증 승인 기록(approved 6건)이 그대로 보임 — data\meta 복사 성공의 증거
3. Claude Code에서 `claude mcp list` → ouroboros ✔ Connected
4. Claude Code 새 세션에서 메모리 지침이 로드됨 (MEMORY.md 항목 인식)

## 환경 요구사항 요약

- Python 3.14 / Node.js 22 / Git / uv / Claude Code + 플러그인 3종
- (선택) Tesseract OCR
- RTX 3050: 파이프라인에는 불필요, predict-models 학습·추론 가속용 (VRAM 8GB/6GB 변형 확인 필요)
