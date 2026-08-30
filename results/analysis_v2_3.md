# V2.3-RAG 독립 비판 분석 — 조기 종료 시점

> 분석일: 2026-08-30  
> 역할: Experiment Track Step 5 fresh results critic  
> 1차 판정: **판정 불가**  
> 분석 대상: `artifacts/v2_3_main/` 전체와 최신 동일-provider 본실험
> `v2-3-codex-20260829-primary01/02`,
> `v2-3-codex-20260830-primary03/04`

이 판정은 효과가 없다는 뜻이 아니다. 승인된 revision의 confirmatory estimand는
F7-t5를 사전 제외한 **단일 캠페인 59 incidents, 177 rows, 2,124 logical
calls**인데, 이를 완료한 캠페인이 하나도 없고 최신 네 캠페인에는 각각 독립적인
leakage, treatment/recovery 또는 runtime-evidence provenance 위반이 있다. 서로 다른
캠페인의 prefix를 이어 붙이지 않았으며 V2.2와 절대 성능도 비교하지 않았다.

## 1. 데이터 검증

### 1.1 정본과 검증 방법

다음 파일을 직접 읽어 기준을 고정했다.

- `rules/experiment-pipeline.md` Step 5와 `rules/agents.md` 부록 A/B
- `rules/data-safety.md`
- `docs/plans/experiment_plan_v2_3.md`
- `docs/plans/review_v2_3.md`
- `docs/issues/experiment_issues_v2_3.md`
- `results/experiment_changes_v2_3.md`

계획서 `§6.4`, `§9.1`, `§9.2`의 현재 기준은 F7-t5 제외, 단일 campaign
59 incidents/177 rows/2,124 calls이며, leakage/treatment/campaign/recovery/provenance
gate 위반 시 점수가 높아도 `판정 불가`다.

검증에는 다음과 같은 실제 read-only 명령을 사용했다. 숫자는 아래 명령의 출력에서
옮겼다.

```bash
git status --short --branch
find artifacts/v2_3_main -maxdepth 2 -type d -print | sort
```

```bash
python3 - <<'PY'
import csv, json, pathlib, collections
root = pathlib.Path('artifacts/v2_3_main')
dirs = sorted(p for p in root.iterdir() if p.is_dir())
complete = manifests = csv_present = 0
for d in dirs:
    if (d/'campaign_manifest.json').exists():
        json.load(open(d/'campaign_manifest.json')); manifests += 1
    rows = []
    if (d/'experiment_results_v2_3.csv').exists():
        rows = list(csv.DictReader(open(d/'experiment_results_v2_3.csv')))
        csv_present += 1
    raw = [json.load(open(p)) for p in sorted((d/'raw_v2_3').glob('*.json'))]
    assert len(rows) == len(raw)
    keys = [(r['fault_id'], r['trial'], r['context_condition']) for r in rows]
    assert len(keys) == len(set(keys))
    for name in ('call_ledger_v2_3.jsonl', 'attempt_call_ledger.jsonl',
                 'charged_call_ledger.jsonl', 'campaign_events.jsonl'):
        p = d/name
        if p.exists():
            records = [json.loads(line) for line in open(p) if line.strip()]
            if name == 'campaign_events.jsonl':
                complete += sum(x.get('event') == 'campaign_complete' for x in records)
print(len(dirs), manifests, csv_present, complete)
# 49 47 27 0
PY
```

```bash
python3 - <<'PY'
import csv, json, pathlib, collections
root = pathlib.Path('artifacts/v2_3_main')
for d in sorted(root.glob('v2-3-codex-*')):
    rows = list(csv.DictReader(open(d/'experiment_results_v2_3.csv')))
    raw = [json.load(open(p)) for p in (d/'raw_v2_3').glob('*.json')]
    logical = [json.loads(s) for s in open(d/'call_ledger_v2_3.jsonl')]
    attempt = [json.loads(s) for s in open(d/'attempt_call_ledger.jsonl')]
    charged = [json.loads(s) for s in open(d/'charged_call_ledger.jsonl')]
    events = [json.loads(s) for s in open(d/'campaign_events.jsonl')]
    ec = collections.Counter(x['event'] for x in events)
    print(d.name, len(rows), len(raw), len(logical), len(attempt), len(charged),
          ec['incident_committed'], ec['incident_failed'],
          ec['recovery_failed'], ec['campaign_complete'])
PY
```

```bash
python3 - <<'PY'
import json, pathlib, collections
for d in sorted(pathlib.Path('artifacts/v2_3_main').glob('v2-3-codex-*')):
    raw = [json.load(open(p)) for p in (d/'raw_v2_3').glob('*.json')]
    calls = [json.loads(s) for s in open(d/'call_ledger_v2_3.jsonl')]
    groups = collections.defaultdict(list)
    for r in raw: groups[(r['fault_id'], r['trial'])].append(r)
    assert all({r['context_condition'] for r in g} ==
               {'runtime','length_placebo','blind_procedural_rag'} for g in groups.values())
    assert all(len({r['runtime_context_hash'] for r in g}) == 1 for g in groups.values())
    assert all(len({r['injection_result_hash'] for r in g}) == 1 for g in groups.values())
    assert all(r['scanner']['match_count'] == 0 for r in raw)
    assert all(r['retrieval_provenance']['query_origin'] == 'runtime_only'
               for r in raw if r['context_condition'] == 'blind_procedural_rag')
    sessions = [c['session_id'] for c in calls]
    assert len(sessions) == len(set(sessions)) and all(sessions)
    assert all(c['provider'] == 'codex-cli-chatgpt-subscription' and
               c['requested_model'] == c['actual_model'] == 'gpt-5.6-terra' and
               c['tool_event_count'] == c['mcp_event_count'] ==
               c['remote_event_count'] == c['custom_instruction_event_count'] == 0
               for c in calls)
    print(d.name, 'incidents=', len(groups), 'scanner_matches=0', 'provenance_bad=0')
PY
```

```bash
rg -n 'Traceback|SKIP|recovery_failed|incident_failed|LeakageDetected|PilotError' \
  artifacts/v2_3_main/v2-3-codex-20260829-primary01 \
  artifacts/v2_3_main/v2-3-codex-20260829-primary02 \
  artifacts/v2_3_main/v2-3-codex-20260830-primary03 \
  artifacts/v2_3_main/v2-3-codex-20260830-primary04
```

### 1.2 전체 artifact tree 감사

`artifacts/v2_3_main/`에는 49개 디렉터리가 있고, 이 중 하나는 F5-t3
model-free probe다. 47개에 manifest, 27개에 결과 CSV가 있었다. CSV가 있는 27개
캠페인은 모두 CSV row 수와 raw JSON 수가 같았고, 파싱 오류·row-key 중복·완료된
incident의 condition mapping 오류는 0이었다. 그러나 **전체 tree의
`campaign_complete` event는 0건**이었다. 이는 과거 부분 결과를 최신 결과와 합칠
근거가 아니라, V2.3 harness의 높은 운영 attrition을 보여 주는 증거다.

오래된 캠페인들은 provider, 코드 revision, schedule, recovery 경계가 여러 차례
바뀌었다. 따라서 모든 과거 CSV/raw는 operational attrition 기록으로만 보존하고
confirmatory dataset으로 합치지 않았다.

### 1.3 최신 네 캠페인의 수량·종료 경계

| campaign | git commit | CSV / raw | logical / attempt / charged | committed / failed / recovery_failed / complete | 마지막 event |
|---|---|---:|---:|---:|---|
| Primary01 | `d1c7a0bb…` | 42 / 42 | 504 / 504 / 504 | 14 / 1 / 0 / 0 | `recovery_green` |
| Primary02 | `2de66327…` | 111 / 111 | 1,332 / 1,332 / 1,332 | 37 / 1 / 1 / 0 | `recovery_failed` |
| Primary03 | `7717a734…` | 117 / 117 | 1,404 / 1,404 / 1,404 | 39 / 1 / 0 / 0 | `recovery_green` |
| Primary04 | `ce244983…` | 90 / 90 | 1,080 / 1,100 / 1,100 | 30 / 1 / 0 / 0 | `recovery_green` |

네 캠페인 모두 manifest는 59/177/2,124와 F7-t5 제외를 정확히 기록했다. 모든
CSV/raw/ledger/event JSON은 파싱됐고, 커밋된 incident마다 세 condition이 정확히
한 행씩 있으며 CSV/raw key는 1:1, 중복은 0이었다. Primary04의 추가 20
attempt/charged는 F7-t1에서 중단 전에 끝난 부분 호출이며 logical ledger와 결과에는
commit되지 않았다.

완료율과 계획 대비 운영 attrition은 각각 다음과 같다.

| campaign | 완료 incident | 완료율 | 미완료율 |
|---|---:|---:|---:|
| Primary01 | 14/59 | 23.7% | 76.3% |
| Primary02 | 37/59 | 62.7% | 37.3% |
| Primary03 | 39/59 | 66.1% | 33.9% |
| Primary04 | 30/59 | 50.8% | 49.2% |

이 비율들을 120/236 같은 하나의 성공률로 합치지 않는다. 동일 early fault가 서로
다른 revision에서 반복 측정됐고 각 캠페인의 종료 원인과 관측 fault set이 다르기
때문이다.

### 1.4 최신 네 캠페인의 독립 중단·무효화 원인

#### Primary01 — F3-t5 leakage gate

event journal은 F3-t5의 `injection_verified` 뒤 `length_placebo` 단계에서
`LeakageDetected`, `field_values=13`, 동일 term hash 13건을 기록하고
`flux_restored → recovery_green`으로 끝난다. 다음 명령으로 term hash를 독립
확인했다.

```bash
python3 - <<'PY'
import hashlib
print(hashlib.sha256(b'main').hexdigest())
PY
# 0d6e4079e36703ebd37c00722f5891d28b0e2811dc114b129215123adcce3605
```

이 값은 event의 term hash와 일치한다. tracker ISS-057과 변경 이력 #93의 설명처럼
`loadgenerator`의 실행 container 이름 `main`이 treatment scalar로 lexicon에 들어가
neutral placebo의 compact substring을 오탐한 것이다. F3-t5에는 model/result/raw가
추가되지 않았지만 campaign은 leakage gate에서 중단됐으므로 전체 primary estimand로
사용할 수 없다.

#### Primary02 — F8-t4 treatment 실패와 recovery 실패

F8-t4 event sequence는 `recovery_receipt_sealed`가 fault/target/trial만 가진 상태에서
`injection_started → 60초 wait → incident_failed(PilotError) → flux_restored →
recovery_failed(RecoveryFailure)`다. `injection_verified`와 F8-t4 model call은 없다.
tracker ISS-058과 변경 이력 #94는 당시 production gRPC readinessProbe에 HTTP handler를
strategic merge하여 Kubernetes의 single-handler 제약을 위반했고, mutation이 없는데
generic rollout undo가 과거 F2 `exit 1` command revision을 골랐다고 기록한다. journal의
pre-fix receipt에 original readinessProbe가 봉인되지 않은 사실과 failure/recovery
경계가 이 설명과 일치한다. 이 campaign은 treatment와 recovery 두 gate를 모두
위반했다.

#### Primary03 — F9-t1 treatment 실패와 F8-t5 exact recovery 결손

F9-t1은 `recovery_receipt_sealed`에 fault/target/trial만 남긴 뒤 90초 후
`incident_failed(PilotError)`, exact Flux restore와 `recovery_green`으로 끝난다.
tracker ISS-059와 변경 이력 #95는 기존 `REDIS_ADDR.value=redis-cart:6379`에
`valueFrom.secretKeyRef`를 strategic merge하여 상호 배타 필드가 충돌했다고 기록한다.
또한 직전 F8-t5에서 추가 Service port 9999를 manifest apply가 exact 제거하지 못했다.
따라서 F8까지 39 incident가 commit됐더라도 campaign-level treatment/recovery
불변성을 충족하지 못한다.

#### Primary04 — Loki fail-open 수집과 운영자 중단

Primary04는 F6까지 30 incident를 commit한 뒤 F7-t1에서 20 attempt/charged call 후
`KeyboardInterrupt`, exact Flux restore, `recovery_green`으로 끝났다. 그러나 raw JSON을
incident 단위로 파싱하면 **F4-t3부터 F6-t5까지 연속 13 incident**에서
`runtime_signals.logs.pod_logs=[]`와 `k8s_events=[]`가 동시에 나타난다. 이 13건은
커밋된 30건의 43.3%다.

tracker ISS-060과 변경 이력 #96은 F4-t3가 Loki local-path PVC의 node를 방해한 뒤
30초 query timeout이 발생했지만 collector가 예외를 `[]`로 바꿔 정상 빈 로그처럼
commit했다고 기록한다. pre-fix raw에는 query success/failure receipt도 없어 빈 결과와
수집 실패를 구별할 수 없다. 따라서 lexical scanner와 LLM call provenance가 정상이더라도
공통 runtime evidence 자체가 불완전하며, 이 campaign은 data/provenance gate 위반이다.

### 1.5 condition, leakage, treatment, call provenance

커밋된 prefix만 감사했을 때 관찰된 사항은 다음과 같다.

| 검사 | Primary01 | Primary02 | Primary03 | Primary04 |
|---|---:|---:|---:|---:|
| row/raw key mismatch | 0 | 0 | 0 | 0 |
| duplicate 또는 3-condition 결손 incident | 0 | 0 | 0 | 0 |
| incident 내 runtime hash mismatch | 0 | 0 | 0 | 0 |
| incident 내 injection hash mismatch/결측 | 0 | 0 | 0 | 0 |
| raw scanner match 합계 | 0 | 0 | 0 | 0 |
| blind-RAG `query_origin != runtime_only` | 0 | 0 | 0 | 0 |
| blind/placebo generator input char/byte/proxy-token mismatch | 0/14 | 0/37 | 0/39 | 0/30 |
| logical call model/provider/tool provenance 위반 | 0/504 | 0/1,332 | 0/1,404 | 0/1,080 |
| logical session 결측/중복 | 0/0 | 0/0 | 0/0 | 0/0 |

이는 **커밋된 prefix 내부**에서 lexical leakage 0, paired runtime hash, length proxy,
condition mapping, session/tool isolation이 일관됐다는 뜻이다. 실패 incident와 campaign
완결성까지 통과했다는 뜻은 아니다. scanner 0은 semantic shortcut 부재의 증명도
아니다.

모든 최신 logical call은 provider `codex-cli-chatgpt-subscription`, requested/ledger
model `gpt-5.6-terra`, tool/MCP/remote/custom-instruction event 0을 기록했다. 다만
`experiments/shared/codex_cli.py`는 Codex JSON이 provider-reported model ID를 내보내지
않는다고 명시하고, 완료 receipt의 `actual_model`에 요청 model을 다시 쓴다. 따라서
여기서 “model mismatch 0”은 **command binding 검증**이지 backend model identity의
독립 확인이 아니다. 마찬가지로 `ai_credits=0.0`은 subscription monetary metric이
미보고라는 sentinel이며 실제 비용 0의 증거가 아니다.

사전 계획의 180건 human-primary review, second reviewer 36건 agreement, procedure
corpus의 4축 semantic audit 산출물은 artifact/results tree에서 발견되지 않았다.
강한 지지 판정에 필요한 human 방향 검증과 semantic leakage 보완 근거가 없다.

## 2. 통계 분석

### 2.1 Confirmatory 분석 불가

다음 계획 분석은 실행하지 않았다.

- 59-incident `Δ_primary`
- 12-fault cluster 50,000회 bootstrap 95% CI
- `2^12` exact fault-cluster permutation
- confirmatory incident-level McNemar exact test
- fault/category별 confirmatory accuracy와 mixed-effects model
- 180건 human-primary 재채점과 judge reliability calibration

이유는 단순 표본 부족이 아니라 **estimand dataset 부재**다. 최신 네 캠페인은 서로
다른 git commit이고 어느 것도 59 incidents를 완료하지 않았다. Primary04에는 이미
commit된 runtime evidence의 수집 실패까지 있다. 이를 concatenate하거나 common subset으로
재구성하면 계획서 `§7.1`, `§9.3`의 단일 campaign 규칙과 사전 지정 fault weighting을
위반한다.

### 2.2 캠페인별 prefix 운영 탐색 통계

아래 값은 각 campaign 내부의 커밋된 prefix만 따로 계산한 **exploratory/operational
diagnostic**이다. confirmatory effect estimate가 아니며 성공/기각 판정에 쓰지 않는다.
threshold 0.5에서 exact two-sided McNemar p는 discordant pair에 대한 exact binomial로
계산했다.

| campaign | 관측 fault 범위 | runtime | placebo | blind RAG | RAG-only / placebo-only | 탐색 Δ | exact p |
|---|---|---:|---:|---:|---:|---:|---:|
| Primary01 | F1–F2, F3 t1–t4; n=14 | 5/14 (35.7%) | 5/14 (35.7%) | 5/14 (35.7%) | 0 / 0 | 0.0%p | 1.0000 |
| Primary02 | F1–F7 유효, F8 t1–t3; n=37 | 21/37 (56.8%) | 21/37 (56.8%) | 19/37 (51.4%) | 2 / 4 | -5.4%p | 0.6875 |
| Primary03 | F1–F8; n=39 | 23/39 (59.0%) | 23/39 (59.0%) | 23/39 (59.0%) | 2 / 2 | 0.0%p | 1.0000 |
| Primary04 | F1–F6; n=30 | 18/30 (60.0%) | 19/30 (63.3%) | 16/30 (53.3%) | 2 / 5 | -10.0%p | 0.4531 |

threshold 민감도에서 RAG−placebo 탐색 Δ는 다음과 같다.

| campaign | 0.5 | 0.6 | 0.7 |
|---|---:|---:|---:|
| Primary01 | 0.0%p | -7.1%p | 0.0%p |
| Primary02 | -5.4%p | -2.7%p | -5.4%p |
| Primary03 | 0.0%p | 0.0%p | 0.0%p |
| Primary04 | -10.0%p | -3.3%p | -6.7%p |

어느 prefix도 threshold 0.5에서 양의 운영 신호를 보이지 않았다. 그러나 순차
schedule의 early-fault composition, invalid campaign, 반복된 early fault, same-model
judge 때문에 이 사실을 `H1` 기각으로 바꾸면 안 된다. 특히 Primary04 수치는 13개
runtime-log 결손 incident를 포함하므로 가장 덜 신뢰할 수 있다.

## 3. 비판적 회고

### 3.1 구성 타당성

긍정적인 부분은 독립변수를 `context_condition` 하나로 제한하고, runtime hash와
blind/placebo 길이 proxy를 실제 ledger에서 맞춘 점이다. 커밋된 raw scanner도 lexical
match 0을 기록했다.

그러나 측정 대상은 여전히 “causal reasoning”이 아니라 label/entity를 제거한 retrieved
procedure의 잔여 진단 효용이다. 계획서와 리뷰가 요구한
`label exposed / entity exposed / unique mechanism cue / generic procedure` 사람 semantic
audit 산출물이 없다. Primary01처럼 scanner lexicon 자체가 execution metadata를
treatment scalar로 오분류한 사례는 scanner 0/1이 곧 construct validity가 아님을
보여 준다.

또한 Terra generator와 Terra judge를 함께 사용했고 human-primary 결과가 없다.
`docs/papers/judging-llm-as-a-judge.md`는 GPT-4 위치 일관성 65.0%와 verbosity bias를,
`docs/papers/rating-roulette.md`는 3회 judge의 α가 task/model에 따라 0.265–0.788임을
기록한다. m=3 raw votes만으로 correlated self-evaluation bias가 제거되지 않는다.

### 3.2 내적 타당성

가장 큰 위협은 condition contrast보다 campaign lifecycle이다.

- 최신 네 campaign의 commit이 모두 다르다.
- F3-t5 scanner, F8-t4 probe/recovery, F9-t1 env recovery, Loki collector가 campaign
  사이에서 수정됐다.
- 순차 schedule이므로 중단 시 fault composition이 비무작위 prefix가 된다.
- Primary03의 Service exact restore 결손과 Primary04의 Loki fail-open은 다음 incident의
  runtime baseline까지 오염시킬 수 있다.
- Codex backend actual model은 command-bound일 뿐 provider-reported identity가 아니다.

따라서 “같은 provider/model 이름”만으로 campaign을 exchangeable replicate로 볼 수
없다. condition 순서 Latin square는 한 incident 안의 순서 교락을 줄이지만, 여러
날짜·revision의 campaign drift를 해결하지 않는다.

### 3.3 외적 타당성

설령 완결 결과가 있었어도 단일 KT Cloud 6-node cluster, Online Boutique, F1–F12
synthetic taxonomy, 한 corpus/masker, 한 Codex subscription serving 시점, incident 동안
Flux reconciliation을 suspend한 환경에 한정된다. production MTTR, active GitOps
reconciliation, 다른 LLM/provider, 다른 runbook 품질로 일반화할 수 없다.

`docs/papers/lost-in-the-middle.md`는 같은 증거도 위치에 따라 20%p 이상 달라질 수
있음을 기록한다. V2.3은 위치를 통제값으로 고정했으므로 position effect나 다른 context
layout에 관한 주장도 할 수 없다.

### 3.4 통계 타당성

2,124 logical calls는 표본 2,124개가 아니다. 추론 단위는 59 paired incidents이고
fault cluster는 12개뿐이다. 현재 prefix는 14–39 incidents와 3–8 fault에만 걸쳐 있어
사전 지정 equal-fault weighting과 12-cluster permutation을 재현하지 못한다.

계획서의 +10%p 기준과 CI 하한 >0은 유효한 complete dataset에서만 의미가 있다.
invalid prefix의 0 또는 음의 탐색 Δ, 유의하지 않은 exact p를 “효과 없음”으로 해석하면
low power와 measurement failure를 효과 부재로 혼동한다.

### 3.5 대안 가설과 선행연구 대비

관측된 종료 및 prefix 패턴은 최소 다음 대안으로 설명된다.

1. blind procedure가 reasoning을 돕지 않았을 수 있다.
2. procedure가 후보 공간을 좁히지만 same-model judge가 그 표현을 다르게 선호했을 수 있다.
3. neutral placebo와 procedure의 실제 tokenizer 길이·형식·명령 밀도가 달랐을 수 있다.
4. fault별 runtime evidence 품질, 특히 Loki fail-open이 condition 효과보다 크게 작용했을 수 있다.
5. provider serving drift와 서로 다른 git revision이 prefix 차이를 만들었을 수 있다.
6. sequential attrition 때문에 관측 fault set이 전체 taxonomy를 대표하지 않을 수 있다.

repo 선행연구는 효과를 낙관할 이유와 감사할 이유를 동시에 제공한다.

- `docs/papers/flow-of-action.md`: SOP knowledge 제거 시 54.06%→15.39%(-38.67%p).
  이는 structured knowledge의 잠재 기여이지 blind RAG의 순효과 예측값이 아니다.
- `docs/papers/auditable-graph-guided-rca.md`: entity F1 headline은 0.6087→0.9130이지만
  stripped 조건은 0.6958로 크게 축소된다. 누출/힌트 제거 후 효과를 다시 보아야 한다.
- `docs/papers/controlled-data-contamination-impact.md`: source-target 결합 오염은 최대
  30 BLEU inflation을 만들었다. test-time RAG leakage와 동일 현상은 아니지만 정답 결합
  노출이 능력보다 점수를 부풀릴 수 있다는 통제 원리가 적용된다.
- judge reliability와 context position 근거는 위 구성·외적 타당성 절의 수치와 같다.

즉 V2.3의 가장 방어 가능한 학술적 위치는 “blind RAG가 향상시켰다”가 아니라,
**RAG 효과를 주장하려면 lexical/semantic leakage, collector completeness, same-model
judge, single-campaign recovery를 함께 감사해야 한다**는 실패 분석이다.

## 4. 개선 가설

### 4.1 1순위 가설

> V2.3의 정보 손실을 지배한 것은 RAG 효과 크기가 아니라 campaign lifecycle과
> evidence-completeness gate의 불충분함이다. model 호출 전에 query-success receipt와
> desired-state exact recovery를 검증했더라면 invalid campaign을 더 이른 시점에
> 차단하고 장시간·호출 비용을 크게 줄였을 것이다.

근거는 최신 네 캠페인이 각각 14, 37, 39, 30 incident 후 서로 다른 harness/data
경계에서 멈췄고, complete campaign은 0이라는 사실이다. 이 가설은 RAG 정확도 가설과
다르며 운영 신뢰성 가설이다.

### 4.2 Primary05를 시작하지 않는 결정

**현재 Primary05를 시작하지 않는 것이 방법론적으로 정당하다.** 이유는 유망/불리한
효과를 보고 선택적으로 멈춘 것이 아니라, 사전 지정 complete-case gate를 한 번도
충족하지 못했고 최신 campaign에서 runtime evidence corruption까지 확인했기 때문이다.
이는 futility/quality stop이며 `H0` 채택이나 `H1` 기각이 아니다.

다만 조기 종료는 confirmatory 질문을 답하지 않는다. 논문에는 “가설 판정 불가”와
중단 이유를 명시해야 하며, prefix 효과를 성공/실패 수치로 제시해서는 안 된다.

### 4.3 비용 대비 정보가 큰 최소 후속 확인

전체 59-incident/2,124-call 재실행 대신 선택할 수 있는 최소 후속은 **새 model 호출이
없는 retrospective measurement audit**이다.

1. Primary03 하나만 선택하고 다른 campaign과 섞지 않는다.
2. outcome을 숨긴 deterministic hash 층화로 12 incidents × 3 conditions = 36 outputs를
   정한다.
3. blind human reviewer가 동일 rubric으로 재채점한다.
4. 같은 12 blind-RAG blocks에 4축 semantic shortcut rubric을 적용한다.
5. Terra judge 방향과 human 방향, semantic cue 빈도를 exploratory로만 보고한다.

이 확인은 적은 비용으로 same-model judge와 semantic leakage가 결론을 뒤집을 가능성을
평가한다. 그러나 incomplete campaign을 confirmatory dataset으로 승격시키지 못한다.
V2.3의 원래 causal effect를 논문 핵심 결과로 반드시 확보해야 한다면, **fresh complete
single campaign을 대체할 통계적 지름길은 없다**. 그 경우에만 먼저 model-free
59-incident lifecycle qualification을 완주한 뒤 새 main run 승인 여부를 결정해야 한다.

## 5. 결론·한계

### 5.1 가설 판정

계획서의 네 분류 중 최종 판정은 **판정 불가**다.

- 강한 지지 아님: complete Δ, CI, threshold 안정성, human 방향 검증이 없다.
- 방향 지지 아님: 유효 complete campaign의 양의 점추정이 없다.
- 기각 아님: invalid/nonrandom prefix의 0 또는 음의 값은 confirmatory 반증이 아니다.
- 판정 불가: leakage/treatment/recovery/campaign/provenance gate 위반이 실제 관측됐다.

### 5.2 논문에 쓸 수 있는 주장

- F7-t5를 제외한 현재 confirmatory schedule은 59 incidents/177 rows/2,124 calls다.
- 최신 네 Codex-provider campaign 모두 incomplete이며 서로 다른 revision이다.
- 커밋된 prefix의 row/raw/condition/call ledger 정합성은 높았지만 campaign-level
  leakage, mutation/recovery, evidence collection failure가 효과 추정을 막았다.
- lexical scanner 0만으로 semantic leakage 부재를 증명할 수 없다.
- long-running LLM RCA evaluation에서 fail-closed collector receipt와 exact recovery가
  통계 분석 이전의 필수 측정 조건이다.
- 품질/운영 futility에 근거한 조기 종료는 정당하지만 연구 가설은 미해결이다.

### 5.3 논문에 쓸 수 없는 주장

- blind procedural RAG가 placebo보다 향상되거나 악화됐다는 confirmatory 주장
- 최신 네 campaign prefix를 합친 효과, CI 또는 p-value
- V2.2 대비 V2.3 절대 정확도 향상/하락: V2.2는 `gpt-4o-mini`, V2.3은
  command-bound Terra와 다른 provider다.
- scanner 0을 근거로 한 semantic leakage 0 주장
- ledger `actual_model`을 provider-reported backend model identity로 표현하는 주장
- subscription `ai_credits=0.0`을 실제 비용 0으로 표현하는 주장
- 다른 cluster, production MTTR, active GitOps, 다른 모델로의 일반화

### 5.4 남은 한계

이 분석은 보존된 artifact와 repo 정본만 감사했다. provider 내부 model identity와
serving revision은 관측할 수 없고, Primary02/03의 Kubernetes API 원문 stderr는
campaign journal에 보존되지 않아 tracker·receipt shape·event boundary로 원인을
교차검증했지만 오류 문자열 자체를 artifact에서 재구성할 수는 없다. Primary04의 빈
로그 13건은 직접 확인했지만 pre-fix raw에 query-status receipt가 없어 개별 timeout
시각은 tracker의 실행 기록에 의존한다. 이 한계들은 효과 판정을 더 보수적으로 만드는
방향이다.
