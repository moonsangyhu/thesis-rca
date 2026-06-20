---
title: "실험 완전 종료 자율 goal 프롬프트"
purpose: "autonomous goal 기능에 넣어 한 실험 버전을 수집→분석→PR 머지까지 자율 종료시키는 표준 프롬프트"
usage: "아래 블록을 복사해 {{...}} 플레이스홀더만 해당 실험에 맞게 치환한 뒤 goal에 입력"
scope_options: "범위(F11/F12 복구 시도 후 전체 | 일부 fault만) · 종료 지점(PR 생성까지 | 머지까지 자동) 은 §범위/종료에서 선택"
---

# 실험 완전 종료 — 자율 goal 프롬프트 템플릿

autonomous goal 기능에 넣어, 새 에이전트가 대화 맥락 없이 시작해도 한 실험 버전을
**수집 → 검증 → 정식 분석 → PR → 머지**까지 자립적으로 끝내게 하는 표준 프롬프트다.

## 사용법

1. 아래 코드블록 전체를 복사한다.
2. `{{EXPERIMENT}}`(예: `V2.1`), `{{SLUG}}`(예: `v2_1`), 현재 상태/수치 등 플레이스홀더를 실제 값으로 치환.
3. **범위**(F11/F12 복구 시도 후 전체 vs 일부 fault만)와 **종료 지점**(PR 생성까지 vs 머지까지 자동)을
   해당 줄에서 선택해 한쪽만 남긴다.
4. goal에 입력.

> ⚠️ 가드레일(모델 고정·데이터 불변·PR-only)과 STOP 조건은 그대로 유지할 것. 이게 자율 실행의 안전장치다.

---

## 프롬프트 (복사용)

```
[GOAL] K8s RCA 석사 실험 {{EXPERIMENT}}({{설명: 예 옛 V10, re-baseline}})을 완전히 종료한다.

레포: /Users/yumunsang/thesis-rca (현재 main). 모든 작업은 PR-only 정책을 따른다.

■ 먼저 읽고 현황 파악 (착수 전 필수)
- results/{{SLUG}}_progress_report.md   ← 현재 상태·결과·미완 원인
- rules/experiment-pipeline.md          ← 실험 7-Step 파이프라인 (Step 4~6 적용)
- rules/data-safety.md                  ← 데이터 불변·모델 고정·실험 격리 규칙
- docs/lab-environment.md, .hermes/handoffs/  ← 재구축 환경·접속
- scripts/fault_inject/config.py (WORKER_NODES), scripts/fault_inject/injector.py
  (F11=netem delay, F12=netem loss), scripts/tunnel.sh

■ 현재 상태 (요약)
- {{EXPERIMENT}}은 {{수집 완료 범위: 예 F1–F10}}만 수집 완료
  ({{핵심 수치: 예 System A 41.7%, System B 50.0%}}).
  결과: results/experiment_results_{{SLUG}}.csv, raw_{{SLUG}}/, experiment_{{SLUG}}.log
- {{미완 항목: 예 F11(NetworkDelay)/F12(NetworkLoss) 주입 실패}}:
  {{원인 요약: 예 워커 노드 SSH(debian@211.62.97.71:22016~22018) tc netem 15초 타임아웃}}.
  → 모델 문제 아니라 환경/접속 문제로 추정.

■ Definition of Done (모두 충족돼야 종료)
1. 데이터가 가능한 범위까지 수집됨
   (복구 성공 시 전체 fault, 복구 불가 판정 시 기존 범위 + 한계 명시)
2. results/analysis_{{SLUG}}.md 정식 분석 문서 작성
   (시스템 A vs B McNemar χ² 검정·p값, fault별/카테고리별 정확도, eval 점수 분포,
    미수집 fault 상태, 결론·한계)
3. 변경이 feature 브랜치 → 한글 PR → {{종료: rebase 머지까지 자동 | PR 생성까지}} 완료

■ 실행 절차
[Phase 1] 환경 연결 + 사전점검
  - /lab-tunnel (또는 ./scripts/tunnel.sh start) 로 K8s API·Prometheus·Loki 터널.
  - kubectl get nodes / boutique 파드 Ready 확인. 비정상이면 정리 후 진행.

[Phase 2-A] 미완 fault 주입 복구 시도 (체계적 디버깅)
  - 가설 검증식 접근: 먼저 수동으로
      ssh -p 22016 debian@211.62.97.71 'sudo tc qdisc show dev ens18'
    를 시도해 SSH 도달성·NOPASSWD sudo·tc 존재·인터페이스명(ens18)을 분리 확인.
  - 흔한 원인: 포트/방화벽 미개방, SSH 키 미배포, sudo 비밀번호 요구, iface명 불일치,
    tc(iproute2) 미설치. 원인을 좁혀 scripts/fault_inject/ 또는 노드 설정을 수정.
  - 복구되면 dry 검증 1회 후 실제 1 trial로 메트릭·로그가 채워지는지 확인.
  - 무한정 시도 금지. 핵심 가설 3~4개 검증 후에도 불가하면 "환경 달성 불가"로 판정하고
    Phase 2-B를 건너뛰어 Phase 3로 간다. (절대 가짜/추정 데이터를 CSV에 넣지 않는다.)

[Phase 2-B] 재수집 (복구 성공 시에만)
  - 백그라운드 실행: nohup python -m experiments.{{SLUG}}.run --fault {{Fxx}} (이어서 나머지),
    또는 python -m experiments.{{SLUG}}.run --resume (기수집분은 자동 skip).
  - /experiment-status 로 주기적 진행 확인. 완료까지 대기(수십 분~1시간+ 가능).
  - 산출물은 기존 CSV에 append. 기존 행·raw·ground_truth.csv는 절대 수정 금지.

[Phase 3] 검증 + 정식 분석
  - superpowers:verification-before-completion 기준 충족:
    실제 CSV 행 수·raw JSON 개수·로그를 명령 실행 결과로 확인하고 인용.
  - results/analysis_{{SLUG}}.md 작성 (DoD 2 포함). 통계는 실제 데이터로 계산.

[Phase 4] 환경 정상화 + 마무리
  - /lab-restore 로 fault 잔여물 제거·클러스터 복원·터널 정리.
  - feature 브랜치 생성 → 커밋·푸시 → 한글 PR 생성 →
    {{종료: gh pr merge --rebase --delete-branch 로 머지·main 동기화 | PR 생성 후 사용자 검토 대기}}.

■ 가드레일 (위반 금지)
- 모델은 gpt-4o-mini 고정. 프롬프트·엔진 로직 변경 금지(목표는 수집·분석·마무리).
- 기존 결과 CSV 행, raw_{{SLUG}}/ JSON, results/ground_truth.csv 수정·삭제 금지(append만).
- main 직접 커밋·push·force·--no-verify·--admin 금지. 반드시 feature 브랜치 → PR → rebase 머지.
- 커밋·PR·문서는 한국어. (hooks/pr-only-guard.sh 가 위반 차단 — 우회 금지.)

■ 종료(STOP) 조건 — 다음 중 하나면 멈추고 한 줄 보고
- (성공) DoD 1·2·3 모두 충족 → 최종 결과(정확도·p값·미완 fault 상태) 요약 보고 후 종료.
- (블록) 랩 클러스터/SSH 지속 불가, OpenAI 키 부재, 또는 Phase 2-A 합리적 시도 후 환경 복구 불가
  → 기존 수집 범위로 분석·문서·PR{{·머지}}까지 완료하고 "미완 fault 환경 미달성" 한계를
  analysis_{{SLUG}}.md와 PR 본문에 명시한 뒤 종료. (이 경우도 DoD 2·3는 충족.)
- 같은 오류로 진전 없이 3회 이상 반복되면 추측 강행 말고 멈춰 현재 상태를 보고.
```

---

## V2.1 적용 예시 (현재 실험에 바로 사용)

위 템플릿에서 `{{EXPERIMENT}}=V2.1`, `{{SLUG}}=v2_1`, 수집 완료=`F1–F10`(A 41.7% / B 50.0%),
미완=`F11/F12 주입 실패(워커 노드 SSH tc netem 타임아웃)`, 범위=`F11/F12 복구 시도 후 전체`,
종료=`rebase 머지까지 자동` 으로 치환하면 V2.1 완전 종료 goal이 된다.
