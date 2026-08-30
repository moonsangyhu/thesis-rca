# V2.4 독립 방법론 비평 — Primary03 retrospective measurement audit

> 검토일: 2026-08-30
> 역할: Experiment Track Step 2 fresh hypothesis/methodology reviewer
> 검토 대상: `docs/plans/experiment_plan_v2_4.md`
> 호출 경계: 모델·API·Codex·Copilot·K8s·Chroma 조회를 실행하지 않았으며, 보존 결과의 평점을 생성하지 않았다.

## 0. 최종 판정

**최초 판정: 수정 후 승인(`approve after amendments`).**

**수정본 검증 후 판정: 계획 승인 권고(`approve plan`; P0-1~P0-8 모두 PASS).**

이 판정은 Step 3 구현 시작을 자동 승인하지 않는다. §6의 amendment verification에서 확인한
최종 plan/review hash와 남은 실행 dependency를 사용자에게 제시하고 단일 명시 승인을
받아야 한다.

V2.4를 새 호출 없는 제한적 측정 감사로 한정하고, Primary03을 confirmatory dataset으로
승격하지 않는 방향은 타당하다. 그러나 현재 계획은 그대로 구현 승인하기에는 다음 P0
문제가 남는다.

1. `outcome_source`를 독립변수로 부르는 구성개념 오류와 하나의 가설 안에 크기·방향을
   `OR`로 결합한 판정 불명확성
2. n=36에서 20%·Wilson·κ·Green/Gray/Red 경계가 실제 가능한 정수 판정과 충분히 연결되지 않음
3. 동일 reviewer가 semantic answer reference를 본 뒤 correctness disagreement를
   adjudicate하여 최종 correctness에 의미 참조가 역오염될 수 있는 순서
4. Chroma snapshot의 quiescence/read-only 보장, HMAC canonicalization, package scanner,
   외부 호출 0의 실행 강제가 아직 검증 가능한 계약으로 충분히 구체적이지 않음
5. Step 1 승인과 Step 2 반영본 재승인을 중복 요구하는 hard gate

아래 P0 수정사항을 계획서에 반영하고, 수정된 plan의 hash와 이 review의 hash를 묶어
**사용자 승인을 한 번만** 받은 뒤 Step 3으로 진행해야 한다. 이 review 자체는 구현이나
package 생성이 아니므로 첫 승인을 기다릴 필요가 없다.

## 1. 검토 범위와 확인된 경계

- V2.3 Primary03은 F1~F8의 39 incidents·117 rows인 incomplete, non-random prefix다.
- V2.3 전체 artifact tree에는 `campaign_complete`가 0건이며, 여러 campaign prefix를
  결합할 수 없다.
- V2.4 표본은 12 incidents의 세 condition에서 archived representative output 하나씩,
  총 36 outputs다. semantic audit의 표본은 12 blind-RAG blocks다.
- V2.4가 답할 수 있는 것은 이 36개 archived representative outcome의 측정 일치와
  12개 block의 semantic eligibility뿐이다. RAG 효과, complete campaign 효과, 다른
  모델·cluster·corpus의 judge validity를 답할 수 없다.
- 아래 평가는 계획·이전 분석 문서의 수치만 사용한다. 실제 human rating이나 새로운
  audit 결과를 가정하지 않는다.

## 2. P0 — 구현 승인 전 필수 수정

### P0-1. “단일 독립변수”를 “단일 1차 측정 대비”로 정정한다

**문제.** 같은 archived output에 Terra 판정과 human 판정을 나란히 적용하는
`outcome_source`는 실험자가 조작한 독립변수가 아니다. 이는 paired measurement method다.
또한 현재 H-V2.4는 “discordance가 20%를 넘거나 방향이 체계적”이라는 두 판정을 `OR`로
묶는다. semantic L0~L3도 별도 eligibility construct이므로 “독립변수가 정확히 하나”라는
표현은 설계를 실제보다 단순하게 보이게 한다.

**정확한 수정안.** 계획서 §0·§2 제목과 본문을 다음처럼 바꾼다.

```text
조작 독립변수: 없음(retrospective paired measurement audit)
단일 1차 estimand: archived representative output에서
  P(Terra correct_at_0.5 != adjudicated human score>=1)
보조 estimand: discordance의 Terra-only/human-only 방향
자료 적격성 gate: blind-RAG block의 adjudicated L3 존재 여부
```

H-V2.4의 primary 판정은 discordance 크기로만 고정하고, 방향성은 보조 경고로 분리한다.
`score=2`, condition strata, κ, L0~L2는 sensitivity/descriptive 결과로 유지한다. 문서 전체의
“single independent variable”은 “single primary estimand”로 치환한다.

### P0-2. n=36에서 20%·Wilson gate를 정수 사건 수로 사전 명시한다

**문제.** 결측이 없을 때 20%는 7.2건이므로 point estimate는 7/36=19.4%,
8/36=22.2%에서 갈린다. 그러나 Wilson 95% 상한 `<20%`는 7건 이하가 아니라 **2건 이하**에서만
가능하다. 2/36의 상한은 약 18.1%이고 3/36의 상한은 약 22.1%다. Wilson 하한 `>=20%`는
12/36부터다. 따라서 현재 Green은 명목상 “20% 미만”보다 훨씬 강한 “불일치 최대 2건”이고,
3~11건이 모두 Gray인 넓은 triage다. 이는 불가능한 gate는 아니지만 계획서가 그 실제
운영 의미와 예상 불확실성을 드러내지 않는다.

abstain으로 유효 n이 줄면 경계도 바뀐다. 예를 들어 n=33에서는 Green 최대 2건이지만
n=32에서는 최대 1건이다. 한편 raw agreement 85%는 n=36에서 31/36=86.1%와
30/36=83.3% 사이의 불연속 기준이고, κ 0.70 및 85%는 이 표본과 RCA rubric에서 검증된
cutoff가 아니라 운영 기준이다.

**정확한 수정안.** 계획서 §11에 다음을 추가한다.

1. 분석 코드가 각 실제 `n_non_abstain`에 대해 Wilson 경계를 계산하고 manifest에
   `green_max_discordant_count`, `red_min_discordant_count`를 기록한다.
2. n=36의 사전 표를 명시한다: Green 0~2, Gray 3~11, Red 12~36. 이는 Terra-human
   discordance 축에만 적용한다.
3. 20%, 85%, κ 0.70은 문헌상 보편 cutoff가 아니라 **의사결정용 운영 경계**임을 명시하고,
   point estimate·confusion matrix·CI를 상태 색보다 먼저 보고한다.
4. `A`가 하나라도 있으면 자동 Gray로 두되 임의 대치하지 않는다. 유효 n별 경계를
   재계산한다.
5. 방향성 exact CI가 0.5를 제외하는 조건은 별도 `DIRECTIONAL_ALERT`로 보고한다. 이것만으로
   전체 measurement를 Red로 만들려면 최소 discordant count 또는 최소 전체 방향 차이를
   별도로 사전 지정해야 한다.
6. human-human κ bootstrap은 36 rows를 독립 resample하지 말고 12 incident cluster를
   resample하여 각 incident의 세 condition을 함께 유지한다. semantic weighted κ(n=12)는
   매우 불안정하므로 gate가 아니라 raw matrix와 함께 descriptive로만 둔다.

Green을 “Wilson 상한 `<20%`”로 유지하려면 위와 같이 강한 저불일치 증거로 해석해야 한다.
의도가 단순히 point `<20%`인 경우에는 Wilson 상한 조건을 삭제해야 하며, 두 정의를 섞으면
안 된다.

### P0-3. correctness reference가 무엇을 측정하는지 좁히고 blinding 표현을 정정한다

**문제.** correctness package의 `expected_root_cause`, expected metrics/logs,
expected recovery action은 사실상 incident answer specification이다. label key를 숨겨도
reviewer는 target·mechanism·recovery에서 진단을 알 수 있다. 이는 채점에 필요한 criterion일
수 있으나 “fault label을 숨긴 독립 현실 판정”은 아니다. 더구나 expected evidence는 실제
Primary03 incident에서 관측된 evidence가 아니라 ground-truth 기대값이므로, 결과는
현실의 근본원인 진실보다는 **사전 작성된 synthetic reference와 candidate의 합치도**를
측정할 수 있다.

같은 incident의 reference가 세 번 반복되므로 reviewer는 세 candidate가 한 묶음임을
알아차릴 수 있다. condition 이름은 몰라도 상대 비교·일관성 압력이 생길 수 있다.

**정확한 수정안.** 다음을 plan과 rubric에 명시한다.

- blinding은 `condition/Terra outcome/provider/provenance blind`이며 `diagnostic-reference blind`가
  아니다.
- primary construct 명칭을 “incident-specific correctness의 절대 gold standard”가 아니라
  “frozen ground-truth rubric과의 blinded human concordance”로 한정한다.
- ground-truth reference file hash와 각 제공 필드의 exact source/hash를 package 생성 전에
  lock하고 candidate를 본 뒤 paraphrase·보완하지 않는다.
- expected metrics/logs와 실제 관측 evidence를 혼동하지 않도록 필드명에 `expected_`를
  유지하고 rubric에서 그 차이를 경고한다.
- 세 sibling candidate를 직접 비교하지 말고 각 item을 절대 기준으로 독립 채점하라는
  지침을 둔다. 동일 reference 반복으로 incident grouping을 추론할 수 있다는 한계를
  보고한다.

### P0-4. semantic reference가 correctness adjudication을 오염시키지 않도록 단계 순서를 바꾼다

**문제.** 현재 계획은 correctness 원판정만 lock한 뒤 같은 reviewer에게
`fault_name/alias`, entity, mechanism, injection signature가 든 semantic package를 배포하고,
두 종류의 sheet가 모두 lock된 뒤 correctness disagreement를 adjudicate한다. opaque ID가
달라도 reviewer는 고유 mechanism·entity·candidate 기억으로 incident를 재연결할 수 있다.
따라서 semantic answer reference가 최종 adjudicated correctness를 오염시킬 수 있다.
원판정 lock은 최종 합의점수의 오염을 막지 못한다.

**정확한 수정안.** 아래 순서를 hard gate로 고정한다.

```text
correctness training
→ R1/R2 correctness 독립 판정 lock
→ correctness disagreement adjudication lock
→ correctness phase 폐쇄 선언과 hash commitment
→ 그 후 semantic package 배포
→ R1/R2 semantic 독립 판정 lock
→ semantic adjudication lock
→ sealed key join 및 분석
```

더 강한 대안은 semantic reviewer pair를 correctness pair와 완전히 분리하는 것이다. 동일
pair를 유지한다면 위 순서와 cross-sheet relinking 한계를 필수로 기록한다. semantic
package는 correctness package와 별도 schema/scanner를 사용해야 한다.

### P0-5. Chroma byte reconstruction과 불변성 계약을 구현 가능한 형태로 고정한다

**문제.** source snapshot을 working copy로 복사하는 방향은 좋지만 Chroma/SQLite snapshot이
quiescent한지, WAL/SHM을 포함한 exact tree인지, library open이 migration·telemetry·write를
일으키는지 아직 정해지지 않았다. “timestamp 갱신 금지”는 일반 파일 read의 atime 정책에
따라 content mutation 없이도 위반될 수 있어 content immutability와 섞여 있다.

**정확한 수정안.** 다음을 preflight와 test에 추가한다.

1. source snapshot의 required file inventory와 SHA-256 tree digest를 정의하고 SQLite
   WAL/SHM 존재 여부 및 checkpoint 상태를 fail-closed한다.
2. source에서는 Chroma library를 열지 않고 raw filesystem copy만 수행한다. copy 전후 source
   content digest를 비교한다. timestamp는 별도 stat audit로 보고하되 content mutation
   판정과 분리한다.
3. working copy는 network/telemetry를 차단하고 read-only 또는 SQLite immutable mode로 연다.
   schema migration이나 write 시도는 hard fail한다.
4. `source_id`가 복수 chunk와 매칭될 수 없도록 exact collection ID/document ID/offset을
   지정하고 0건·2건 이상 match를 모두 fail한다.
5. UTF-8 strict decode, Unicode normalization을 **하지 않음**, Python `.strip()`의 exact
   semantics, `\n\n` 결합, `[REDACTED]` byte sequence를 versioned reconstruction spec으로
   고정한다.
6. 12/12 source/masked/additional hash 일치와 source/working tree digest before/after를
   distribution 전 필수 evidence로 남긴다.

### P0-6. package scanner와 HMAC package의 재현·감사 계약을 보강한다

**문제.** allowlist 생성과 recursive scanner는 적절하지만 두 package의 의도적 truth
field가 다르다. 하나의 substring denylist를 공유하면 false positive 또는 semantic
package의 허용 노출을 놓칠 수 있다. scanner 0은 구조화 leakage 0일 뿐, reference 내용으로
incident를 추론하는 semantic leakage 0의 증명이 아니다.

OS CSPRNG master로 만든 HMAC order는 secret이 보존되면 재현 가능하지만, 현재 spec에는
canonical identity의 byte encoding·Unicode·delimiter escaping, HMAC truncation 단위,
secret 복구 시 재생성 절차가 충분히 고정되지 않았다. 공개 commitment만으로 rating 전에
order가 결과 독립적으로 고정됐는지도 제3자가 확인할 수 없다.

**정확한 수정안.** 다음을 manifest에 고정한다.

- correctness/semantic distribution별 exact schema와 별도 scanner policy
- canonical identity를 versioned canonical JSON 또는 length-prefixed UTF-8 bytes로 정의;
  normalization, newline, field order, delimiter ambiguity를 제거
- HMAC algorithm, domain-separation labels, truncation 길이(가능하면 현재 64-bit보다 긴
  128-bit opaque ID), collision check, order tie-break rule
- 최초 생성 secret의 sealed 보존과 SHA-256 commitment; 동일 audit ID 재현은 새 secret을
  만들지 않고 sealed secret을 사용하며 byte-identical archive가 아니면 fail
- package/order/archive hash를 rating 배포 전에 append-only manifest에 commit하고, lock 뒤
  secret 또는 검증 가능한 mapping을 감사 범위에서 공개하는 절차
- sealed answer-key의 모든 known identifier/value에 대해 exact·case-folded·normalized·encoded
  canary fixture를 두고 archive name/header/value/metadata를 검사
- scanner pass의 주장은 “금지된 구조화 field/marker 미검출”로 한정

### P0-7. 0-call/0-K8s를 denylist test가 아니라 실행 격리로 강제한다

**문제.** `codex`, `copilot`, `kubectl` executable denylist와 outbound-network fixture만으로는
Python HTTP client, Chroma telemetry, 다른 binary, 직접 socket, kubeconfig library 접근을
막지 못한다. manifest의 `*_calls=0` 자기기록도 실제 0의 독립 증거가 아니다.

**정확한 수정안.** Step 3 실행 계획에 다음 중 검증 가능한 등가 통제를 요구한다.

- network namespace/container의 `network=none` 또는 OS 수준 egress deny
- proxy·cloud·Kubernetes 관련 환경변수 제거, kubeconfig/service-account 미마운트,
  executable PATH allowlist
- Chroma telemetry 명시적 disable
- child-process와 socket/network attempt를 기록·차단하는 실행 wrapper
- 완료 manifest에 격리 방식, 정책 hash, 차단 attempt 수, child-process inventory를 기록
- test에서 HTTP library, raw socket, DNS, `kubectl`, Kubernetes client library, Chroma
  telemetry 각각의 negative fixture가 실제로 차단되는지 검증

플랫폼이 이를 강제할 수 없다면 완료 문구를 “외부 호출 0 보장”이 아니라 “관측된 외부
호출 0”으로 낮추고 그 관측 한계를 명시해야 한다. 어느 경우에도 live Chroma retrieval,
embedding, 모델 호출, K8s read/write는 허용하지 않는다.

### P0-8. 사용자 hard gate를 한 번으로 통합한다

**문제.** 계획서 §0은 Step 1 승인 뒤 Step 2 review, 다시 반영본 승인을 요구한다. 그러나
Step 2는 구현이 아니라 계획 비평이고, Experiment pipeline도 Step 2 산출물을 구현 전
검토 gate로 둔다. 두 승인은 안전성을 추가하지 않고 동일 설계에 대한 중복 checkpoint가
된다.

**정확한 수정안.** 승인 계약을 다음으로 교체한다.

```text
Step 1 plan 초안
→ Step 2 fresh 독립 review
→ P0 amendment를 plan에 반영
→ plan/review hash와 미해결 P1 목록을 사용자에게 제시
→ 사용자 단일 명시 승인
→ Step 3 구현
```

이 단일 승인 전에는 기존 계획과 동일하게 구현, dry-run, Chroma open/copy, package 생성,
reviewer 배포·채점, 분석, tunnel/K8s 접근을 금지한다.

## 3. Plan critique 5축

### 3.1 구성 타당성

장점은 자동 outcome calibration과 semantic eligibility를 RAG 효과 검정에서 분리하고,
human score `>=1`을 primary, `=2`를 sensitivity로 사전 고정한 점이다. L3를 hard fail로 둔
것도 lexical scanner 0을 semantic safety로 오해하지 않게 한다.

핵심 위협은 측정법 비교를 독립변수로 잘못 명명한 점, ground-truth expected fields를
현실 truth처럼 해석할 위험, semantic severity가 사람의 ordered judgment라는 점이다.
P0-1·3·4를 반영하면 “frozen synthetic reference에 대한 paired measurement concordance”라는
방어 가능한 construct가 된다.

### 3.2 내적 타당성

Primary03 한 campaign만 사용하고 다른 revision을 결합하지 않는 경계, outcome을 selector
input에서 제외한 hash sampling, reviewer별 order, answer-key 분리, append-only lock은
타당하다. 반면 deterministic은 곧 preregistered를 뜻하지 않는다. seed namespace와 sampling
algorithm은 이미 전체 결과를 본 연구자가 선택했고, representative output 자체도 Terra
majority/score로 선택됐다. 따라서 36개 결과는 archived representative endpoint의 감사이지
generation distribution의 unbiased audit가 아니다.

동일 incident의 세 condition이 동일 reference를 공유해 reviewer가 sibling을 알아볼 수 있고,
동일 reviewer의 semantic reference 노출은 현재 adjudication 순서에서 직접 교란이다.
P0-4를 고치고, selection 및 grouping 한계를 결과 해석에 남겨야 한다.

### 3.3 외적 타당성

fault coverage는 F1~F8에 한정되고 일부 fault만 두 incident를 가진 불균형 표본이다.
Primary03 자체가 sequential attrition을 겪은 prefix이고 단일 cluster, Online Boutique,
한 corpus, archived Terra representative outputs에만 해당한다. Green이어도 다음에는
일반화할 수 없다.

- F9~F12 또는 complete 12-fault campaign
- generation 세 번 전체의 judge reliability
- 다른 model/provider/judge rubric
- active GitOps reconciliation, 다른 cluster, production MTTR

문서의 기존 주장 경계는 이 한계를 대체로 올바르게 보존한다.

### 3.4 통계 타당성

n=36은 효과 검정 표본이 아니라 triage 표본이며, 세 condition row는 12 incident 안에
clustered되어 있다. semantic n=12의 weighted κ CI는 특히 불안정하다. 20% Wilson Green은
실제로 불일치 2건 이하만 허용하고 Red는 12건 이상부터여서 Gray가 넓다. 이는 탐색적
three-way decision으로는 가능하지만 정수 경계, abstain 처리, cluster bootstrap,
direction alert를 사전 명시해야 한다.

κ는 prevalence paradox에 취약하므로 raw agreement·confusion을 우선한다는 계획은 옳다.
다만 κ 0.70과 raw 85%를 사람 판정의 “신뢰성 검증”이나 gold-standard 인증으로 표현하면
안 된다. operational flag로만 사용해야 한다.

### 3.5 대안 가설

관측될 Terra-human 불일치 또는 일치는 최소 다음 메커니즘으로도 설명될 수 있다.

1. same-model self-preference가 아니라 ground-truth rubric과 Terra rubric의 threshold 정의가
   다르다(partial correctness `>=1` 대 Terra 0.5).
2. human reviewer가 더 정확한 것이 아니라 expected mechanism/recovery 문구에 anchoring됐다.
3. Terra 대표 output 선택 규칙이 human과 잘 맞는/안 맞는 generation을 선택했다.
4. 특정 fault의 reference 품질·난이도가 sample에서 과대표집됐다.
5. 동일 incident의 세 candidate를 알아본 reviewer가 상대 비교 또는 일관성 압력을 받았다.
6. reviewer expertise, 피로, item order, rubric training 차이가 condition보다 큰 변동을 만들었다.
7. L2/L3는 실제 generator shortcut이 아니라 사람이 reference와 procedure의 사후 유사성을
   과대판정한 결과일 수 있다.
8. Terra-human 높은 일치는 두 측정기가 모두 같은 synthetic ground truth 표현에 정렬된
   공통방법 편향일 수 있다.

그러므로 Red는 same-model bias의 원인을 입증하지 않고 “이 automatic outcome을 단독
근거로 쓰기 부적합”하다는 운영 결론만 지지한다. Green도 Terra의 보편 타당성을 입증하지
않는다.

## 4. P1 — 권장 개선

### P1-1. representative-selection bias를 감사할 목적이면 108을 outcome-contingent하게만 열지 않는다

현재 108-output 확대는 Gray 또는 observed disagreement pattern에 따라 결정된다. 이는 비용
절감에는 적절하지만 representative-selection bias의 무조건적 추정은 아니다. 36개 primary를
유지하되, 108 확대 여부와 무관하게 모든 archived generation identity/hash를 처음부터 sealed
manifest에 고정한다. 확대 시 새 sample 선택 없이 전부 포함한다. 논문에서 generation-level
주장이 필요하면 108 audit을 선택적 escalation이 아니라 별도 사전 승인된 sensitivity로
실행한다.

### P1-2. adjudication 독립성을 높인다

가능하면 disagreement는 원 reviewer의 합의보다 condition/Terra/semantic phase에 blind인
세 번째 domain adjudicator가 판정한다. 두 reviewer 합의를 유지하면 원점수와 disagreement
matrix를 primary evidence로 보존하고, consensus가 uncertainty를 제거한 것처럼 표현하지
않는다.

### P1-3. reviewer qualification과 피로 통제를 사전 기록한다

Kubernetes/SRE 경력 기준, conflict disclosure, synthetic training set의 최소 통과 조건,
세션 분할·휴식·최대 item 수를 plan에 고정한다. 실제 sample item으로 rubric을 수정하지
않고, 수정 시 rubric version과 fresh review 규칙을 적용한다.

### P1-4. gate 민감도 표를 결과 양식에 미리 둔다

20% 외에 10%·15%·25% 경계에서 상태가 어떻게 달라지는지를 descriptive sensitivity로
보고하면 임의 cutoff 의존성을 드러낼 수 있다. 사후에 유리한 threshold를 primary로
교체하지 않는다.

### P1-5. package-only와 measurement-complete를 별도 완료 상태로 유지한다

`PACKAGE_READY_AWAITING_HUMAN_REVIEW`는 기술 산출물 완료일 뿐 H-V2.4 판정 완료가 아니다.
Step 5 분석과 changelog/PR 상태에서도 두 완료를 별도 필드로 유지하고, reviewer가 없으면
Green/Gray/Red와 κ를 생성하지 않는다.

## 5. 승인 체크리스트

다음 항목이 수정 plan에서 모두 확인되면 Step 3 진입을 승인할 수 있다.

- [ ] 조작 독립변수 없음, 단일 primary estimand와 보조/eligibility 결과 분리
- [ ] n=36 및 실제 n별 Wilson 정수 경계, abstain, cluster bootstrap 명시
- [ ] reference 기반 construct와 blinding 범위 정정
- [ ] correctness adjudication 완전 lock 후 semantic package 배포
- [ ] Chroma quiescent snapshot·immutable working-copy·byte spec 명시
- [ ] correctness/semantic 별도 scanner와 HMAC canonicalization·replay spec 명시
- [ ] OS 수준 0-network/0-K8s 실행 격리 또는 주장 수준 하향
- [ ] Step 2 반영 뒤 사용자 단일 승인 hard gate
- [ ] Primary03 incomplete/non-random 및 36 representative-only 주장 경계 유지
- [ ] reviewer 부재 시 rating·adjudication·measurement status 생성 금지

위 P0가 반영되지 않으면 판정은 **reject**로 바뀐다. 반영 후에도 V2.4는 exploratory
measurement triage이며 V2.3의 인과 가설을 성공 또는 기각으로 판정할 수 없다.

## 6. Amendment verification — 수정 계획서 독립 재검증

> 검증 대상: 2026-08-30 수정본 `docs/plans/experiment_plan_v2_4.md`
> 검증 방식: 계획서 전체를 다시 읽고 이 review의 P0-1~P0-8 및 P1-1~P1-5와 일대일 대조
> 실행 경계: 계획 문서 read-only 검토만 수행. 구현·dry-run·Chroma open/copy·모델/K8s 호출 없음

### 6.1 P0 정확 판정

| 항목 | 판정 | 수정본 근거 | 검증 의견 |
|---|---|---|---|
| P0-1 조작변수/estimand | **PASS** | plan §0, §2.1 | 조작 독립변수를 `없음`으로 정정했고 primary를 paired Terra-human discordance magnitude 하나로 고정했다. 방향은 `DIRECTIONAL_ALERT`, semantic은 eligibility gate, score=2는 sensitivity로 분리됐다. |
| P0-2 n=36 gate/통계 | **PASS** | plan §11.1~§11.3, §15.2 | actual `n_non_abstain`에서 Wilson count boundary를 계산하며 n=36의 Green 0~2, Gray 3~11, Red 12~36을 명시했다. A는 Gray override, n=0은 미평가다. 방향 alert는 primary 색을 바꾸지 않고, correctness κ는 12-incident cluster bootstrap, semantic κ는 descriptive point only다. 20%·85%·κ 0.70도 보편 cutoff가 아닌 운영 경계로 한정했다. |
| P0-3 reference construct/blinding | **PASS** | plan §2.1, §6.1, §8, §18 | blinding을 condition/Terra/provider/provenance로 한정하고 diagnostic reference가 보인다는 사실을 명시했다. expected field와 실제 관측 evidence를 구분하고 ground-truth file/row/field hash를 candidate read 전에 lock한다. construct도 frozen synthetic reference와의 human concordance로 좁혔다. sibling grouping 한계도 공개했다. |
| P0-4 semantic 역오염 | **PASS** | plan §6.2, §10.2~§10.4, §15.1~§15.3 | correctness 원판정과 adjudication을 lock하고 phase를 `CLOSED`로 만든 뒤 semantic training/package를 최초 공개하는 순서가 hard gate와 automated/manual test로 고정됐다. 동일 pair의 기억 기반 relinking은 잔여 한계로 남겼다. |
| P0-5 Chroma/byte immutability | **PASS (설계)** | plan §3.2, §5, §15.1~§15.3 | source는 raw filesystem read/copy만 허용하고 WAL/SHM 또는 quiescence 불명확 시 fail한다. working copy digest, immutable/read-only open, migration/journal/telemetry 차단, exact collection/document/offset uniqueness, UTF-8/Python 3.11 strip/LF/REDACTED byte spec 및 12/12 hash gate가 명시됐다. 실제 snapshot과 library 동작은 Step 3 검증 dependency다. |
| P0-6 scanner/HMAC reproducibility | **PASS (설계)** | plan §6.3~§7, §15.2~§15.3 | correctness/semantic 별도 schema·scanner, canonical JSON bytes, domain-separated HMAC-SHA256, 128-bit ID, collision/tie rule, secret commitment, 배포 전 package/order/archive commitment, same-secret byte-identical replay, encoded canary fixtures를 고정했다. scanner pass의 주장도 구조화 marker 미검출로 제한했다. 실제 replay/scanner pass는 Step 3 dependency다. |
| P0-7 0-call/0-K8s enforcement | **PASS (조건부 설계)** | plan §15.1~§16 | network-none 또는 동등 egress deny, credential/K8s mount 제거, PATH allowlist, telemetry off, process/socket 차단·inventory와 negative fixtures를 요구한다. 강제 불가 시 `OBSERVED_ONLY`로 claim을 낮추도록 했다. 어느 수준에서도 live retrieval/model/K8s access는 금지된다. 실제 플랫폼 격리 증거 전에는 0-call 보장 완료를 주장할 수 없다. |
| P0-8 단일 사용자 승인 | **PASS** | plan §0, §14, §19 | Step 1→fresh Step 2→P0 반영→plan/review hash와 P1 bundle→사용자 단일 승인→Step 3 흐름으로 통합됐다. 승인 전 구현·dry-run·Chroma/package/reviewer/분석을 모두 금지한다. |

**P0 종합: 8 PASS / 0 FAIL.** `PASS (설계)`와 `PASS (조건부 설계)`는 계획의 요구사항이
충분하다는 뜻이며 구현·환경 검증이 이미 성공했다는 뜻은 아니다.

### 6.2 P1 및 남은 dependency 판정

| 항목 | 판정 | 상태와 남은 위험 |
|---|---|---|
| P1-1 108 identity 선봉인 | **PASS (계획)** | plan §6.4·§12가 최초 36 package 시 108 identity/output hash를 outcome과 무관하게 봉인하고, escalation은 그 전수만 사용하도록 했다. 아직 실제 sealed manifest는 생성되지 않았다. Gray 뒤 확대는 sensitivity이며 unbiased primary audit가 아니라고 명시했다. |
| P1-2 독립 adjudicator | **PARTIAL / DEPENDENCY** | plan §10.4가 qualified R3를 선호하지만 확보하지 못하면 R1/R2 합의로 fallback한다. 이는 원 review의 권장안과 모순되지 않지만 독립성 개선의 실현 여부는 R3 확보에 달렸다. R3 부재 시 원판정·matrix를 우선하고 consensus 한계를 반드시 보고해야 한다. |
| P1-3 qualification/fatigue | **PASS (계획)** | plan §10.1이 경력/자격, conflict, 외부 synthetic training pass, fresh-pair rubric revision, session 최대량·휴식·시간/fatigue 기록을 사전 고정했다. 실제 적격 reviewer 확보는 dependency다. |
| P1-4 cutoff sensitivity | **PASS (계획)** | plan §11.1과 test가 10/15/25% Wilson sensitivity를 descriptive로 고정하고 primary 20%를 바꾸지 못하게 한다. |
| P1-5 완료 상태 분리 | **PASS (계획)** | plan §13이 technical package, human measurement, analysis status를 분리하고 reviewer 부재 시 rating·κ·gate·H-V2.4 판정을 금지한다. |

남은 실행·해석 리스크는 다음과 같다.

1. **입력 dependency:** exact Primary03/Chroma snapshot이 존재하고 WAL/SHM 없는 quiescent
   상태이며 12/12 byte hash를 재현해야 한다. 실패 시 대체 corpus/campaign을 쓰지 않는다.
2. **격리 dependency:** 실제 호스트가 network-none, credential/K8s unmount, child/socket
   차단을 제공해야 한다. 불가능하면 assurance를 `OBSERVED_ONLY`로 낮추며 보장 표현을
   사용하지 않는다.
3. **사람 dependency:** 기준을 통과한 R1/R2가 없으면 package-only로 종료한다. R3 부재는
   허용된 fallback이지만 adjudication 독립성을 낮춘다.
4. **재현성 dependency:** deterministic archive replay, HMAC commitment, phase별 scanner와
   canary가 실제 test를 통과하기 전에는 blinding/leakage 방지를 완료로 주장할 수 없다.
5. **설계 한계:** deterministic selection은 결과를 본 뒤 설계된 audit trail이고 prospective
   random sample이 아니다. 대표 output은 Terra 선택을 이미 내포하며 36개 결과는 generation
   distribution을 대표하지 않는다.
6. **통계 한계:** n=36에서 Green은 최대 2건이라는 매우 강한 조건이고 Gray 범위가 넓다.
   κ·85%·20%는 운영 경계일 뿐 검증된 보편 validity cutoff가 아니다.
7. **외적 타당성:** 어떤 색도 incomplete Primary03을 confirmatory dataset으로 승격하거나
   RAG 효과·다른 fault/model/cluster로 일반화하지 못한다.

### 6.3 수정본 최종 판정

**계획 승인 권고(`approve plan`).** 수정 계획서는 이 review의 P0-1~P0-8을 모두 충족했고
P1-1·3·4·5를 반영했다. P1-2는 R3 확보라는 실행 dependency로 남지만 계획 승인 blocker는
아니다.

다음 checkpoint는 이 수정 plan과 review의 최종 SHA-256, 위 dependency/P1 상태를 사용자에게
제시해 **단일 명시 승인**을 받는 것이다. 그 승인 전에는 Step 3 구현이나 어떠한 package,
Chroma, reviewer, 모델/K8s 작업도 시작하면 안 된다.
