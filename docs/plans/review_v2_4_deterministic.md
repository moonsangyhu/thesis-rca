# V2.4-D 결정론적 RCA 채점 계획 독립 방법론 비평

> 검토일: 2026-08-31
>
> 단계: Experiment Track Step 2 — fresh methodology review
>
> 검토 범위: `experiment_plan_v2_4_deterministic.md`, 선행 deep analysis,
> `results/ground_truth.csv`, repository 실험/에이전트 규칙
>
> 독립성 선언: 이 검토에서는 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 scorer도 실행하지 않았다. 관찰된 arm별 score·표현·alias coverage를 전혀 사용하지 않았다.

## 0. 결론

**수정 요구(승인 거부)**다.

ground truth 12행의 canonical incident·target·fault·mechanism·recovery를 plan 표로 옮긴
기본 대응과 paired exact 통계 설계는 대체로 타당하다. 그러나 현재 matcher는 canonical
ontology보다 훨씬 넓다. 특히 (1) component의 단순 언급을 culprit localization으로 계산하고,
(2) FA에 mechanism/symptom alias를 섞으면서 다른 일곱 family를 모두 contradiction으로 삼고,
(3) 명시된 negation test를 일반적으로 구현하지 못하며, (4) Unicode tokenization과 ASCII regex
경계가 충돌한다. 이 네 문제는 primary `JRA-D` 자체를 바꿀 수 있으므로 P0다.

또한 현재 Step 2 review 시점에는 ontology/scorer/test가 아직 없으므로 그 구현물까지 승인하는
것은 불가능하다. ground-truth digest와 승인 문서가 포함된 **candidate 접근 전 두 번째 frozen
bundle review**가 필요하다. 아래 P0를 고치고 재검토하기 전에는 candidate scoring을 실행하면
안 된다.

## 1. 검토한 사실과 범위

- 선택 incident 12개는 plan과 ground truth에서 동일하다:
  `F1-t2`, `F1-t3`, `F2-t1`, `F3-t3`, `F3-t4`, `F4-t1`, `F5-t2`, `F5-t3`,
  `F6-t5`, `F7-t1`, `F7-t3`, `F8-t3`.
- 이 12행의 target component, `fault_name`, `expected_root_cause`,
  `expected_recovery_action`을 직접 대조했다.
- candidate artifact의 위치를 탐색하거나 본문을 읽지 않았다. 따라서 아래 alias 평가는 오직
  ground truth와 plan 문구의 의미·대칭성에 근거한다.
- scorer, analyzer, ontology 구현 파일과 candidate score는 검토 범위 밖이며 실행하지 않았다.

## 2. Ground truth 대 ontology 대응

### 2.1 Canonical 의미 대응

| incident | ground-truth 핵심 | plan canonical/path 대응 | 판정 |
|---|---|---|---|
| F1-t2 | recommendationservice, OOMKilled, 24Mi limit/OOM, 96Mi 증가 | target·fault·mechanism·96Mi recovery 일치 | PASS |
| F1-t3 | checkoutservice, OOMKilled, 16Mi limit/OOM, 64Mi 증가 | 일치 | PASS |
| F2-t1 | paymentservice, CrashLoopBackOff, corrupted entrypoint/startup exit | 일치 | PASS |
| F3-t3 | productcatalogservice, ImagePullBackOff, registry typo/DNS | 일치 | PASS |
| F3-t4 | checkoutservice, ImagePullBackOff, invalid digest | 일치 | PASS |
| F4-t1 | worker01, NodeNotReady, kubelet stopped | 일치 | PASS |
| F5-t2 | prometheus, PVCPending, 500Gi/capacity | 일치 | PASS |
| F5-t3 | loki, PVCPending, local-path provisioner deleted/unavailable | core mechanism 일치. recovery의 generic `redeploy`는 GT보다 넓음 | P1 |
| F6-t5 | redis-cart, NetworkPolicy, cartservice→redis-cart:6379 ingress block | target·route·port 일치 | PASS |
| F7-t1 | frontend, CPUThrottle, 10m limit/throttling, 200m 또는 limit 제거 | 일치 | PASS |
| F7-t3 | productcatalogservice, CPUThrottle, 5m limit/throttling, 100m 증가 | 일치 | PASS |
| F8-t3 | paymentservice, ServiceEndpoint, app label 제거/empty endpoints | 일치 | PASS |

Canonical 표의 전사는 정확하다. 그러나 **canonical 전사 일치와 matcher의 구성 타당성은 다른
문제**다. 아래 operational alias는 ground truth가 말하지 않은 표현까지 정답으로 만들거나,
ground truth와 양립하는 표현을 contradiction으로 제거한다. 따라서 “ontology가 ground truth와
exact 일치한다”는 전체 P0는 현재 FAIL이다.

### 2.2 Alias 과포괄·과소포괄과 incident 비대칭

1. `FT_CRASHLOOP`의 `startup crash`, `FT_NODENOTREADY`의 `kubelet unavailable`,
   `FT_PVCPENDING`의 `volume provisioning failed`, `FT_SERVICEENDPOINT`의
   `selector mismatch/no endpoints`, `FT_CPUTHROTTLE`의 `container cpu limit too low`는
   canonical fault label의 철자·형태 변형이 아니라 mechanism 또는 symptom이다. MCA와 FA가
   서로 다른 구성을 측정한다는 설계를 약화시키며 일부 family만 더 쉽게 만든다.
2. 반대로 FA contradiction을 “자기 group을 제외한 나머지 7개 전부”로 두면 올바른 계층적
   병기까지 탈락할 수 있다. 예를 들어 OOM으로 반복 재시작되는 상태에서 OOM과 crash-loop를
   함께 쓰거나, service endpoint 장애의 downstream connection/DNS 증상을 병기하는 것은
   반드시 competing root fault 주장이 아니다. 현재 정책은 **상호 배타적 원인**과
   **동반 상태/영향**을 구분하지 않는다.
3. family마다 alias 추상화 수준이 다르다. OOM은 상태·원인 phrase가 섞이고, NodeNotReady는
   kubelet mechanism만으로도 통과하며, F3은 pull failure 상태를 요구한다. 이는 incident별
   난이도 비대칭이고 condition 효과와 상호작용할 수 있다.
4. 영어 alias만 지원하는 것은 frozen upstream output의 언어가 사전 고정돼 있지 않다면
   과소포괄이다. candidate를 보아 alias를 늘려서는 안 되지만, upstream 생성 계약에서 출력
   언어가 영어로 고정됐다는 metadata 근거를 freeze bundle에 넣거나 언어 제한을 명시해야 한다.

**필수 수정:** FA alias는 canonical `fault_name`의 정규화·널리 인정되는 orthographic variant로
축소한다. mechanism/symptom은 MCA에만 남긴다. contradiction은 다른 family 문자열의 단순 존재가
아니라 사전 정의한 mutually-exclusive fault assertion에만 적용하거나, 이 구분이 불가능하면
FA를 “fault-family lexical mention”으로 이름을 낮추고 JRA/Cloud-OpsBench localization 주장을
철회한다. 어느 선택도 candidate 본문을 보고 결정하면 안 된다.

## 3. 구성 타당성

### 3.1 Component culprit-role — P0 FAIL

CA는 `root_cause` 안에 canonical component token이 한 번이라도 있으면 통과한다. 하지만
`root_cause`는 dedicated `root_cause_component` field가 아니라 자유서술이다. canonical service가
피해 대상, 호출자, dependency 또는 배제된 대안으로 언급돼도 CA가 1이 될 수 있다. F6-t5는 특히
정답 문장 자체가 cartservice와 redis-cart 두 component를 필수로 포함하므로 “어느 component가
culprit인가”라는 질문이 단순 membership으로 해결되지 않는다.

이는 작은 label 문제가 아니다. `JRA-D = CA ∧ FA ∧ MCA`의 primary gate 하나가 실제
localization이 아니라 mention recall이므로 Cloud-OpsBench의 Component Accuracy와 동일한 구성으로
해석할 수 없다.

**필수 수정 선택지:**

- candidate schema에 독립 `root_cause_component` field가 이미 동결돼 있지 않으므로 새 parsing을
  사후 도입하지 말고, CA를 `CM`(canonical component mention)으로 재명명해 primary와 모든 주장을
  “field-isolated lexical concordance”로 한정한다. 또는
- candidate 독립적인 finite role grammar와 positive/negative synthetic cases를 사전등록해
  culprit assertion만 통과시키고 affected/dependency/negated mention을 거부한다.

후자가 신뢰성 있게 고정되지 않으면 첫 번째가 더 정직하다.

### 3.2 Mechanism과 remediation

- MCA의 incident-specific conjunction은 대체로 ground truth mechanism을 충실히 분해한다.
- F6의 route 양끝·port까지 요구하는 것과 F8의 selector/label/endpoints를 모두 요구하는 것은
  다른 incident보다 더 많은 atom을 요구한다. ground truth 복잡성 차이이므로 그 자체는 오류가
  아니지만 fault별 rate를 직접 난이도 비교로 해석하면 안 된다.
- remediation DNF를 JSON의 별도 complete paths로 전개한다는 규칙은 명확하다. F5-t3의
  `redeploy`와 F1/F7의 generic `higher/sufficient limit`는 exact expected action보다 넓으므로
  secondary RA의 semantic acceptance set이라는 근거를 plan에 따로 기록해야 한다.
- remediation group을 여러 list item에 걸쳐 결합하면 서로 다른 권고의 우연한 bag-of-words가
  한 path를 완성할 수 있다. 최소한 한 accepted path의 action·target·desired-state는 동일 item에
  있어야 한다. 그렇지 않으면 “increase unrelated X” + “memory limit note” 같은 cross-item join이
  가능하다. 이 변경은 DNF test에 포함해야 한다.

## 4. 내적 타당성

### 4.1 Negation scope — P0 FAIL

계획의 “직전 3 token” 규칙은 test 9의 한 예문만 우연히 통과할 뿐 coordinated negation을
일반적으로 정의하지 않는다.

- `no cpu throttling or memory pressure`에서 `memory pressure` 시작 전 3 token에는 `no`가 없어
  두 번째 conjunct가 살아남는다.
- `not a cpu or memory issue`도 두 번째 concept까지 `not`이 도달하지 않을 수 있다.
- `network policy was ruled out`, `OOMKilled is not the cause`처럼 postposed negation은 concept 뒤에
  있으므로 전혀 suppress되지 않는다.
- `no evidence of X`와 “absence assertion”의 `no endpoints`를 같은 local window로 처리하면
  장애 부재 주장과 장애 상태 자체를 구분하는 규칙이 phrase 목록에 과도하게 의존한다.

이 결함은 positive와 contradiction 양쪽에 비대칭 오분류를 만들 수 있다.

**필수 수정:** negation grammar의 scope를 token index로 명시한다. 최소한
(a) preposed negator의 coordinated NP/VP 전파 종료점, (b) `X ... ruled out/not the cause` 같은
postposed pattern, (c) clause boundary, (d) `not only`, (e) absence assertion 우선순위를 정의하고
각각 positive와 contradiction에서 대칭 test를 둔다. 단순 window를 유지하려면 coordinated
negation을 지원한다고 주장하지 말고 해당 문형을 fail-closed/INVALID로 탐지해야 한다.

### 4.2 Contradiction precedence

positive와 contradiction이 동시에 있으면 0이라는 precedence 자체는 명확하고 보수적이다.
그러나 contradiction lexicon의 phrase가 원인 주장인지 영향·대안인지 판단하지 못하는 문제가
남는다. negation P0와 FA family policy를 수정한 뒤에야 PASS 가능하다.

### 4.3 비결정성·선택·교란

- frozen paired outputs를 동일 scorer로 재채점하므로 모델 비결정성·cluster 시간대는 이번
  retrospective comparison에 새로 들어오지 않는다.
- 같은 12 incidents와 frozen representative-selection을 쓰는 pairing은 적절하다.
- 다만 representative-selection bias는 고정됐을 뿐 제거되지 않았다. 결과는 V2.3 전체 campaign
  또는 새 generation에 일반화할 수 없다.
- condition별 문체가 lexical matcher hit rate를 바꾼다는 대안 가설은 여전히 강하다. relaxed
  sensitivity와 axis matrix는 이를 진단할 뿐 제거하지 않는다.

## 5. Regex·parser safety — P0 FAIL

계획은 tokenization을 “maximal Unicode alphanumeric runs”로 정의하면서 regex 경계를
`[0-9a-z]`로만 강제한다. 따라서 ASCII 밖의 Unicode alphanumeric이 alias에 붙은 경우 regex가
token 내부 substring을 match할 수 있다. literal과 regex의 boundary semantics가 서로 다르다.

현재 두 regex는 명백한 catastrophic backtracking 구조는 아니지만, `re.search`를 허용하는 schema와
“모든 pattern은 ASCII boundary를 포함” 규칙만으로는 future pattern safety가 보장되지 않는다.
field size 상한, regex AST/construct allowlist, compile failure 처리도 없다.

**필수 수정:** regex도 tokenizer가 산출한 token span 경계에서만 평가하도록 만들고 raw ASCII
lookaround를 정본으로 삼지 않는다. 가능하면 현재 두 패턴을 token-sequence predicate로 바꾼다.
regex를 유지하면 Unicode alphanumeric boundary, 입력 byte/token 상한, pattern length,
backreference/lookaround/nested-repeat 금지, compile error fail-close를 schema와 test에 고정한다.

## 6. 통계 타당성

### 6.1 Primary exact test — PASS

- `b=RAG-only`, `c=placebo-only` 정의와
  `Pr[X>=b | X~Binomial(b+c, 0.5)]`는 사전 방향의 exact one-sided McNemar 검정으로 맞다.
- `b+c=0 → p=1`, known-answer `5/0 → 0.03125`, `4/0 → 0.0625`,
  `0/5 → 1`도 맞다.
- one-sided 방향은 ontology freeze 전에 가설로 고정됐고 n=12 한계를 명시했다.
- primary outcome/comparison 하나만 confirmatory로 둔 것도 적절하다.

### 6.2 Interval — PASS with limitations

- discordant dominance `q=b/(b+c)`의 two-sided 95% Clopper–Pearson은 조건부 discordance 방향의
  exact interval로 적절하다. 이를 전체 incident의 RD CI나 효과 일반화 CI로 부르면 안 된다.
- incident pair bootstrap으로 RD percentile CI를 계산하는 절차는 기술적 불확실성 표시로
  재현 가능하다. n=12에서 coverage가 보장되는 exact CI가 아니며 이미 그 경계를 명시했다.
- byte replay를 주장하려면 NumPy/Python 버전 “기록”만 하지 말고 실행 환경 또는 lock/hash를
  freeze해야 한다. 그렇지 않으면 같은 seed라도 library 변경에 따른 percentile serialization
  차이를 재현성 실패와 구분하기 어렵다.

### 6.3 Multiplicity와 primary status — P1

- secondary p-value를 “생성한다면” Holm family로 묶는 선택적 문구는 분석자 재량을 남긴다.
  사전에 secondary inferential tests를 0개로 고정하거나 exact 목록과 family를 고정해야 한다.
- `FULL` 저하가 primary `JRA-D` 가설을 사후 뒤집지 않는 것은 맞다. 그러나
  `SUPPORTED_WITH_REMEDIATION_WARNING`을 별도 status처럼 쓰면 §11의 primary enum과 충돌한다.
  출력은 `primary_status=SUPPORTED`와
  `remediation_regression_flag=true` 두 필드로 분리하고 합성 label은 presentation-only로 명시한다.
- remediation warning이 있어도 “RCA 전반 개선”이라고 쓰면 안 된다. 허용 결론은 이 표본의
  `JRA-D` lexical outcome 우세뿐이다.

## 7. 외적 타당성과 대안 가설

외적 타당성은 매우 제한적이다. 12 incidents는 F1~F8의 incomplete, non-random prefix이며 단일
Online Boutique/단일 upstream generation pipeline이다. public benchmark taxonomy를 참고했다는
사실은 다른 cluster·fault·언어·운영 환경에 대한 외적 검증이 아니다.

결과가 유리해도 다음 대안 가설을 배제하지 못한다.

1. RAG가 reasoning을 개선한 것이 아니라 canonical vocabulary 사용 빈도를 높였다.
2. procedural context가 root-cause field의 문장 구조와 길이를 바꿔 alias conjunction을 쉽게 했다.
3. representative-selection rule이 condition별 출력 분포를 다르게 축약했다.
4. broad FA/RA alias 또는 component mention gate가 condition별 verbosity를 보상했다.
5. 12개의 우연한 discordance가 방향을 만들었고 전체 59 incidents에서는 재현되지 않을 수 있다.

따라서 결과 명칭은 “frozen 12-incident lexical JRA-D agreement” 범위를 넘으면 안 되며, 후속
external replication/live recovery는 별도 사전등록 실험이어야 한다.

## 8. Hash freeze·opaque commitment·clean checkout — P0 FAIL

방향은 좋지만 현재 순서는 결과 독립성을 완전히 봉인하지 못한다.

1. 이 review는 ontology/scorer/test 구현 전에 작성된다. 아직 존재하지 않는 파일의 exact
   semantics와 test 통과를 승인할 수 없다. plan review와 implementation freeze review를
   분리해야 한다.
2. ground truth는 실행 시 hash를 “기록”한다고만 되어 있고 approval bundle의 고정 입력 목록에는
   명확히 포함되지 않는다. repository 불변 정책만으로는 어느 revision의 ground truth인지
   충분하지 않다.
3. approval 문서가 frozen commit에 포함돼야 한다는 조건이 불명확하다. detached checkout은
   반드시 사용자 승인 기록을 포함한 exact commit이어야 한다.
4. opaque commitment는 파일 byte를 hash-only로 읽는 절차로서 타당하지만, digest만으로는 사람이
   별도 명령으로 본문을 보지 않았음을 증명하지 못한다. 최소한 commitment 생성 도구 자체의 hash,
   stdout/stderr redaction test, 실행 명령/exit status, 접근자 자기선언을 approval provenance에
   남겨야 한다. 이를 cryptographic proof라고 표현하면 안 된다.
5. `env -i`만으로 Python user-site/sitecustomize와 interpreter/dependency가 고정되지 않는다.
   `python -I`, exact interpreter hash 또는 locked environment, `PYTHONHASHSEED`, locale availability를
   고정해야 replay 의미가 명확하다.
6. source root symlink 거부 외에도 각 raw entry를 no-follow `lstat`으로 regular file인지 확인하고,
   path traversal·hard-link/TOCTOU를 막아야 한다. preflight hash 이후 같은 open file descriptor 또는
   재-hash로 scoring input 불변을 확인해야 한다.

**필수 수정된 gate 순서:**

1. 현재 semantic plan review의 P0 수정.
2. candidate 비접근 상태에서 ontology/scorer/analyzer/test와 hash-only commitment 도구 구현.
3. plan, review, ontology, code, tests, input commitment, **ground-truth 전체 hash와 선택 12행의
   canonical projection hash**를 commit.
4. fresh reviewer가 구현과 synthetic tests를 candidate 없이 두 번째 검토하고 P0 PASS 기록.
5. 사용자 승인 문서를 생성해 그 문서까지 포함한 commit을 freeze.
6. 그 exact commit의 detached clean checkout에서만 scoring. checkout commit이 승인 commit과
   동일하지 않으면 INVALID.

## 9. P0 gate 표

| P0 gate | 판정 | 근거/필수 조치 |
|---|---|---|
| candidate 본문 비열람 독립 review | PASS | 이 검토에서 candidate 본문 접근·검색·출력과 scorer 실행 0 |
| 12 incident canonical truth 전사 | PASS | target/fault/mechanism/action core를 ground truth와 대조 |
| ontology matcher가 ground truth와 exact 대응 | **FAIL** | FA mechanism alias, generic RA, component mention으로 acceptance set이 GT보다 넓음 |
| CA/component culprit-role 구성 타당성 | **FAIL** | 자유서술 root_cause의 단순 mention은 localization이 아님 |
| FA alias 대칭성과 contradiction 정책 | **FAIL** | family별 추상화 수준 불균형, 다른 7 family 일괄 모순은 동반 상태까지 배제 |
| MCA incident-specific mechanism | PASS | 선택 12행의 핵심 mechanism conjunction은 GT와 일치 |
| remediation DNF 의미 | **FAIL** | DNF 전개는 명확하나 multi-item cross-join과 broad path를 제한해야 함 |
| negation/absence/coordinated scope | **FAIL** | 3-token pre-window가 coordinated·postposed negation을 일반적으로 처리하지 못함 |
| contradiction precedence의 기계적 명확성 | PASS | positive+affirmative contradiction→0은 명확; lexicon 타당성은 별도 FAIL |
| regex/tokenizer safety와 동치 | **FAIL** | Unicode alnum tokenizer와 ASCII boundary 불일치, input/pattern safety gate 부족 |
| exact one-sided McNemar | PASS | b/c 방향·tail·zero-discordance·known answers 정확 |
| bootstrap/Clopper–Pearson 보고 | PASS | estimand 구분과 small-n 한계가 명시됨; environment freeze는 P1 보완 |
| primary status와 remediation warning 분리 | PASS 조건부 | 논리는 타당; machine field 두 개로 분리해야 함 |
| missingness fail-close | PASS | imputation/complete-case 대체 금지 명확 |
| multiplicity 사전 고정 | **FAIL** | secondary test를 할지 여부가 분석자 재량으로 남음 |
| hash freeze/opaque commitment/clean checkout | **FAIL** | GT hash·approval commit·두 번째 implementation review·runtime isolation 보완 필요 |
| 주장·외적 타당성 경계 | PASS | lexical, frozen 12 incidents, non-production 한계를 명시 |

P0는 하나라도 FAIL이면 scoring package 승인 불가다.

## 10. P1 보완사항

1. F5-t3 `redeploy`와 generic `higher/sufficient limit`이 exact GT action보다 넓은 이유를
   ground-truth-derived semantic equivalence로 문서화하거나 제거한다.
2. DNF path의 group 충족을 같은 remediation item 안으로 제한한다. 여러 item 결합이 꼭 필요하면
   incident별 허용 group partition을 사전등록한다.
3. FA·MCA·RA alias별 provenance를 `ground_truth column/row` 또는 public taxonomy source로
   기계 판독 가능하게 ontology에 넣는다. “왜 이 alias가 있는가”를 candidate와 무관하게 감사할 수
   있어야 한다.
4. fault별 atom 수와 alias 수를 표로 보고해 matcher 난이도 비대칭을 공개한다. 이를 결과에 맞춰
   균등화하지 않는다.
5. bootstrap environment와 canonical float serialization을 고정한다.
6. exploratory test 목록을 고정하고 생성하지 않을 test는 명시적으로 금지한다.
7. `primary_status`와 `remediation_regression_flag`를 summary schema에 별도 required field로 둔다.

## 11. 최종 판정과 다음 checkpoint

**최종 판정: 수정 요구 — Step 3 실데이터 적용 및 candidate 접근 승인 안 함.**

다음 checkpoint는 plan/ontology 계약에서 위 P0를 수정한 뒤, candidate 비접근 상태의 fresh
재검토다. 특히 component 축을 실제 culprit localization으로 만들지 못한다면 `CA/JRA-D` 명칭과
Cloud-OpsBench 호환 주장을 낮추는 것이 필수다. 이후 구현 bundle이 만들어지면 별도의 두 번째
review에서 ontology JSON이 이 계약과 byte-level로 일치하는지, synthetic negation/DNF/regex/hash
tests가 실제로 통과하는지를 확인해야 한다.

이 문서는 결과를 보지 않은 방법론 비평이며, 어떤 condition이 우세할지 예측하거나 암시하지 않는다.

---

## 12. Revision 2 재검토

> 재검토일: 2026-08-31
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 2
>
> 검토 plan SHA-256:
> `e9a5cba9c0ab539f75fbe8e3544c5613807dbf3d66b03564dc2232fb8ac22afc`
>
> 독립성 재선언: Revision 2 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 scorer를 실행하지 않았다. 허용된 ground truth와 plan만 사용했다.

### 12.1 재검토 결론

**수정 요구 유지(Revision 2 승인 거부)**다.

Revision 2는 최초 review의 구성 타당성·alias·regex·RA·통계 P0를 실질적으로 해결했다.
`JRA-D/CA/FA`를 `JLC-D/CM/FLM`으로 낮추고 Cloud-OpsBench 호환 주장을 철회한 것은 충분하다.
FLM을 orthographic-only로 제한하고 contradiction을 비운 것, raw regex를 제거한 것, RA를
same-item DNF로 바꾼 것, secondary inference를 0으로 고정한 것도 적절하다.

그러나 candidate 접근 전 hard gate에 새 P0 세 개가 남는다.

1. coordinated-negation 핵심 synthetic test의 두 번째 phrase인 `memory pressure`가 Revision 2
   ontology concept에서 제거됐다. 따라서 그 test는 두 번째 conjunct suppression을 검증하지
   못한다.
2. implementation review PASS **후** bundle commit `B`를 만든다는 순서는 reviewer가 확인한
   working tree와 실제 `B` 사이의 변경 가능성을 봉인하지 못한다.
3. plan은 semantic 재검토를 별도 `review_v2_4_deterministic_r2.md`에 기록하도록 요구하지만,
   이번 작업의 승인된 정본은 기존 `review_v2_4_deterministic.md`에 최초 기록을 보존하고
   Revision 2 섹션을 append하는 방식이다. 현재 그대로면 commit `B` required bundle에 존재하지
   않는 r2 파일을 요구하거나, 실제 review artifact를 잘못 식별한다.

이 세 항목은 scoring 전 수정할 수 있고 결과 방향과 독립적이지만, 현재 plan의 exact hard gate를
그대로 승인할 수는 없다.

### 12.2 최초 P0/P1 재판정

| 최초 gate | Revision 2 판정 | 재검토 근거 |
|---|---|---|
| candidate 본문 비열람 독립 review | PASS | 두 차례 review 모두 candidate 본문 접근·검색·출력과 scorer 실행 0 |
| 12 incident canonical truth 전사 | PASS | canonical mapping 유지 |
| ontology matcher가 ground truth와 exact 대응 | PASS | CM/FLM 주장 하향, FLM orthographic-only, broad numeric/RA alias 제거, provenance 계약 추가 |
| CA/component culprit-role 구성 타당성 | PASS | CA/localization을 폐기하고 CM token mention으로 명시적으로 낮춤 |
| FA alias 대칭성과 contradiction 정책 | PASS | FLM case/separator variant만 허용하고 전 incident `contradictions=[]` |
| MCA incident-specific mechanism | PASS | incident별 mechanism conjunction 유지, competing-role phrase contradiction 제거 |
| remediation DNF 의미 | PASS | accepted path의 모든 group과 RA contradiction을 동일 item 안에서만 완성 |
| negation/absence/coordinated scope | **FAIL** | finite grammar/fail-close 방향은 적절하나 coordinated test가 제거된 concept를 사용해 핵심 branch를 검증하지 못함 |
| contradiction precedence | PASS | CM/FLM/MCA contradiction 제거, RA의 same-item affirmative opposite action만 precedence 적용 |
| regex/tokenizer safety와 동치 | PASS | raw regex 제거, 유일한 finite token predicate와 input/token/language 상한 고정 |
| exact one-sided McNemar | PASS | 정의·tail·known-answer 유지 |
| bootstrap/Clopper–Pearson | PASS | CP estimand 유지, stdlib RNG·linear percentile·float serialization 고정 |
| primary status/remediation warning 분리 | PASS | machine-readable 두 required field, 합성 status 금지 |
| missingness fail-close | PASS | parse/schema/hash/identity/language/negation 실패 전체 INVALID |
| multiplicity 사전 고정 | PASS | secondary/exploratory inferential test와 CI를 0으로 고정 |
| hash freeze/opaque commitment/clean checkout | **FAIL** | GT commitment는 PASS지만 implementation review→B 사이 exact tree 봉인이 없음 |
| 주장·외적 타당성 경계 | PASS | JLC-D lexical outcome, non-semantic/non-production 경계가 명확 |

### 12.3 요청 항목별 상세 판정

#### JLC-D/CM/FLM 주장 하향 — PASS

- `CM`은 canonical component의 token mention이며 culprit role/localization이 아니라고 명시했다.
- `FLM`은 canonical fault label mention이며 classification accuracy가 아니라고 명시했다.
- `JLC-D`를 Cloud-OpsBench CA/FA/JRA compatible extension이나 semantic correctness로 부르는 것을
  금지했다.
- 허용 결론도 frozen 12 incidents의 lexical concordance에 한정됐다.

따라서 최초 component culprit-role P0는 metric 이름을 낮추는 방식으로 적절히 해결됐다.

#### FLM orthographic-only와 contradictions=[] — PASS

여덟 FLM group은 ground-truth `fault_name`의 case와 separator 결합/분리만 허용한다.
`startup crash`, `kubelet unavailable`, `no endpoints`, `container cpu limit too low` 같은
mechanism/symptom alias가 제거됐다. 다른 family label의 단순 병기는 competing assertion인지
판별할 finite grammar가 없다는 이유로 전 incident contradiction을 비운 것도 CM/FLM의 낮아진
구성과 일치한다.

#### Finite negation/fail-close — FAIL

`PRE_DIRECT`, `PRE_COORD`, `PRE_RULE`, `POST_RULE`, `POST_CAUSE`, clause/contrast 종료,
absence assertion, `not only`, grammar 밖 negation의 `UNSUPPORTED_NEGATION` fail-close는 최초
3-token window보다 훨씬 명확하다. 다만 다음을 고쳐야 PASS다.

1. synthetic test 9의 `no cpu throttling or memory pressure`에서 `memory pressure`는 Revision 2의
   matcher group이 아니다. 두 번째 `C`가 존재하지 않아 `PRE_COORD`의 연장 suppression을 검증하지
   못한다. 두 conjunct가 모두 실제 ontology concept인 예문, 예를 들어
   `no cpu throttling or memory limit`, 그리고 두 positive span이 모두 suppress됐다는 assertion으로
   교체해야 한다.
2. step 12는 `not only`처럼 exception으로 소비된 marker가 있을 때 같은 clause의 다른 concept를
   모두 미분류로 간주하는지 모호하다. “소비 후 남은 unresolved negation marker와 그 scope 후보가
   있을 때만 fail-close”인지, “marker가 있던 clause의 모든 concept를 분류”하는지 하나로 고정하고
   `not only C1 but C2` test를 추가해야 한다.
3. JSON Schema의 `negation.window_tokens/tokens/phrases`는 revision 1 형태를 유지하며 arbitrary
   array를 허용한다. implementation validator가 §7의 exact token/phrase/grammar 상수를 강제한다는
   조건을 schema 또는 synthetic static validation에 명시해야 한다.

첫 번째는 coordinated negation P0의 실제 반증 test가 비어 있다는 뜻이므로 구현 review로
미룰 수 없다.

#### Regex 제거/token predicate — PASS

raw regex, wildcard, substring, fuzzy match를 금지하고
`MEMORY_LIMIT_EXCEEDED_V1`의 아홉 token sequence만 허용했다. ASCII 밖 alphanumeric과 input
크기를 fail-close하며 literal과 predicate가 동일 token boundary를 쓰므로 최초 Unicode/ASCII
boundary 충돌은 제거됐다.

#### Same-item RA — PASS

positive path 전체와 반대 action contradiction 모두 하나의 `remediation[]` item 안에서 완성돼야
한다. F1/F7 generic sufficient-limit과 F5-t3 generic redeploy도 제거됐다. DNF cross-item join과
acceptance-set 과포괄 P0/P1은 해결됐다.

#### Secondary inference 0 — PASS

confirmatory test는 RAG 대 placebo JLC-D exact one-sided McNemar 하나다. runtime, CM, FLM, MCA,
RA, FULL, relaxed, fault matrix는 count/rate/difference만 허용하며 secondary p-value, CI,
Cochran Q를 모두 금지했다. multiplicity 재량이 남지 않는다.

#### Ground-truth projection hash — PASS

candidate와 scorer 없이 repository ground truth만 읽어 projection을 독립 재계산했다.

```text
selected rows       12
projection bytes    3318
projection SHA-256  be456f903354d581ae66c8f7051ea271a9add2cb7b6a58e28d1d768aaee57b1b
full GT SHA-256     d00115766dbfaa844b5325ff60aac8170b83689ccf2f2d2cd427faad9f8115c6
```

네 값 모두 Revision 2와 exact 일치한다. projection field, numeric F/trial sort, canonical JSON
serialization도 재현됐다.

#### Two-stage review/approval commit — FAIL

semantic review와 implementation review를 분리하고, approved bundle `B`와 approval-document
commit `A`를 분리한 발상은 타당하다. `A`가 approval 문서의 `B`를 ancestor로 가져야 한다는
검사도 self-reference를 피한다. 그러나 exact freeze에는 다음 보완이 필요하다.

1. implementation files와 commitment를 먼저 implementation candidate commit `I`로 봉인한다.
2. fresh reviewer는 exact `I`를 detached clean checkout에서 검토하고 review 문서에 `I`와
   검토 대상 파일 SHA-256를 기록한다.
3. commit `B`는 `I`에 implementation review 문서만 추가해야 한다. `git diff I..B`가 그 review
   파일 하나뿐이고 review에 기록된 file hash가 `B` tree와 일치하지 않으면 INVALID다.
4. 사용자에게 `B`를 승인받고 approval 문서만 추가한 `A`를 만든다. `git diff B..A`도 approval
   문서 하나뿐이어야 한다.

현재처럼 uncommitted 구현을 review한 뒤 `B`를 만들면 review와 commit 사이의 변경을 검출할
기준점이 없다.

또한 semantic review artifact의 exact 경로를 현재 정본으로 맞춰야 한다. 이번 재검토는 사용자
지시에 따라 최초 FAIL 기록을 보존한 같은 파일의 이 섹션에 기록됐다. 따라서 plan §9.1, §12와
bundle 목록의 `review_v2_4_deterministic_r2.md`를 이 파일의 Revision 2 section/hash로 바꾸거나,
승인된 별도 r2 파일을 실제 생성해야 한다. 현 작업 범위에서는 다른 파일을 만들 수 없으므로
전자를 권고한다.

### 12.4 Revision 2 P0 gate 표

| Revision 2 P0 | 판정 | 승인 조건 |
|---|---|---|
| JLC-D/CM/FLM construct boundary | PASS | 현재 명칭·주장 경계 유지 |
| FLM orthographic-only / empty contradictions | PASS | mechanism alias와 all-other-family contradiction 재도입 금지 |
| MCA/RA ground-truth correspondence | PASS | provenance와 incident별 path 유지 |
| finite negation grammar | PASS | finite grammar 자체는 명시됨 |
| coordinated-negation/exception synthetic verification | **FAIL** | 실제 ontology concept 두 개로 test하고 `not only C1 but C2` scope 고정 |
| raw regex 제거 / finite token predicate | PASS | predicate ID·sequence 확장 시 새 review |
| same-item remediation DNF/contradiction | PASS | cross-item join 금지 유지 |
| primary exact inference | PASS | one-sided direction과 single primary 유지 |
| secondary inference count 0 | PASS | p-value/CI/Q 생성 금지 유지 |
| GT full/projection commitment | PASS | 독립 재계산 exact 일치 |
| opaque input commitment provenance | PASS 조건부 | implementation review에서 hash-only behavior/redaction 실제 검증 필요 |
| implementation review→commit B exact freeze | **FAIL** | candidate commit `I`를 먼저 만들고 I→B review-only diff 검증 |
| approval commit A / clean checkout | PASS 조건부 | B→A approval-only diff와 exact A checkout 검증 필요 |
| semantic review artifact identity | **FAIL** | plan의 별도 r2 path를 이 파일/section으로 정합화 |
| candidate 비접근 | PASS | 본 재검토까지 본문 접근·검색·출력/scorer 실행 0 |

### 12.5 Revision 2 최종 판정과 다음 checkpoint

**최종 판정: 수정 요구 — candidate 접근 및 scoring package 승인 안 함.**

다음 checkpoint는 plan-only revision 3에서 다음 세 가지를 고치는 것이다.

1. coordinated-negation test를 실제 두 ontology concept으로 만들고 `not only` 소비 후 scope를
   명확히 한다.
2. implementation candidate commit `I` → review-only commit `B` → approval-only commit `A`의
   허용 diff와 hash 검증을 hard gate로 추가한다.
3. semantic Revision 2 review artifact를 이 파일의 본 섹션으로 일치시킨다.

이 수정은 candidate 표현이나 arm score를 보지 않고 수행해야 한다. 그 뒤 plan hash가 바뀌므로
semantic 재검토와 최종 plan hash 보고를 다시 받아야 한다.

---

## 13. Revision 3 재검토

> 재검토일: 2026-08-31
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 3
>
> 검토 plan SHA-256:
> `83e88cd31ff31173eacc3b1f09eeade5f0c4021c2a03c120fdc250a90f6ea473`
>
> 독립성 재선언: Revision 3 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 scorer를 실행하지 않았다. candidate path나 observed alias/score도 검토 입력으로
> 사용하지 않았다.

### 13.1 재검토 결론

**직전 Revision 2의 P0 세 개는 모두 exact하게 닫혔다. 그러나 plan 내부 hard gate에 새
self-referential hash P0가 있어 Revision 3도 수정 요구다.**

방법론의 substantive semantic/statistical 계약은 최종 승인 가능한 수준이다. 새 P0는 outcome
정의나 통계가 아니라 충족 불가능한 review hash 기록 절차 하나다. candidate 접근 전에 한 줄의
plan-only revision으로 고칠 수 있다.

### 13.2 Revision 2 P0 세 개 closure 검증

#### P0-A. Coordinated negation/`not only` — PASS

- test 9가 제거된 `memory pressure` 대신 실제 ontology concept인 `M_CPU_THROTTLED`와
  `M_MEMORY_LIMIT`를 사용한다.
- `no cpu throttling or memory limit`에서 두 span 모두 suppress됐음을 직접 assertion한다.
- `NOT_ONLY := not only C1 but C2`를 다른 grammar보다 먼저 소비하고 C1/C2를 둘 다 affirmative로
  남긴다.
- exception 소비 뒤에는 **남아 있는** unresolved marker/scope만 fail-close하고 ordinary concept는
  fail-close 대상이 아니라고 §7.10·§7.13에서 같은 의미로 고정했다.
- positive fixture와 남은 unsupported negation의 negative fixture가 모두 test 11에 있다.
- schema는 tokens, phrases, fillers, coordinators, contrasts, exceptions, grammar IDs를 `const`로
  강제하고 static validator가 값과 순서까지 확인한다.

따라서 finite grammar, coordinated scope, exception 소비, unsupported grammar fail-close의
Revision 2 공백은 닫혔다.

#### P0-B. Implementation review→commit freeze — PASS

Revision 3는 다음 비순환 chain을 exact하게 정의한다.

```text
I = implementation target files를 먼저 봉인한 candidate commit
B = I에 implementation review 문서 하나만 추가
A = B에 approval 문서 하나만 추가
```

- implementation reviewer는 detached clean exact `I`를 검토한다.
- review에는 exact I, detached/clean 증거, 각 `I:path` blob/filesystem SHA-256, test command와
  exit status를 기록한다.
- `B^ == I`와 I→B exact one-file diff, target hash 불변을 hard gate로 둔다.
- `A^ == B`와 B→A exact approval-only diff를 hard gate로 둔다.
- candidate 본문 접근은 exact `A` parent/diff/hash 검증 이후에만 허용된다.

reviewed working tree와 commit B 사이의 mutation gap 및 review/approval 자기참조 문제가 모두
해소됐다.

#### P0-C. Semantic review artifact identity — PASS

- 단일 정본을 이 파일 `docs/plans/review_v2_4_deterministic.md`로 고정했다.
- 최초 FAIL, Revision 2, Revision 3 section을 같은 파일에 append한다.
- 별도 r2/r3 파일의 생성·참조를 금지했고 commit `I` target list도 이 파일 하나만 포함한다.
- §9.1, §12, §16의 artifact path가 일치한다.

따라서 이번 작업 지시와 plan의 required bundle 사이 경로 충돌은 닫혔다.

### 13.3 Plan 전체 P0 재판정

| P0 gate | Revision 3 판정 | 근거 |
|---|---|---|
| JLC-D/CM/FLM 주장 경계 | PASS | mention/concordance로 한정, CA/FA/JRA 호환·semantic accuracy 주장 금지 |
| canonical GT/ontology correspondence | PASS | 12행 mapping·provenance·strict FLM/RA 유지 |
| FLM orthographic-only / contradictions=[] | PASS | mechanism/symptom alias와 competing-role 추정 없음 |
| MCA/RA field isolation과 DNF | PASS | incident-specific MCA, RA same-item positive/contradiction |
| finite negation grammar | PASS | 여섯 grammar와 exact constants, unresolved marker fail-close |
| coordinated negation/exception tests | PASS | 실제 concept 두 개와 positive/negative assertions |
| regex/token safety | PASS | raw regex 없음, finite predicate·token boundary·size/language fail-close |
| primary exact McNemar | PASS | one-sided 사전 방향, single confirmatory outcome/comparison |
| bootstrap/Clopper–Pearson | PASS | estimand 구분, stdlib deterministic procedure |
| secondary inference | PASS | p-value/CI/Q 0으로 고정 |
| primary status/remediation warning | PASS | 별도 required fields, 합성 status 금지 |
| GT full/projection commitment | PASS | Revision 2 독립 재계산 hash/3318 bytes 유지 |
| opaque commitment | PASS 조건부 | semantic 계약 타당; exact tool behavior는 implementation review 대상 |
| I→B→A freeze/approval chain | PASS | exact parent, one-file diffs, target hashes, detached review |
| semantic review artifact path | PASS | 이 단일 append-only 정본으로 통일 |
| review 최종 SHA 기록 가능성 | **FAIL** | 최종 SHA를 같은 review 파일 안에 append하라는 DoD는 자기참조라 충족 불가능 |
| candidate 비접근 | PASS | 세 차례 semantic review 모두 본문 접근·검색·출력/scorer 실행 0 |
| 외적 타당성·주장 경계 | PASS | frozen 12 incidents lexical outcome으로 제한 |

### 13.4 새 P0 — self-referential review SHA

§9.1은 Revision 3 append 뒤 바뀐 review file hash를 commit `I`에 기록한다고 해 외부 기록으로
해석할 수 있다. 그러나 §16 Definition of Done은 다음을 요구한다.

> 단일 semantic review 정본에 Revision 3 PASS와 최종 file hash가 append됨.

review 파일에 그 파일 자신의 “최종 SHA-256” 문자열을 append하면 파일 bytes와 SHA가 다시
바뀐다. 일반 SHA-256 fixed point를 전제로 하지 않는 한 이 gate는 충족할 수 없다. 이번 답변에서
계산해 보고하는 review SHA도 파일 밖의 report이므로 가능하지만, 그 값을 다시 이 파일 안에
넣으면 더 이상 최종 SHA가 아니다.

**필수 수정:**

- §16을 “단일 semantic review 정본에 Revision 3 PASS가 append되고, 그 최종 filesystem
  SHA-256가 commit `I` 이후 implementation review 문서와 사용자 보고에 기록됨”으로 바꾼다.
- §9.1의 “commit I에 기록”도 Git tree에 파일이 포함된다는 뜻과 digest 기록 위치를 구분해,
  최종 review filesystem SHA-256는 exact `I`를 검토하는 implementation review 문서가 기록한다고
  명시한다.
- review 정본 자체에는 자기 SHA를 쓰지 않는다. `I:path` Git blob identity와 filesystem
  SHA-256는 implementation review에서 함께 기록한다.

이는 결과를 보지 않고 수정할 수 있는 plan execution gate이며, 고치기 전에는 Definition of Done이
논리적으로 완결되지 않는다.

### 13.5 Revision 3 최종 판정

**최종 판정: 수정 요구 — semantic plan 최종 승인 보류.**

직전 P0 세 개와 최초 방법론 P0는 모두 해결됐다. 남은 것은 self-referential hash 문구 하나다.
이를 외부 implementation review/user report 기록으로 수정한 plan revision을 candidate 비접근
상태에서 확인하면, 다른 변경이나 새 P0가 없는 한 semantic plan 최종 승인을 권고할 수 있다.

---

## 14. Revision 4 재검토

> 재검토일: 2026-08-31
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 4
>
> 검토 plan SHA-256:
> `24385717f3de42f3288ca44e80ab040d498fb1a5cabf59ec7ac43424e10145db`
>
> 독립성 재선언: Revision 4 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 scorer를 실행하지 않았다. 이 review 파일 자신의 SHA-256는 내부에 기록하지 않는다.

### 14.1 최종 결론

**Semantic plan 최종 승인 권고 — P0 PASS 18, FAIL 0.**

Revision 4는 Revision 3의 유일한 잔여 P0였던 self-referential review SHA 계약을 정확히
수정했다. 측정 ontology, negation grammar, DNF, 통계, input commitment, `I→B→A` chain의 의미는
바뀌지 않았다. 이 승인은 semantic plan에 대한 것이며, 아직 만들어지지 않은 ontology/code/test/
commitment 구현의 승인은 아니다. 그 구현은 plan대로 exact commit `I`의 별도 fresh
implementation review를 통과해야 한다.

### 14.2 Self-reference P0 closure — PASS

Revision 4의 세 관련 위치가 같은 계약을 말한다.

1. **§9.1:** semantic review 정본은 append content와 commit `I` tree의 exact path/blob OID로
   고정한다. review 파일은 자기 filesystem SHA-256를 포함하지 않는다.
2. **§9.1 I→B gate:** exact `I`가 고정된 뒤 외부에서 review filesystem SHA-256를 계산한다.
   implementation review는 그 값과 `I:path` blob/filesystem hash를 기록하며, B tree에서 같은지
   검증한다.
3. **§9.1 B→A gate:** approval provenance가 semantic review blob OID와 외부 계산 SHA-256를
   기록한다. approval 문서만 추가한 `A`를 실행한다.
4. **§12:** Step 2도 review 내부 self-hash를 금지하고 blob/tree identity와 외부 provenance를
   정본화 수단으로 명시한다.
5. **§16:** DoD를 “PASS content는 review에 append, final filesystem SHA-256는 review 파일 밖
   implementation review·approval·사용자 보고에 기록”으로 분리했다.

따라서 hash 값을 파일 안에 넣어 다시 hash가 바뀌는 순환은 없다. review final SHA의 계산 시점,
기록 위치, I/B tree 비교가 모두 실행 가능하고 비순환적이다.

Revision 4의 본 section은 Revision 3에서 승인 가능하다고 판정한 substantive semantic 계약과
Revision 4의 self-reference closure를 함께 최종 PASS로 비준한다. 기존 FAIL 기록은 당시 gate의
이력을 보존하며, 최종 유효 판정은 이 section이다.

### 14.3 의미 불변 확인

Self-reference 수정 외 다음 핵심 계약은 Revision 3와 동일하다.

- primary는 `JLC-D = CM ∧ FLM ∧ MCA`, RAG 대 length placebo의 12-pair 비교 하나다.
- CM/FLM은 mention/concordance이며 localization, classification accuracy, JRA가 아니다.
- FLM은 orthographic-only이고 CM/FLM/MCA contradictions는 비운다.
- MCA는 incident-specific conjunction, RA는 same-item DNF와 same-item opposite-action
  contradiction이다.
- raw regex 없이 finite token predicate만 허용한다.
- finite negation grammar, actual-concept coordinated test, `NOT_ONLY`, unresolved marker
  fail-close가 유지된다.
- exact one-sided McNemar, Clopper–Pearson, deterministic paired bootstrap이 유지된다.
- secondary inferential p-value/CI/Q는 0이다.
- GT full/projection hash, opaque commitment, no-follow/rehash, clean execution gate가 유지된다.
- implementation candidate `I` → review-only `B` → approval-only `A` chain이 유지된다.
- candidate 접근은 exact `A` 검증 뒤에만 가능하다.

새 outcome, alias, threshold, test 방향, comparator, missingness rule 또는 주장 확장은 없다.

### 14.4 최종 P0 표

| P0 gate | 최종 판정 | 근거 |
|---|---|---|
| candidate 비접근 semantic review | PASS | 네 차례 모두 본문 접근·검색·출력/scorer 실행 0 |
| canonical 12-row ground-truth mapping | PASS | 선택 identity와 canonical projection 고정 |
| JLC-D/CM/FLM construct boundary | PASS | lexical mention으로 명시적 하향 |
| FLM orthographic-only | PASS | mechanism/symptom alias 제거 |
| CM/FLM/MCA contradiction policy | PASS | role 추정 없이 빈 배열 |
| MCA field isolation/conjunction | PASS | incident-specific ground-truth atoms |
| RA same-item DNF/contradiction | PASS | cross-item join 금지 |
| finite negation grammar | PASS | exact constants와 여섯 grammar |
| coordinated negation/NOT_ONLY tests | PASS | 실제 ontology concept와 positive/negative assertion |
| unsupported negation fail-close | PASS | unresolved marker/scope만 INVALID |
| regex/token safety | PASS | raw regex 금지, finite predicate·input/language limits |
| exact one-sided primary inference | PASS | single primary, direction·tail·known-answer 고정 |
| interval/replay determinism | PASS | CP estimand, stdlib bootstrap, canonical serialization |
| secondary inference/multiplicity | PASS | inferential test·CI·Q 수 0 |
| status/remediation warning separation | PASS | 독립 required fields, 합성 status 금지 |
| GT/input commitment | PASS | full/projection digest와 opaque hash-only provenance |
| I→B→A result-independent freeze | PASS | exact parents, one-file diffs, target hash equality |
| review SHA non-self-reference | PASS | I 고정 후 외부 기록, review 내부 기록 금지 |

**합계: PASS 18 / FAIL 0.**

### 14.5 승인 경계와 다음 checkpoint

**Semantic plan을 최종 승인하도록 권고한다.**

다음 checkpoint는 candidate 비접근 상태에서 ontology/scorer/analyzer/tests/commitment를 구현해
candidate commit `I`를 만드는 것이다. 이후 fresh implementation reviewer가 exact detached
`I`와 synthetic/static test를 검증하기 전에는 scoring package를 승인하거나 candidate 본문을
읽어서는 안 된다.
