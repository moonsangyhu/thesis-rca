# V2.3 Terra 파일럿 실행 Runbook

> 상태: 관리자 zero-overage 증빙 및 사용자 실행 승인을 확인함. 2026-08-09 F7 trial 5의 5m rollout 교락으로 무효화한 뒤, 사용자 승인에 따라 F7 trial 1로 변경함.

## 1. 파일럿 고정 범위

- incident: `F7` trial `1` 한 건 (`frontend`, CPU limit/request `10m`)
- conditions: `runtime`, `length_placebo`, `blind_procedural_rag`
- model: generator/judge 모두 `gpt-5.6-terra`
- calls: generator 9 + judge 27 = 총 36
- call별 최대 AIC: 10.0
- campaign 최대 AIC: 360.0
- output: `artifacts/v2_3_pilot/{campaign_id}/`
- 자동 재시도: 없음
- injection을 시도한 뒤에는 성공·예외·중단과 관계없이 recovery를 정확히 한 번 시도한다.
- V2.2 historical prompt proxy는 F7 t1 최대 약 12.9k chars, F7 t5 최대 약 16.6k chars다. t1 pilot 비용을 본실험에 투영할 때 기존 15% margin 외에 context ratio `16.6/12.9 ≈ 1.29`를 적용한다.

## 2. Zero-overage 증빙

회사 GitHub 관리자에게서 다음 세 자료를 잘라낸 화면 또는 export 파일로 받는다. 계정명·조직명과 설정 상태만 남기고 토큰·개인정보·다른 조직 정보는 제거한다.

1. `AI credits paid usage = Disabled`
2. `Stop usage when budget limit is reached = Enabled`
3. 파일럿 직전 included AIC balance

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
- recovery `health_check_passed=true` 확인 후에만 three-arm 3 rows/36 calls commit

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
