# Lab 워크플로우 & 스킬

## 실험 워크플로우

`/lab-tunnel` → 실험 수행 → `/lab-restore` → 다음 실험

## 스킬 카탈로그

| 스킬 | 설명 |
|------|------|
| `/lab-tunnel` | 실험 환경 터널링 + preflight check (K8s API, Prometheus, Loki) |
| `/lab-restore` | 실험 후 환경 정상화 (fault 잔여물 제거, 디스크 정리, 모니터링 복원) |
| `/changelog` | 변경 이력 기록. 모든 에이전트가 수정 작업 후 반드시 호출 |
| `/commit-push` | Git commit & push (실험 중이 아닐 때만) |
| `/experiment-status` | 실험 진행상황 확인 (PID, 진행률, trial별 결과) |
| `/deep-analysis` | 실험 개선점 심층 분석 (이전 데이터 분석 + LLM/AIOps 서칭 → 개선 가설 도출) |
| `/paper-reader` | 논문 심층 읽기 (20년차 SRE 관점, LLM+클라우드 운영 적용 분석). **에이전트가 논문을 읽을 때 반드시 사용** |
| `/paper-survey` | AIOps 논문 조사 (최근 3년 LLM+RCA 논문 서베이, `docs/surveys/`에 결과 저장) |

## Lab 환경

실험 환경 상세 정보: `docs/lab-environment.md`
