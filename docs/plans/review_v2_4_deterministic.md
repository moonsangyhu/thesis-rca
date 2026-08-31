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

---

## 15. Revision 5 재검토

> 재검토일: 2026-08-31
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 5
>
> 검토 plan SHA-256:
> `c31361c52c0e5bd2b5b79fbe9e304b13b27123dd88fd42cd5988ec75f4a76ef4`
>
> 독립성 재선언: Revision 5 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 V2.4-D scorer를 실행하지 않았다. 허용된 plan, cumulative reviews, commitment의
> metadata key/digest와 synthetic 통계 계약만 확인했다. 이 review 파일 자신의 SHA-256는 내부에
> 기록하지 않는다.

### 15.1 결론

**수정 요구 — P0 PASS 19 / FAIL 2.**

Revision 5는 implementation FAIL P0-1~P0-5, P0-7과 대부분의 P0-6 내용을 exact contract로
잘 흡수했다. Outcome semantics, alias, threshold, comparator, primary test와 상태 판정은 Revision
4에서 바뀌지 않았다. 그러나 opaque commitment의 **identity**와 **review-before-real-access
순서**에 두 P0가 남아 implementation candidate를 아직 만들 수 없다.

### 15.2 Outcome semantics 불변 — PASS

- primary는 계속 `JLC-D = CM ∧ FLM ∧ MCA`이고 treatment/control은 동일 12-pair
  RAG/length-placebo다.
- CM/FLM lexical mention 경계, FLM orthographic-only, MCA incident conjunction, RA same-item DNF,
  contradictions 정책이 그대로다.
- exact one-sided McNemar, Clopper–Pearson, paired bootstrap seed/algorithm, secondary inference 0,
  `primary_status`/remediation flag 분리가 유지된다.
- synthetic vector의 50,000 bootstrap 계약을 독립 재계산한 결과도 plan과 일치했다:

```text
serialized bytes  744080
SHA-256           aa089664652480d5565da1853d51635dd53310475585e3cccbc8516bb7aae4ca
percentiles       [-0.16666666666666666, 0.66666666666666663]
```

따라서 Revision 5는 결과에 맞춰 outcome을 이동시키지 않고 implementation assurance만 강화한다.

### 15.3 요청 항목별 판정

#### Ontology schema representation — PASS

`token_predicates`와 `negation.syntax`를 top-level schema의 required/`const` representation으로
명시해 Revision 4 prose와 구현 representation의 차이를 제거했다. duplicate-rejecting loader,
object order, version/normalization/predicate/negation exact constants, incident/path/group identity,
F1 inventory와 §6.2 전체 count를 builder와 loader 양쪽에서 검증한다. 이 representation 추가는
기존 9개 finite token sequence와 여섯 negation grammar의 의미를 바꾸지 않는다.

#### Implementation target 확대 — PASS

새 `I` target은 기존 목록에 `__init__.py`, `build_ontology.py`, `run.py`를 포함한다. 실제 import,
builder, runner, commitment tool, scorer, analyzer, tests, plan/review/commitment 전체가 blob OID·
blob SHA-256·filesystem SHA-256 map에 들어간다. 기존 implementation review는 B에서 수정되고
approval은 A에서 추가되므로 I target과 분리한 것도 chain 의미와 맞다.

#### I/B/A + all-hash gate — PASS

- `B^=I`, I→B는 cumulative implementation review 파일 한 개의 modification만 허용한다.
- `A^=B`, B→A는 approval 파일 한 개의 addition만 허용한다.
- runner는 candidate source open 전에 HEAD/A/B/I parent·diff, semantic/implementation/approval
  identity, 전체 target map, interpreter와 commitment/GT/input hash를 재계산한다.
- approval 자체의 hash는 external execution authorization과 manifest에 기록해 self-reference를
  피한다.

기존 runner 비봉인과 approval string-only 검증 문제를 semantic contract 수준에서 닫았다.

#### Hidden two-full-run release — PASS with P1 clarification

run1과 run2를 각각 완전한 36-row scoring+analysis로 hidden mode-0700 staging 안에서 끝내고,
file별/aggregate canonical digest가 같은 경우에만 single release root를 한 번 atomic rename한다.
run2 실패·mismatch·rename 실패 때 public result/summary가 absent이고 body 없는 INVALID receipt만
나오는 test matrix도 있다. 따라서 replay 전에 arm score가 공개돼 change control을 오염시키는
P0는 닫혔다.

P1로, single release root 안의 “tracked result candidate”가 최종
`results/experiment_results_v2_4_deterministic.csv` 및 analysis 경로로 언제·어떻게 승격되는지
§13에 명시해야 한다. 서로 다른 기존 parent에 두 파일을 놓는 작업은 하나의 directory rename으로
동시에 atomic할 수 없다. 최초 score 공개가 replay 뒤라는 핵심은 충족하므로 이 layout 설명은
semantic P0가 아니라 implementation review에서 확인할 publication P1이다.

#### Commitment safety — **P0 FAIL 2개**

Revision 5의 no-follow/fd/pre-post hash/fstat/lstat, unexpected-entry, hard-link, TOCTOU, executable
redaction test와 rich provenance 계약 자체는 적절하다. 그러나 다음 두 모순이 남는다.

**P0-5A — 새 commitment 계약과 frozen old digest가 양립하지 않는다.**

§9.2는 commitment 내부 digest를 다음 기존 값으로 exact 요구한다.

```text
590e8e006d5adc449bb8e0bdd12b0beaaf7bc8197015dd65a7131525cf90ca64
```

허용된 현재 commitment metadata를 본문 없이 key/digest만 확인하면 provenance는
`argv, exit_status, finished_utc, interpreter_path, interpreter_sha256, operator_attestation,
python_version, redaction_test, started_utc, stderr_sha256, stdout_sha256, tool_sha256`이고
`redaction_test=PASS` 상수다. Revision 5가 새로 required로 만든 tool blob OID, cwd, allowlisted
environment, source-root device/inode, fixture/sentinel digest, sentinel count, manifest digest 등의
필드가 없다. implementation review도 이 commitment가 unsafe old tool에서 만들어졌음을 기록했다.

`commit_inputs.py`를 P0-6에 맞게 수정하고 새 executable evidence/provenance를 넣으면 canonical
commitment bytes와 내부 `commitment_sha256`는 반드시 바뀐다. 그런데 old digest를 exact gate로
유지하면 새 safe commitment는 거부되고 old unsafe commitment만 통과한다.

**필수 수정:** old internal digest를 삭제한다. 새 tool safety review 뒤 생성된 commitment를
새 candidate commit에 넣고, 그 파일의 canonical self-excluding digest를 implementation review와
approval에서 새 값으로 freeze한다. CSV/raw entry digest는 기존 opaque source identity와 exact
일치해야 하지만 provenance를 포함한 commitment envelope digest는 새 값이어야 한다.

**P0-5B — real commitment tool이 review 전에 candidate bytes를 연다.**

§9.1 순서는 구현과 real opaque commitment를 먼저 완성해 commit `I`를 만든 뒤 fresh reviewer가
`commit_inputs.py`를 검토한다. 즉 새 tool이 source bytes를 실제로 읽는 시점에는 아직 독립
safety/redaction review를 받지 않았다. Self-test가 먼저 실행돼도 real path와 error path가 그
reviewed contract를 구현했다는 보장은 사후에만 생긴다. 과거 tool이 상수 PASS와 unsafe `open()`을
사용했다는 이번 implementation finding이 바로 이 순서의 위험을 실증한다.

**필수 수정:** candidate source를 전혀 열지 않는 code-only commit `I0`를 먼저 만들고 fresh
commitment-safety reviewer가 detached `I0`에서 `commit_inputs.py`, bootstrap, executable
redaction/path-attack tests를 PASS해야 한다. 그 exact reviewed tool로만 real hash-only commitment를
생성한 뒤 commitment를 추가한 implementation candidate `I`를 만들고, 기존 전체 implementation
review→B→A chain을 수행한다. 대안은 이미 독립 승인된 별도 minimal hash-only tool/commit을
사용하는 것이다. I0→I diff도 commitment file과 사전 허용 provenance receipt 외 변경을 금지하고
tool hash가 같아야 한다.

#### `python -I` bootstrap — PASS

각 script가 자기 `__file__`에서 expected root를 계산하고 ancestor no-symlink/git identity를
확인한 뒤 그 root만 `sys.path`에 삽입하도록 사전 고정했다. `PYTHONPATH`, user site, arbitrary cwd,
namespace fallback을 금지하고 bootstrap code 자체를 I target/hash와 test 35에 포함한다. 이는
isolated mode에서 이전 import failure를 고치는 제한된 bootstrap이며 external code injection을
허용하지 않는다.

#### Synthetic/static 37 categories — PASS at semantic adequacy level

추가 15개 범주는 implementation FAIL의 ontology mutation, grammar traces, absence polarity,
schema boundaries, hash/identity, git chain, replay publication, path attacks, executable redaction,
known statistics bytes, isolated bootstrap, deviation schema와 no-text-egress를 직접 공격한다.
37은 test method 개수가 아니라 required behavior category 수로 이해해야 한다. 실제 fixture/assertion
coverage와 37개 PASS는 새 exact I의 implementation review에서 검증해야 한다.

#### `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION` — PASS 조건부

과거 generic parser의 process-level candidate parse 가능성을 “access 0”으로 숨기지 않고 별도
status로 공개한다. 실행 identity/log digest, human/agent text egress 0, V2.4-D scorer/ontology/
alias/score 실행 0, observed-output-derived change 0의 네 evidence를 모두 요구하며 하나라도 없거나
text egress가 있으면 gate를 실패시킨다. 이는 process deviation을 결과 비정보성의 causal evidence와
구분하며 outcome definition을 사후 바꾸지 않는다.

이 판정은 operator attestation을 cryptographic proof로 취급하지 않는다는 §9.1 경계 아래에서만
유효하다. Implementation review는 historical command/log/diff evidence가 실제 존재하는지 확인해야
하며, 없으면 `INVALID` 또는 `EXPLORATORY_ONLY`로 강등해야 한다.

### 15.4 P0 gate 표

| P0 gate | Revision 5 판정 | 근거 |
|---|---|---|
| candidate body 비열람 semantic review | PASS | 본문 접근·검색·출력 및 scorer 실행 0 |
| outcome semantics/primary status 불변 | PASS | JLC-D/CM/FLM/MCA/RA와 통계 계약 동일 |
| ontology schema representation | PASS | predicate/syntax representation과 exact validator 계약 일치 |
| ontology inventory/provenance | PASS | F1 aliases와 12-row count mutation gate |
| finite negation/schema fail-close | PASS | implementation counterexamples가 tests 23~28에 반영 |
| implementation target completeness | PASS | init/builder/runner/commitment tool 포함 |
| I/B/A parent/diff gate | PASS | review-only B, approval-only A |
| all target/hash binding | PASS | blob/filesystem/interpreter/input maps candidate-open 전 검증 |
| hidden two-full-run replay | PASS | run1 미공개, complete+equal 뒤 single release |
| result-independent publication | PASS | mismatch 시 body 없는 INVALID만 공개 |
| commitment path/TOCTOU specification | PASS | no-follow fd와 mutation/unexpected-entry matrix |
| commitment executable redaction specification | PASS | sentinel/captured evidence, 상수 PASS 금지 |
| commitment digest identity | **FAIL** | 새 provenance와 old hard-coded internal digest가 양립 불가 |
| commitment review-before-real-access | **FAIL** | tool이 exact fresh safety review 전에 source bytes를 읽음 |
| isolated `python -I` bootstrap | PASS | reviewed root-only bootstrap과 exact commands |
| synthetic/static 37-category adequacy | PASS | prior P0/P1 counterexamples와 known bytes 포함 |
| exact primary statistics | PASS | independent synthetic hash/percentile 재계산 일치 |
| machine-parse deviation transparency | PASS 조건부 | 네 evidence required, process-access-zero 주장 금지 |
| no-text-egress/result-derived-change gate | PASS 조건부 | historical evidence는 implementation review에서 확인 |
| GT/input fixed identity | PASS | full/projection/CSV/raw contract 유지 |
| missingness/language/schema fail-close | PASS | invalid 전체 run, imputation 없음 |

**합계: PASS 19 / FAIL 2.** 조건부 PASS는 implementation evidence가 없으면 FAIL로 전환된다.

### 15.5 최종 판정과 다음 checkpoint

**최종 판정: 수정 요구 — Revision 5 semantic implementation contract 승인 보류.**

다음 plan-only revision은 (1) old commitment internal digest를 제거하고 새 reviewed provenance로
재생성·freeze하는 규칙, (2) code-only `I0` commitment-safety review → real hash-only commitment →
full candidate `I`의 access 순서를 추가해야 한다. 이 두 P0는 candidate 표현이나 arm score를 보지
않고 해결할 수 있다. 수정 전에는 새 commitment 생성, implementation candidate `I`, bundle B/A,
scoring을 진행하면 안 된다.

---

## 16. Revision 6 재검토

> 재검토일: 2026-08-31
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 6
>
> 검토 plan SHA-256:
> `169f59e40b4619c15613cce6360ca4b03063dfa1cd451e79160c86be949d936d`
>
> 독립성 재선언: Revision 6 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 V2.4-D scorer를 실행하지 않았다. 이 review 파일 자신의 SHA-256는 내부에 기록하지
> 않는다.

### 16.1 최종 결론

**Semantic implementation plan 최종 승인 권고 — P0 PASS 20 / FAIL 0.**

Revision 5의 두 잔여 P0는 code-only `I0` safety review → reviewed tool real commitment → full
candidate `I1` review chain으로 exact하게 닫혔다. Revision 6는 commitment access/freeze 절차만
강화했고 `JLC-D` outcome, ontology acceptance set, 통계, comparator, 상태 판정은 바꾸지 않았다.

이 승인은 plan의 semantic·procedural contract에 대한 것이다. 아직 만들어지지 않은 `I0` tool과
`I1` implementation이 이 계약을 실제 구현했다는 승인이 아니다. 두 fresh implementation gate가
각각 실제 PASS하기 전에는 B/A 또는 scoring으로 진행할 수 없다.

### 16.2 Revision 5 P0 closure

#### P0-5A. Old envelope conflict — PASS

Revision 6는 old commitment와 내부
`590e8e006d5adc449bb8e0bdd12b0beaaf7bc8197015dd65a7131525cf90ca64`를
`DEPRECATED_MACHINE_HASH_ONLY_COMMITMENT` history로만 보존한다.

- Old envelope bytes/provenance/digest를 confirmatory commitment, approval target, runtime
  expected digest로 사용하는 계약을 명시적으로 폐기했다.
- Old artifact의 fixed CSV SHA와 정렬된 117개 `relative_path,size,sha256`만 outcome-independent
  **legacy source-identity map**으로 사용한다.
- Exact reviewed `I0` tool이 새 commitment와 richer provenance를 생성한다.
- 새 canonical self-excluding envelope digest는 old 값과 달라도 되며 plan에 사전 하드코딩하지
  않는다.
- 새 file/envelope digest는 `I1`에서 처음 고정되고 full review B·approval A·runtime preflight가
  같은 값을 독립 재계산한다.
- Runtime에서 old `590e8e...`를 새 expected value로 비교하면 오히려 INVALID다.

따라서 새 provenance를 요구하면서 old envelope digest만 허용하던 Revision 5의 논리 모순은 없다.
Source identity는 old/new map exact equality로 유지되고 provenance envelope만 안전하게 교체된다.

#### P0-5B. Unreviewed tool real access — PASS

Revision 6의 순서는 다음과 같이 비순환적이다.

```text
semantic PASS
  → candidate-unmounted code-only commit I0
  → fresh detached I0 commitment-safety review + external content-addressed PASS receipt
  → exact reviewed I0 tool만 real hash-only access
  → commitment + deviation provenance만 바꾼 I1
  → fresh detached I1 full implementation review
  → review-only B
  → approval-only A
  → scoring
```

- `I0` safety review에는 candidate source path를 mount/전달하지 않으며 real CSV/raw open count 0을
  요구한다.
- Reviewer는 exact I0/tool/interpreter/blob/filesystem hashes, commands, fixture/sentinel,
  stdout/stderr digest와 PASS를 external receipt로 먼저 봉인한다.
- FAIL 또는 receipt 부재면 real commitment를 금지한다.
- 새 commitment provenance가 exact I0 tool blob과 safety receipt digest를 포함한다.
- `I1^=I0`이고 I0→I1은 commitment modification과 deviation provenance addition 두 줄만
  허용한다. 모든 code/plan/review blob은 불변이어야 한다.
- Safety review보다 이른 real source open, reviewed tool/provenance identity mismatch, allowlist 밖
  diff는 INVALID다.
- 별도 fresh reviewer가 exact I1에서 receipt, commitment, provenance, full code/test를 다시
  검증한다.

따라서 candidate bytes를 읽는 tool이 독립 검토 전 실행되던 순서가 제거됐다.

### 16.3 Outcome semantics 불변 — PASS

Revision 5 대비 다음이 그대로다.

- `JLC-D = CM ∧ FLM ∧ MCA`, 동일 12 incidents의 RAG 대 length-placebo single primary.
- CM/FLM lexical mention 경계, FLM orthographic-only, empty CM/FLM/MCA contradictions.
- Incident-specific MCA와 same-item RA DNF/contradiction.
- Finite negation grammar, raw regex 금지, finite token predicate, fail-close schema.
- Exact one-sided McNemar, Clopper–Pearson, seed-fixed paired bootstrap, secondary inference 0.
- Primary status와 remediation warning의 독립 required fields.
- Hidden two-full-run complete+equal 뒤 release, mismatch 시 body 없는 INVALID.
- `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION`의 네 evidence와 process-access-zero 표현 금지.

새 alias, matcher, threshold, missingness 처리, success rule 또는 주장 확장은 없다.

### 16.4 Chain·internal consistency 검증

- Semantic cumulative review는 I0 blob/tree로 고정하고 self-hash는 외부 provenance에만 기록한다.
- I0 safety scope 여덟 code/test files와 I1 full target 열두 files가 명시돼 있다.
- I0→I1 exact two-file diff, I1→B implementation-review-only diff, B→A approval-only diff가
  서로 다른 역할을 가진다.
- Runner는 source open 전에 I0/I1/B/A parent, diffs, external receipt, all blob/filesystem hashes,
  new commitment digest, legacy map, GT/input/interpreter를 검증한다.
- Code hash는 I0→I1에서 불변이며 full reviewer와 approval target map이 이를 재확인한다.
- DoD와 §9.1, §9.2, §12가 같은 I0→I1→B→A 명칭과 순서를 사용한다.

External safety receipt는 repository target이 아니지만 그 content hash가 새 commitment, full review,
approval, runtime preflight에 연쇄 고정된다. Receipt bytes가 없거나 digest/content가 불일치하면
full review/runtime gate가 실패하므로 승인 우회 경로가 아니다.

### 16.5 최종 P0 표

| P0 gate | Revision 6 판정 | 근거 |
|---|---|---|
| candidate body 비열람 semantic review | PASS | 본문 접근·검색·출력/scorer 실행 0 |
| outcome semantics 불변 | PASS | JLC-D ontology/statistics/status 동일 |
| ontology schema/inventory/provenance | PASS | Revision 5 exact representation 유지 |
| finite negation/schema fail-close | PASS | grammar·mutation matrices 유지 |
| RA same-item DNF | PASS | cross-item join 금지 유지 |
| old commitment deprecation | PASS | confirmatory/approval/runtime 사용 금지 |
| legacy source identity continuity | PASS | CSV+117 path/size/hash old/new exact comparison |
| new envelope digest identity | PASS | I1에서 새 값 freeze, old digest 비교 금지 |
| code-only I0 before real access | PASS | candidate source unmounted/open count 0 |
| I0 commitment-safety review | PASS | fresh detached synthetic-only review+receipt required |
| reviewed-tool-only commitment | PASS | exact I0 tool/receipt identity provenance |
| I0→I1 code immutability | PASS | commitment+deviation exact two-file diff만 허용 |
| fresh I1 full implementation review | PASS | receipt/commitment/full target/test 재검증 |
| I1→B→A freeze chain | PASS | review-only B, approval-only A |
| all hash/preflight binding | PASS | I0/I1/B/A·receipt·targets·input candidate-open 전 검증 |
| commitment path/TOCTOU/redaction | PASS | reviewed no-follow/fd/rehash/sentinel gates |
| isolated `python -I`/37 tests | PASS | reviewed bootstrap와 counterexample matrix 유지 |
| hidden replay publication | PASS | two full runs equal 뒤 single-root release |
| machine-parse deviation transparency | PASS 조건부 | 네 historical evidence 없으면 downstream gate FAIL |
| external/generalization claim boundary | PASS | frozen lexical 12-incident scope 유지 |

**합계: PASS 20 / FAIL 0.** 조건부 evidence는 implementation 단계에서 없으면 그 단계가 FAIL이며,
현재 semantic contract에는 우회 규칙이 없다.

### 16.6 승인 경계와 다음 checkpoint

**Revision 6 semantic implementation plan을 최종 승인하도록 권고한다.**

다음 checkpoint는 candidate source를 mount하거나 전달하지 않은 상태에서 implementation code와
synthetic fixtures만 완성해 code-only `I0`를 만드는 것이다. 그 뒤 fresh safety reviewer의 exact
I0 PASS receipt가 봉인되기 전에는 `commit_inputs.py`를 real source에 실행하면 안 된다.

---

## 17. Revision 7 chain consistency 재검토

> 재검토일: 2026-09-01
>
> 검토 범위: `experiment_plan_v2_4_deterministic.md` revision 7의 chain 표기 교정
>
> 검토 plan SHA-256:
> `33435f87ce56c9bcef38b6ea3bb985e305ac02b5a1ebebdb4af69e9a241b4381`
>
> 독립성 재선언: Revision 7 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 V2.4-D scorer를 실행하지 않았다. 이 review 파일 자신의 SHA-256는 내부에 기록하지
> 않는다.

### 17.1 결론

**Revision 7 chain 승인 권고 — P0 PASS 8 / FAIL 0.**

Revision 7은 Revision 6의 outcome/ontology/statistics를 변경하지 않고 code-only `I0` tree와
`I0→I1` diff status를 실제 Git 상태 전이와 일치시킨 교정이다. 직전 semantic 승인 결론은
유효하며 새 P0가 없다.

### 17.2 Code-only I0 commitment path — PASS

Revision 7은 다음을 exact hard gate로 추가했다.

```text
git cat-file -e I0:docs/plans/input_commitment_v2_4_deterministic.json
→ non-zero required
```

- Active `input_commitment_v2_4_deterministic.json`은 `I0` tree에 존재하지 않는다.
- Pre-I0 old commitment는 git history에만 남으며 I0 safety scope/target이 아니다.
- I0 safety scope는 ontology/init/builder/commit tool/scorer/analyzer/runner/test 여덟 code/test
  파일로 한정된다.
- 따라서 fresh safety reviewer가 commitment bytes가 아니라 real source를 아직 읽지 않은 exact
  tool과 synthetic safety behavior만 검토한다는 `I0` 정의가 실제 tree와 일치한다.

### 17.3 I0→I1 A/A diff — PASS

Exact reviewed I0 tool로 새 commitment를 생성하고 deviation provenance를 봉인한 뒤의 유일한
허용 diff는 다음과 같다.

```text
I1^ == I0
git diff --name-status I0..I1
A  docs/plans/input_commitment_v2_4_deterministic.json
A  docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json
```

두 경로 모두 I0에 없고 I1에서 처음 생기므로 `A/A`가 맞다. Revision 6의 commitment `M` 표기와
달리 code-only I0 정의, `git cat-file` absence gate, full I1 target list, preflight의
“commitment addition + deviation addition” 문구가 모두 같은 상태 전이를 말한다.

I0→I1에서 ontology/scorer/analyzer/runner/builder/commit tool/tests 및 plan/cumulative review blob은
불변이어야 하므로 commitment 생성 뒤 code를 조정하는 우회도 없다.

### 17.4 Discarded hash-only artifact — PASS

Revision 6의 M/A contract mismatch 상태에서 한 차례 생성된 hash-only artifact는 다음과 같이
분리됐다.

- Candidate text를 decode/parse/search/preview/output하지 않았음은 절차 이력으로만 기록한다.
- 즉시 폐기됐고 commit, freeze, safety/full review, approval을 받지 않았다.
- 그 artifact bytes와 digest는 새 I1 commitment 또는 confirmatory provenance에 사용하지 않는다.
- Revision 7 계약의 exact reviewed I0 tool로 commitment를 새로 생성한다.

Pre-I0 git history의 더 오래된 commitment에서 fixed CSV SHA와 117개 opaque source-identity map만
source drift reference로 비교하는 계약은 별개다. 그 old envelope/provenance/digest는 계속
`DEPRECATED_MACHINE_HASH_ONLY_COMMITMENT`이며 confirmatory expected envelope로 사용되지 않는다.
따라서 폐기된 mismatch artifact를 legacy reference로 몰래 재사용하는 경로도 없다.

### 17.5 Downstream chain — PASS

- Full implementation candidate는 exact I1이다.
- I1→B는 cumulative implementation review modification 한 줄이다.
- B→A는 approval addition 한 줄이다.
- Runner는 source open 전에 `HEAD=A`, `A^=B`, `B^=I1`, `I1^=I0`, 세 diff와 all-hash map을
  검증한다.
- New commitment/deviation provenance는 I1 target, full review, approval, runtime manifest에
  포함된다.
- Commitment tool code는 I0→I1에서 byte-identical이어야 한다.

따라서 chain은 `I0 → I1 → B → A → scoring`으로 유일하다.

### 17.6 Outcome semantic 불변 — PASS

Revision 7에서 다음은 모두 Revision 6와 동일하다.

- `JLC-D = CM ∧ FLM ∧ MCA`, 동일 12-pair RAG 대 length-placebo primary.
- CM/FLM lexical 경계, orthographic-only FLM, MCA/RA paths와 contradictions.
- Finite negation, token predicate, field/schema/missingness fail-close.
- Exact one-sided McNemar, CP/bootstrap, secondary inference 0, status/warning 분리.
- Hidden two-full-run release와 machine-parse deviation evidence.

새 alias, outcome, threshold, comparator, success rule 또는 일반화 주장은 없다.

### 17.7 P0 gate 표

| Chain P0 | Revision 7 판정 | 근거 |
|---|---|---|
| I0 active commitment absence | PASS | `git cat-file -e` non-zero hard gate |
| I0 safety scope purity | PASS | code/test 8 files, real commitment 제외 |
| I0→I1 parent | PASS | `I1^ == I0` |
| I0→I1 status | PASS | commitment/deviation exact `A/A` two lines |
| I0→I1 code immutability | PASS | allowlist 밖 blob change INVALID |
| discarded mismatch artifact non-use | PASS | uncommitted/unfrozen/unapproved, I1/provenance 배제 |
| downstream I1→B→A consistency | PASS | review-only B, approval-only A, runtime preflight |
| outcome semantic invariance | PASS | JLC-D ontology/statistics/status 변화 0 |

**합계: PASS 8 / FAIL 0.**

### 17.8 최종 판정

**Revision 7 chain을 승인하도록 권고한다.**

다음 checkpoint는 plan대로 active commitment path가 없는 code-only `I0`를 봉인하고, candidate
source가 mount/전달되지 않은 fresh safety review에서 exact tool PASS receipt를 먼저 얻는 것이다.

---

## 18. Revision 8 methodology 재검토

> 재검토일: 2026-09-01
>
> 검토 plan: `experiment_plan_v2_4_deterministic.md` revision 8
>
> 검토 plan SHA-256:
> `3a9c7586f51bc7444ea432a933bd149f31e4f06f47d3a5383fb561407e2870f1`
>
> 독립성 재선언: Revision 8 재검토에서도 candidate output JSON/CSV의
> `identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 검색하거나 출력하지
> 않았고 V2.4-D scorer를 실행하지 않았다. 이 review 파일 자신의 SHA-256는 내부에 기록하지
> 않는다.

### 18.1 결론

**Revision 8 methodology 승인 권고 — P0 PASS 12 / FAIL 0.**

Revision 8은 Revision 7 full implementation review가 찾은 producer/consumer, runtime ontology,
unresolved negation, raw enumeration과 machine-parse evidence 계약의 결함을 outcome semantics 변경
없이 보완했다. `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION` waiver는 pristine process-access-zero
주장을 복구하지는 못하지만, 제한된 lexical confirmatory status에 붙는 **공개된 방법론 편차**로는
과학적으로 수용 가능하다. 아래 조건을 만족하지 못하면 waiver가 아니라 전체 run `INVALID`다.

### 18.2 Canonical producer→runner commitment schema — PASS

Plan은 producer와 runner가 공유하는 단일 exact shape를 고정했다.

- Top-level은 `raw_files, raw_count, csv, entry_manifest_sha256, commitment_sha256, provenance`
  여섯 key만 허용한다.
- `raw_files[]`는 exact `{path,size,sha256}`, CSV는 exact `{id_sha256,size,sha256}`다.
- `entry_manifest_sha256`는 canonical raw array, `commitment_sha256`는 자신과 provenance를 제외한
  canonical top-level object의 digest다.
- Provenance exact key/type/const, `reviewed_i0`, safety receipt와 top-level digest equality를
  강제한다.
- `_commit_core()`/real CLI와 repository/preflight/commitment gate가 **동일 validator를 import**해
  사용한다. Adapter, legacy normalization, `csv.path`, `reviewed_code_candidate` alias를 금지한다.
- Producer output key set과 runner accepted key set을 direct equality로 검증하고 실제 synthetic
  producer envelope을 shape 변환 없이 runner preflight에 전달하는 test 38이 있다.

따라서 Revision 7에서 actual producer commitment가 runner에서 필연적으로 INVALID였던 세 schema
불일치는 계약 수준에서 닫혔다.

### 18.3 Runtime ontology exact contract — PASS

Builder와 runtime `scorer.load_ontology()`가 동일 `validate_ontology_exact()`와
duplicate-rejecting loader를 반드시 호출한다. Runtime에서 다음을 모두 exact 강제한다.

- version/normalization/token predicates/negation syntax와 배열 순서,
- exact 12 incident identity·fault/trial·order,
- path/group/matcher 수와 §6.2 inventory,
- F1 `M_MEMORY_LIMIT` 3 aliases와 3 atoms/11 aliases,
- duplicate/add/remove/reorder mutation 거부.

Builder PASS나 approved file hash가 runtime validation을 대신할 수 없고 fallback/partial validation을
금지했다. Test 39가 runtime loader 자체에 result-changing mutation을 주입한다. Ontology acceptance
set은 Revision 7과 동일하며 enforcement만 강화됐다.

### 18.4 Unresolved negation — PASS

Runtime classifier는 각 grammar가 소비한 marker/concept/connector span exact set을 반환하고,
concept-associated negation marker 전체에서 consumed set을 뺀 remainder를 clause 단위로 검사한다.
Prefix-only 검사나 ontology marker 무시는 금지된다.

`memory limit is not generally relevant`는 `memory limit`과 unresolved `not`이 같은 clause에 남으므로
positive match가 아니라 `INVALID_UNSUPPORTED_NEGATION`이다. Test 40이 runtime scorer path에서
invalid status, positive path 미생성, consumed/remainder trace를 직접 assertion한다. Finite grammar
의미는 바뀌지 않고 Revision 7 fail-open 구현만 닫혔다.

### 18.5 Raw enumeration — PASS

Runner는 descriptor-anchored `listdir/scandir(fd)`로 모든 direct entry를 먼저 열거한다. 117 direct
regular JSON 외 extra/nested directory, nested JSON, non-JSON regular, hidden file, symlink, socket,
FIFO, device를 모두 INVALID 처리한다. `rglob("*.json")`/suffix-filter로 unexpected entry를 숨기는
경로를 금지했고 test 41이 각 entry type을 공격한다. 이후 no-follow/fstat/pre-post hash/lstat와
approved manifest equality도 유지된다.

### 18.6 Machine-parse waiver와 `NOT_RETAINED` — PASS with mandatory disclosure

#### 관찰한 한계

2026-08-31 generic `tests.test_v2_4_audit`가 candidate JSON을 machine-only parse했다.
`process_access_zero=false`다. Original stdout/stderr streams, exact execution commit과 clean tree는
보존되지 않았으므로 완전한 독립 재현이나 cryptographic non-egress proof는 불가능하다.
`NOT_RETAINED`는 이 결손을 정직하게 나타낼 뿐 digest가 아니다.

#### Confirmatory 유지가 제한적으로 가능한 이유

Confirmatory lexical outcome의 직접적 오염 경로는 candidate 표현/score가 ontology·alias·metric·
threshold/status 결정자에게 전달돼 사후 적합화되는 것이다. Revision 8은 다음을 별도로 고정한다.

1. `text_egress=false`: candidate value/score의 human·agent 전달이 없었다는 operator attestation과
   historical evidence snapshot.
2. `v2_4_d_execution=false`: V2.4-D scorer/ontology/score가 실행되지 않았다.
3. `output_derived_tuning=false`: observed output에 근거한 ontology/alias/metric/threshold/status
   변경이 없었다.
4. Exact command/date, best-known HEAD `c9c94b4`, dirty state, 28 PASS와 세 evidence-source hash를
   immutable snapshot으로 기록한다.
5. Approval이 missing streams, dirty/best-known identity와 waiver를 명시적으로 인지해야 한다.

즉, process access 자체는 인정하되 outcome-adaptation으로 이어지는 세 정보 경로가 차단됐다는
제한된 causal claim이다. Protocol amendment는 candidate score/본문을 사람·agent가 보지 않은 상태에서
이뤄졌고 JLC-D 정의를 바꾸지 않았다. 그러므로 status
`CONFIRMATORY_WITH_DISCLOSED_NONINFORMATIVE_MACHINE_PARSE_DEVIATION`은 수용 가능하다.

#### 허용되지 않는 과장

- 이를 “candidate 접근 0”, “완전한 blinding”, “재현 검증된 non-egress”라고 표현하면 안 된다.
- User waiver는 missing stream을 복원하거나 epistemic uncertainty를 제거하지 않는다.
- 논문/analysis에는 `NOT_RETAINED`, best-known dirty state, attestation 기반이라는 제한을 본문에
  공개해야 한다.
- Evidence hash 불일치, text/score egress, V2.4-D execution, output-derived tuning의 반증이 하나라도
  나오면 confirmatory waiver는 즉시 무효이고 run 전체 `INVALID`다.

이 조건부 confirmatory status는 §11의 primary result status와 별도 methodology disposition이다.
`SUPPORTED`와 합성하거나 일반적 RCA 개선 주장으로 확대할 수 없다. 더 엄격한 독자는 이 편차를
exploratory 근거로 해석할 수 있음을 limitation에 인정해야 하지만, 현재 evidence만으로 강제
`EXPLORATORY_ONLY`로 낮춰야 할 정보성 노출 증거는 없다.

### 18.7 A/A chain — PASS

Revision 7의 chain은 유지된다.

```text
I0: active commitment/deviation path absent
I1^ == I0
I0..I1:
  A  docs/plans/input_commitment_v2_4_deterministic.json
  A  docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json
I1→B: implementation review modification only
B→A: approval addition only
```

Revision 8 implementation code/plan/review는 I0에서 고정되고 I0→I1에서 변할 수 없다. New commitment와
waiver record만 I1에서 추가되며 full review/approval/preflight target map에 포함된다.

### 18.8 Outcome semantic 불변 — PASS

- `JLC-D = CM ∧ FLM ∧ MCA`, 12-pair RAG 대 length-placebo primary 동일.
- CM/FLM/MCA/RA ontology와 alias, DNF, contradiction, negation grammar 동일.
- Exact one-sided McNemar, CP/bootstrap, secondary inference 0 동일.
- Missingness, schema, language, replay, status/warning rule 동일.

Revision 8은 validator, bridge, enumeration, evidence schema와 tests를 강화했을 뿐 outcome acceptance
set이나 성공 임계값을 바꾸지 않았다.

### 18.9 P0 gate 표

| P0 gate | Revision 8 판정 | 근거 |
|---|---|---|
| candidate body 비열람 review | PASS | 본문 접근·검색·출력/scorer 실행 0 |
| producer/runner canonical schema | PASS | single shared validator, direct bridge |
| commitment provenance exactness | PASS | exact keys/types/digests/reviewed_i0 |
| runtime ontology exact validator | PASS | builder/scorer same validator+mutation tests |
| unresolved negation fail-close | PASS | consumed-span remainder runtime assertion |
| raw direct-entry enumeration | PASS | descriptor enumeration, all unexpected entries reject |
| machine-parse deviation disclosure | PASS | process access false claim 금지, exact waiver schema |
| `NOT_RETAINED` scientific handling | PASS | missing evidence를 발명하지 않고 mandatory limitation |
| confirmatory anti-overfitting integrity | PASS 조건부 | non-egress/non-execution/non-tuning evidence 유지 시만 |
| A/A freeze chain | PASS | I0 absence, I1 two additions, code immutable |
| outcome semantic invariance | PASS | ontology/statistics/status threshold 변화 0 |
| test adequacy contract | PASS | direct tests 38~42가 prior counterexamples 포함 |

**합계: PASS 12 / FAIL 0.** 조건부 evidence가 full implementation review/approval에서 충족되지
않으면 그 단계와 run은 FAIL이며 confirmatory waiver는 없다.

### 18.10 최종 판정

**Revision 8 methodology를 승인하도록 권고한다.**

다음 checkpoint는 candidate-unmounted 상태에서 Revision 8 code-only `I0`를 봉인하고 fresh safety
review를 수행하는 것이다. 그 뒤 exact reviewed I0 tool로만 I1 commitment/waiver record를 만들고,
fresh full implementation review가 actual direct bridge·runtime counterexamples·historical waiver
evidence를 모두 검증해야 한다.
