# V5 실험 변경 이력

---

### 1. /deep-analysis 스킬 생성 + V5 심층 분석 — 2026-04-08

- **수정 에이전트**: 오케스트레이터 (deep-analysis skill)
- **증상/문제**: /paper-survey 스킬이 WebSearch 대량 호출로 진행 불가. 이전 실험 데이터를 깊게 분석하여 개선점을 도출하는 전용 스킬 필요.
- **원인**: 논문 서베이 접근 방식의 한계 — 인터넷 검색 양이 많아 비효율적
- **수정 내용**:
  1. `/deep-analysis` 스킬 생성 — 이전 실험 데이터 Python 분석 + LLM/AIOps 인터넷 서칭 + 3개 가설 도출
  2. V4 부분 결과 분석(40/50 trials) → `results/analysis_v4.md` 저장
  3. V5 심층 분석 수행 → `docs/surveys/deep_analysis_v5.md` 작성
  4. CLAUDE.md 파이프라인에 Step 0.5(/deep-analysis) 추가, Skills 섹션에 등록
- **수정 파일**:
  - `.claude/skills/deep-analysis/SKILL.md` (신규)
  - `results/analysis_v4.md` (신규)
  - `docs/surveys/deep_analysis_v5.md` (신규)
  - `CLAUDE.md:55-62` (파이프라인 Step 0.5 추가)
  - `CLAUDE.md:123` (Skills 섹션에 /deep-analysis 등록)
  - `results/experiment_changes_v5.md` (신규, 본 파일)
- **상태**: 수정됨

**도출된 V5 가설 3개:**
- V5a: Structured Symptom Extraction → Diagnosis 2단계 분리 (프롬프트 구조)
- V5b: Confidence-Weighted Self-Consistency Voting (생성 전략)
- V5c: Differential Evaluator + 구체적 피드백 Retry (하네스 개선)
