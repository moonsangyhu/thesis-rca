# V2.3 Terra 파일럿 실행 Runbook

> 상태: 2026-08-12 사용자가 추가 과금 가능성을 실행 차단 사유에서 제외하도록 명시적으로 변경했다. F7 trial 1 설계와 캠페인/세션 AIC 상한은 유지하고, 실제 server quota는 provenance로 기록한 뒤 파일럿을 재개한다.

## 1. 파일럿 고정 범위

- incident: `F7` trial `1` 한 건 (`frontend`, CPU limit/request `10m`)
- conditions: `runtime`, `length_placebo`, `blind_procedural_rag`
- model: generator/judge 모두 `gpt-5.6-terra`
- calls: generator 9 + judge 27 = 총 36
- Copilot 단일 CLI 세션 상한: 30 AIC (CLI 1.0.78의 허용 최소값이며 예상 사용량이 아님)
- campaign 최대 AIC: 360.0
- 호출 전 `누적 AIC + 30 <= 360`일 때만 다음 subprocess를 허용한다.
- output: `artifacts/v2_3_pilot/{campaign_id}/`
- 자동 재시도: 없음
- Flux 상위 `flux-system`과 하위 `app` Kustomization은 incident 동안 root→child 순서로 suspend한다. 두 기존 suspend field의 존재 여부와 값을 mutation 전에 fsync하고, F7 복구 뒤 child→root 순서로 정확히 원상복원한다.
- injection을 시도한 뒤에는 성공·예외·중단과 관계없이 recovery를 정확히 한 번 시도한다.
- V2.2 historical prompt proxy는 F7 t1 최대 약 12.9k chars, F7 t5 최대 약 16.6k chars다. t1 pilot 비용을 본실험에 투영할 때 기존 15% margin 외에 context ratio `16.6/12.9 ≈ 1.29`를 적용한다.

## 2. Billing authorization

두 상호 배타적 실행 모드를 지원한다.

- `zero-overage-evidence`: 기존 관리자 증빙 3종과 서버 overage=false를 요구한다.
- `paid-overage-user-authorized`: `--allow-paid-overage`, `THESIS_V23_PAID_OVERAGE_AUTHORIZED=1`, 사용자 승인 gate를 함께 요구한다. 서버 overage 상태는 account/Business seat와 함께 매 호출 전 재조회해 manifest에 기록하지만 차단하지 않는다.

현재 캠페인은 사용자의 2026-08-12 지시에 따라 두 번째 모드로 실행한다. 이는 tool/MCP/skill 차단, 30 AIC 세션 cap, 360 AIC 파일럿 campaign cap, durable charge receipt, 실패 후 campaign abort를 변경하지 않는다.

### Zero-overage legacy mode

회사 GitHub 관리자에게서 다음 세 자료를 잘라낸 화면 또는 export 파일로 받는다. 계정명·조직명과 설정 상태만 남기고 토큰·개인정보·다른 조직 정보는 제거한다.

1. `AI credits paid usage = Disabled`
2. `Stop usage when budget limit is reached = Enabled`
3. 파일럿 직전 included AIC balance

수동 증빙 모드에서는 공식 SDK `account.getCurrentAuth`와 `account.getQuota`를 K8s import 전과 매 Copilot 호출 전에 확인한다. login `moonsangyhu`, Business seat SKU, token-based billing을 exact binding하고, overage 허용 flag/사용량이 있거나 포함 잔여량이 부족하면 즉시 중단한다.

세 파일은 repo 밖에 보관하고 SHA-256을 계산한다. `docs/plans/v2_3_billing_evidence_template.json`을 repo 밖으로 복사해 절대경로·hash·관측값을 채운다. 확인 시각과 balance 관측 시각은 24시간 이내여야 한다.

로컬 manifest는 관리 정책을 대신하지 않는다. 세 evidence 파일의 실제 SHA-256을 재계산해 일치해야만 실행 권한 객체가 생성된다.

수동 hash·JSON 편집 대신 다음 오프라인 intake를 사용할 수 있다. 세 파일의 내용을 사람이 직접 확인한 뒤 실행하며, evidence와 manifest는 모두 repo 밖에 둔다. 이 명령은 Copilot·GitHub·클러스터·네트워크를 호출하지 않는다.

```bash
python3.11 -m experiments.v2_3.evidence_intake \
  --paid-usage-disabled /Users/yumunsang/v2_3_evidence/paid-usage-disabled.png \
  --budget-hard-stop /Users/yumunsang/v2_3_evidence/budget-hard-stop.png \
  --included-aic-balance /Users/yumunsang/v2_3_evidence/included-aic-balance.png \
  --included-aic-balance-value 21150 \
  --account-scope company/REPLACE_ORG \
  --confirmed-by REPLACE_ADMIN_ID_OR_ROLE \
  --output /Users/yumunsang/v2_3_evidence/v2_3-billing-evidence.json \
  --confirm-reviewed
```

intake는 세 artifact의 경로와 SHA-256이 모두 고유한지, 파일과 output이 repo 밖인지, balance가 양의 유한값인지 검증한다. manifest는 exclusive create와 mode `0600`으로 생성하고 즉시 정식 verifier로 재검증한다.

## 3. 실행 전 필수 승인

다음 두 환경변수는 증빙 검토와 사용자의 파일럿 승인 후 같은 shell에서만 설정한다.

```bash
export THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED=1
export THESIS_V23_PILOT_USER_APPROVED=1
```

둘 중 하나라도 없거나 `1`이 아니면 Copilot·Kubernetes lazy import 전에 중단된다.

## 4. 고정 명령

아래 명령은 `$lab-tunnel`이 GREEN이고 사용자가 승인한 새 campaign에서만 실행한다.

```bash
KUBECONFIG="/Users/yumunsang/.kube/config-k8s-lab" \
/Users/yumunsang/thesis-rca/.venv/bin/python -m experiments.v2_3.run --pilot \
  --billing-evidence /absolute/path/v2_3-billing-evidence.json \
  --approval-id pilot-YYYYMMDD-approved \
  --campaign-id v2-3-pilot-YYYYMMDD-HHMM \
  --chroma-dir /Users/yumunsang/thesis-rca/data/chromadb \
  --max-campaign-aic 360
```

실행 경로는 다음을 fail-closed 검증한다.

- 증빙 3종의 실제 file hash, 조직 scope, 확인자·방법, 24시간 freshness
- output campaign directory가 존재하지 않음
- Copilot CLI 실제 모델·session·output token·AIC 및 tool/MCP/remote event 0
- CLI 종료 직후 성공·파싱 실패·cap 초과와 무관하게 charged-call receipt를 fsync
- Chroma corpus/index snapshot hash와 runtime-only query provenance
- preflight GREEN, injector receipt와 live deployment CPU state 일치, 단일 collect
- Flux root/app identity와 원래 suspend 상태를 durable hierarchy receipt로 봉인하고 root·app suspend=true가 각각 10회 연속 안정적인 뒤에만 F7을 주입
- 성공·오류·partial patch와 무관하게 F7 복구 후 app→root suspend field를 원래 존재 여부·값으로 복원
- recovery `health_check_passed=true` 확인 후에만 three-arm 3 rows/36 calls commit

### 강제 종료 emergency restore

오케스트레이터는 pilot PID와 `campaign_events.jsonl`을 함께 감시한다. 프로세스가 사라졌는데 `flux_restored` 또는 `flux_emergency_restored`가 없으면 다음 idempotent 명령을 즉시 실행한다. 이 명령은 campaign identity와 hierarchy receipt를 검증하고, F7 receipt가 있으면 **frontend/server CPU limit 200m·request 100m exact recovery를 먼저 수행한 뒤** Kubernetes `resourceVersion` CAS로 app→root 원래 suspend field 존재 여부·값을 복원한다. Flux suspend 뒤 F7 receipt 전 crash window에서는 mutation이 시작되지 않았으므로 hierarchy-only exact restore를 수행한다. `injection_started` 뒤 F7 receipt가 없거나 receipt가 중복이면 실패로 남기되 Flux hierarchy 복구는 계속 시도한다. journal의 마지막 append가 SIGKILL로 잘린 경우 그 불완전 tail만 무시하며 중간 손상은 거부한다. concurrent actor가 다른 false 상태를 만든 경우 이를 덮어쓰지 않고 실패한다.

```bash
KUBECONFIG=/Users/yumunsang/.kube/config-k8s-lab \
/Users/yumunsang/thesis-rca/.venv/bin/python -m experiments.v2_3.flux_restore \
  --campaign-dir /Users/yumunsang/thesis-rca-v2-3-terra/artifacts/v2_3_pilot/CAMPAIGN_ID
```

명령 성공 뒤에도 frontend/server CPU limit 200m·request 100m와 rollout generation/ready/available exact state, `spec.suspend` 원래 absent/false, Flux `app` Ready, Boutique 12/12를 읽기 전용으로 확인한다. F7 또는 Flux emergency restore가 하나라도 실패하면 완료 event를 기록하지 않고 추가 실험을 시작하지 않으며 cluster recovery를 최우선으로 처리한다.

## 5. 완료 후 확인

파일럿 종료 후 UI included AIC balance `B1`을 다시 캡처한다. 다음이 모두 맞지 않으면 본실험 승인을 요청하지 않는다.

- `pilot_results.csv`: 3행
- `raw/*.json`: 3개
- `pilot_call_ledger.jsonl`: 36개
- `attempt_call_ledger.jsonl`: 성공 시 36개
- `charged_call_ledger.jsonl`: 실제 CLI process attempt 전체(성공 시 36개)
- requested/actual model: 36/36 `gpt-5.6-terra`
- tool/MCP/remote/custom event: 0
- manifest `B0 - B1`과 ledger AIC 합 일치
- campaign event 마지막 상태: `pilot_complete`, recovery `GREEN`

그 뒤 계획서의 `scaled_pilot`, `role_upper`, `projected_main`, `reserve`를 계산해 본실험 비용·시간과 함께 다시 사용자 승인을 받는다.
