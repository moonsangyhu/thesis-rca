# 심층 분석: V2.4 측정 감사 설계를 위한 개선점 도출

> 분석일: 2026-08-30
>
> 분석 대상: V2~V2.3 결과·분석·계획, Primary03 보존 artifact, 최근 LLM judge·semantic contamination 문헌
>
> 목적: 새 LLM 호출과 fault injection 없이 V2.3의 outcome measurement를 감사하는 단일 가설 수립
>
> 상태: Experiment Track Step 0.5 — 효과 검증이나 V2.3 재개가 아님

## 0. 결론부터

V2.4의 우선 질문은 **“RAG가 RCA를 개선했는가?”가 아니다.** 그 질문에 답하려면 먼저 V2.3의 자동 outcome이 사람의 incident-specific correctness 판단과 충분히 일치하고, blind-RAG block에 의미론적 정답 지름길이 남지 않았다는 근거가 필요하다. V2.3은 이 두 조건을 사전 요구했지만 human review와 semantic audit를 완료하지 못했다.

따라서 V2.4의 단일 1차 가설은 다음과 같다.

> **H-V2.4:** condition과 기존 점수를 가린 두 독립 사람 reviewer의 합의 판정과 Terra judge의 binary correctness 판정 사이에는, V2.3 결론을 자동 지표 하나에 맡기기 어렵게 만드는 실질적 불일치가 존재한다.

semantic shortcut audit는 별도 성능 가설이 아니라 이 outcome audit의 **자료 적격성 gate**다. 명시적 label/entity 노출이 한 건이라도 발견되면 해당 blind-RAG context를 인과적 RAG 처치로 해석하지 않는다. V2.4는 Primary03을 confirmatory dataset으로 승격하지 않고, 12 incidents × 3 conditions = 36 representative outputs를 사용하는 저비용 triage다.

## 1. 이전 실험이 만든 문제의 계보

### 1.1 V2~V2.1: threshold와 judge가 결론을 바꿀 수 있었다

- V2는 100 rows에서 전체 정답 34/100이었다.
- V2.1은 유효 incident 기준 A 20/58=34.5%, B 25/58=43.1%였지만 threshold를 0.5에서 0.6으로 바꾸면 A 25.9%, B 22.4%로 순위가 역전됐다.
- V2.1 B 정답 25건 중 12건(48%)이 정확히 score 0.5 경계에 있었다.
- 같은 종류의 답을 judge가 0.1과 0.5로 갈라 채점한 사례도 보존됐다.

즉, 자동 채점기의 연속점수를 임의 threshold로 이진화하면 “시스템 효과”와 “측정기 효과”가 분리되지 않는다.

### 1.2 V2.2: 큰 RAG 신호와 큰 retrieval leakage가 함께 나타났다

V2.2의 5-arm 300-row factorial 결과에서 C3 RAG는 39/60=65.0%, C1 runtime은 19/60=31.7%, C5 placebo는 22/60=36.7%였다. RAG−runtime은 +33.3%p였고 threshold 0.6/0.7에서도 RAG가 1위였다. 길이 placebo와 GitOps arm이 모두 36.7%였으므로 단순 길이 효과는 작았다.

그러나 RAG 60건 중 45건(75%)이 주입 fault의 자기 런북을 회수했고, 그 파일명·제목·본문이 진단명을 직접 노출했다. 자기 런북 회수 시 32/45=71%, 미회수 시 7/15=47%였다. 그러므로 V2.2의 큰 수치는 “절차 지식이 reasoning을 개선했다”와 “검색기가 정답지를 제공했다”를 분리하지 못한다.

### 1.3 V2.3: lexical leakage는 줄였지만 outcome과 semantic validity가 미완성이다

V2.3은 runtime, length placebo, blind procedural RAG의 세 조건만 유지하고 label/entity masking, runtime-only query, 동일 길이 proxy, condition-blind judge를 도입했다. 그러나 전체 59 incidents·177 rows·2,124 logical calls를 완주한 campaign은 0건이었다. 최신 campaign들은 서로 다른 code revision과 종료 원인을 가지므로 결합할 수 없다.

V2.4가 사용하는 Primary03 하나의 보존 prefix는 다음과 같다.

| 조건 | rows | correct@0.5 | @0.6 | @0.7 | generation split | mean agreement | median score |
|---|---:|---:|---:|---:|---:|---:|---:|
| runtime | 39 | 23 | 21 | 20 | 18 | 0.607 | 0.86 |
| length placebo | 39 | 23 | 22 | 22 | 19 | 0.598 | 0.86 |
| blind procedural RAG | 39 | 23 | 22 | 22 | 17 | 0.598 | 0.76 |

RAG와 placebo는 21건에서 함께 정답, 14건에서 함께 오답, 각 방향 discordance가 2건씩이다. 점추정은 0%p지만 다음 이유로 효과 없음의 증거가 아니다.

1. Primary03은 F1~F8의 39 incidents만 보유한 incomplete, non-random prefix다.
2. campaign 뒤 F9 injection 실패와 직전 Service exact-recovery 결손이 확인됐다.
3. Terra가 generation과 judge를 모두 수행했다.
4. 계획된 human-primary review와 semantic audit가 없다.
5. representative output은 Terra judge 점수와 majority label로 선택돼 selection stage부터 자동 측정기에 의존한다.

### 1.4 버전 간 한 줄 변화

| 버전 | 관찰 | 남은 핵심 결함 |
|---|---|---|
| V2.1 | B−A +8.6%p | threshold 0.6에서 역전, judge 불안정 |
| V2.2 | RAG−runtime +33.3%p | 자기 런북 75% 회수, label leakage |
| V2.3 | Primary03 세 조건 23/39 동률 | incomplete campaign, semantic audit·human calibration 부재 |
| V2.4 | 무호출 retrospective audit | 효과가 아니라 측정 적격성만 판단 |

## 2. 원시 데이터 질적 분석

### 2.1 정답 3건과 오답 3건 표본

Primary03 raw JSON에서 동일 F1 계열의 정답 3건과 오답 3건을 직접 읽었다. 아래에는 민감한 전체 prompt나 output을 복제하지 않고 판정에 필요한 최소 필드만 기록한다.

| incident·condition | Terra @0.5 | 대표 score | 대표 identified label | 관찰 |
|---|---:|---:|---|---|
| F1-t1 blind RAG | 정답 | 1.00 | Container OOMKilled / CrashLoopBackOff | 진단명이 ground truth와 정렬 |
| F1-t1 runtime | 정답 | 0.98 | container_memory_limit_oom | 진단명이 ground truth와 정렬 |
| F1-t1 placebo | 정답 | 0.70 | NetworkPolicy misconfiguration | 대표 label만 보면 반대인데 root-cause 세부가 부분점수를 받은 것으로 보임 |
| F1-t2 blind RAG | 오답 | 0.18 | NetworkPolicy misconfiguration | 다른 fault family로 이탈 |
| F1-t3 placebo | 오답 | 0.02 | Application container crash / CrashLoopBackOff | 상위 증상에서 멈춤 |
| F1-t3 blind RAG | 오답 | 0.35 | Container OOM kill | label은 맞아 보이나 incident-specific mechanism·target 충족도가 낮게 채점됨 |

이 표는 `identified_fault_type` exact match만으로도, Terra score만으로도 RCA correctness를 충분히 표현하지 못할 수 있음을 보여 준다. 사람 reviewer는 canonical label만 보는 것이 아니라 target, mechanism, causal chain을 사전 정의한 rubric으로 분리해야 한다.

### 2.2 generation 구조

Primary03에서 세 조건의 mean generation agreement는 0.598~0.607이고 split은 17~19/39였다. 즉 대표 output 하나는 각 condition의 생성 분포를 충분히 대표하지 않을 수 있다. 36-output audit는 row-level endpoint를 감사하는 최소안일 뿐, generation selection bias까지 완전히 감사하지 않는다.

이 한계가 실제 결론을 흔들면 escalation은 선택된 12 incidents의 모든 generation 108개를 사람이 보는 것이다. 두 reviewer면 216 ratings가 필요하므로 비용은 1차 최소안의 세 배다.

### 2.3 blind procedure 재구성 가능성 검증

Primary03의 39개 blind-RAG raw는 원문 procedure를 직접 저장하지 않고 candidate source ID·span·source hash·removed span·masked hash를 저장한다. 동결 Chroma collection `k8s-rca-knowledge`에서 source ID로 원문을 가져와 rank별 removed span을 역순으로 `[REDACTED]` 처리한 뒤 두 줄로 결합했다.

- 재구성 대상: 39 blocks
- source length/hash 불일치: 0
- reconstructed `masked_procedure_hash` 불일치: 0
- row `additional_context_hash` 불일치: 0

따라서 새 retrieval이나 embedding 호출 없이 당시 generator가 받은 blind procedure block을 byte-equivalent하게 복원할 수 있다.

## 3. 문헌이 요구하는 감사 원칙

### 3.1 same-model judge는 독립 측정기가 아니다

[Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819)는 GPT-4가 유의한 self-preference를 보이고, 사람이 평가한 것보다 낮은 perplexity의 익숙한 문장을 더 높게 평가하는 경향을 보고했다. V2.3처럼 같은 model family가 생성과 평가를 모두 맡으면 condition blinding만으로 이 상관오차를 제거할 수 없다.

[Judging the Judges](https://aclanthology.org/2025.ijcnlp-long.18/)는 15 judges, 22 tasks, 약 40 generator models, 150,000건 이상의 평가에서 position bias가 우연이 아니며 judge·task·candidate에 따라 달라짐을 보였다. 따라서 V2.4 package는 condition 순서와 item 순서를 opaque ID로 무작위화하고 reviewer마다 다른 order를 제공해야 한다.

[Humans or LLMs as the Judge?](https://aclanthology.org/2024.emnlp-main.474/)는 수천 건 평가에서 인간과 LLM judge 모두 여러 perturbation과 bias에 취약하다고 보고했다. 사람 판정을 무조건 gold standard라고 부르지 않고, 두 독립 reviewer의 합의와 disagreement pattern을 함께 제시해야 한다.

### 3.2 lexical scanner 0은 semantic shortcut 0이 아니다

[SSA: Semantic Contamination](https://aclanthology.org/2025.emnlp-main.744/)은 token overlap만으로 잡히지 않는 semantic contamination을 entity-shift perturbation으로 감사했다. 45 model variants와 4 contamination levels에서 SSA factor가 contamination과 거의 완전하게 함께 움직였다(3B 이상 `r≥.97`, 전체 `ρ≥.9`). 분야는 다르지만 “정확한 단어를 지웠다”와 “정답을 사실상 유일하게 만드는 mechanism cue를 지웠다”가 다르다는 원리는 V2.3에 직접 적용된다.

V2.4는 model call이 없는 범위이므로 entity-shift 재생성까지 하지 않는다. 대신 사람이 각 reconstructed block을 L0~L3의 ordered severity로 판정하고 explicit label/entity를 별도 flag로 남긴다.

### 3.3 사람 평가는 guideline과 agreement 없이는 자동으로 신뢰할 수 없다

[Defining and Detecting Vulnerability in Human Evaluation Guidelines](https://aclanthology.org/2024.naacl-long.441/)는 최근 top-conference human-evaluation 논문 중 guideline 공개가 29.84%에 불과했고, 공개 guideline의 77.09%에서 취약점을 찾았다. 그러므로 V2.4는 “전문가가 봤다”가 아니라 rubric, 예시, abstain, adjudication 규칙을 산출물로 고정해야 한다.

[Counting on Consensus](https://aclanthology.org/2026.lrec-1.347/)는 task type, label imbalance, missingness에 따라 agreement metric을 골라야 하고 confidence interval과 disagreement pattern을 함께 보고할 것을 권한다. V2.4는 raw agreement와 Cohen's κ를 binary correctness에, weighted κ를 ordinal leakage severity에 사용하고 prevalence paradox가 의심되면 confusion matrix를 우선 해석한다.

## 4. V2.4의 구성개념과 단일 독립변수

### 4.1 무엇을 측정하는가

V2.4의 대상은 RAG 효과가 아니라 **outcome source**다.

- 자동 outcome: 보존된 Terra `correct_at_0.5`
- 독립 outcome: 두 human reviewer가 condition과 Terra 결과를 보지 않고 판정한 incident-specific correctness
- 단일 대비: `Terra outcome ↔ adjudicated human outcome`

context condition은 V2.4의 조작변수가 아니라 disagreement를 설명하기 위한 고정 strata다. semantic severity도 성능 처치가 아니라 blind-RAG 자료 적격성 검사다.

### 4.2 correctness rubric

reviewer는 anonymized case별로 다음 reference criterion을 본다. condition, Terra score/vote, model/provider, campaign ID, fault ID/trial ID는 보지 않는다.

1. **0 Incorrect:** 핵심 fault family 또는 target/mechanism이 틀렸고 incident를 해결하지 못함.
2. **1 Partially correct:** 상위 fault family나 주된 증상은 맞지만 target, mechanism, causal chain 중 중요한 항목이 빠지거나 잘못됨.
3. **2 Fully correct:** target과 mechanism이 reference에 부합하고 관측 evidence와 인과 설명이 모순되지 않음.
4. **A Abstain:** reference/output만으로 판정 불가능하거나 guideline 자체가 모호함. 결측을 억지로 0/1/2로 만들지 않음.

primary human binary는 adjudicated score `≥1`과 `=2` 두 threshold를 모두 탐색 보고한다. 어느 하나를 사후에 “맞는 threshold”로 고르지 않는다. 이는 기존 Terra 0.5와 사람의 partial-credit 정의가 같은지 감사하기 위한 것이다.

### 4.3 semantic shortcut rubric

각 12개 reconstructed blind-RAG block은 outcome을 보지 않은 별도 sheet에서 판정한다.

| 등급 | 정의 | 처리 |
|---|---|---|
| L0 generic | 여러 fault에 공통인 일반 확인·분기·복구 절차 | 적격 |
| L1 weak narrowing | 넓은 fault family를 좁히나 답을 유일하게 만들지 않음 | flag, sensitivity |
| L2 unique mechanism cue | label 없이도 해당 incident mechanism을 사실상 유일하게 암시 | 부적격 후보, 원문 재설계 필요 |
| L3 explicit shortcut | canonical/alias label, target entity, injection-specific value·명령 직접 노출 | hard fail |

`label_exposed`, `entity_exposed`, `injection_specific`, `generic_procedure`를 별도 boolean으로 기록한다. L3가 한 건이라도 있으면 V2.3의 “leakage-controlled RAG” 표현을 철회한다. L2 비율은 기술하되 n=12에서 보편 threshold를 주장하지 않는다.

## 5. outcome-blind deterministic sample

### 5.1 선택 규칙

관측된 F1~F8 모두에서 한 incident를 먼저 뽑고, 그중 네 fault에 두 번째 incident를 배정해 총 12개를 만든다. 선택에는 correctness, score, output, condition이 들어가지 않는다.

seed material은 다음 immutable provenance를 결합한다.

```text
v2.4-measurement-audit-v1
| campaign_id
| schedule_hash
| corpus_version
```

그 seed의 공개 SHA-256은 `b6d27015ce04ec86b7296e3762b2a38eb98ba5b5e602ca6c357d7533f62fbbe8`이다. fault 내 primary incident는 `SHA256(seed|primary|fault|trial)` 최솟값, second-stratum fault 네 개는 `SHA256(seed|secondary-fault|fault)` 최솟값, 그 fault의 추가 incident는 `SHA256(seed|secondary-incident|fault|trial)` 최솟값으로 고른다.

### 5.2 선택 결과

- F1-t2, F1-t3
- F2-t1
- F3-t3, F3-t4
- F4-t1
- F5-t2, F5-t3
- F6-t5
- F7-t1, F7-t3
- F8-t3

두 번째 sample을 받은 strata는 F5, F7, F3, F1이다. 각 incident의 세 condition을 모두 포함해 36 outputs를 만든다. 이 목록은 review 결과를 보기 전에 이 문서에 고정한다.

## 6. 개선 가설 후보

### 가설 A: 36 representative-output dual-human audit + semantic eligibility screen

**변경 변수:** outcome source를 Terra-only에서 blinded dual-human calibration으로 바꾼다.

**데이터 근거:** Primary03 세 조건은 23/39 동률이지만 RAG↔placebo discordance 4건이 있고, generation split이 17~19/39다. F1 raw 표본은 label과 Terra score의 관계가 단순하지 않음을 보여 준다.

**문헌 근거:** self-preference, position bias, 사람·LLM 양측 bias, guideline vulnerability.

**메커니즘:** condition과 자동 점수를 가린 사람 판정으로 same-model correlated error를 식별한다.

**예상 효과:** accuracy 향상 예측이 아니라 `Terra-human discordance`, 방향별 confusion, human-human agreement의 측정.

**성공 기준:** package blind 검증 통과, 두 reviewer sheet 독립 lock, binary raw agreement ≥85%와 κ≥0.70이면 adjudication 결과를 최소 calibration 근거로 사용한다. 미달이면 rubric을 수정해 새 독립 review를 하며 기존 점수를 덮어쓰지 않는다.

**리스크:** 36개로 discordance CI가 넓고 representative selection bias를 감사하지 못한다.

**구현 범위:** deterministic selector, Chroma reconstruction, redacted review workbook/CSV, separate answer key, analysis script. LLM/K8s 호출 0.

### 가설 B: 선택 12 incidents의 모든 generation 108-output audit

**변경 변수:** representative output만 보던 sample unit을 세 generation 전체로 확장한다.

**근거:** Primary03 generation agreement 약 0.60, split 44~49%이므로 대표 선택이 정보를 버린다.

**메커니즘:** generator variance와 representative-selection variance를 Terra judge error에서 분리한다.

**예상 효과:** accuracy 향상이 아니라 selection-stage disagreement를 정량화한다.

**리스크/비용:** reviewer 두 명 기준 216 ratings로 A의 세 배이며 피로·순서 효과가 커진다.

**구현 범위:** A와 같되 generation별 raw output을 전부 추출. A가 모호할 때만 escalation한다.

### 가설 C: entity-shift semantic counterfactual

**변경 변수:** blind procedure의 mechanism/entity를 counterfactual로 바꿔 model 응답 민감도를 본다.

**근거:** SSA가 token-overlap 밖 semantic contamination을 entity shift로 감지했다.

**메커니즘:** model이 runtime evidence보다 procedure shortcut에 의존하면 counterfactual shift에 따라 진단이 이동한다.

**예상 효과:** mechanism-level shortcut의 더 강한 인과 검증.

**리스크:** 새 LLM 호출, 새 prompt, 새로운 평가 corpus가 필요해 현재 무호출 V2.4 범위를 위반한다.

**구현 범위:** 후속 별도 실험으로만 보류한다.

## 7. 권장 우선순위와 판정 규칙

### 7.1 1순위: 가설 A

가설 A가 비용 대비 정보량이 가장 크고 현재 authorization과 일치한다. B는 A에서 다음 중 하나가 나오면 확장한다.

- human-human raw agreement <85% 또는 κ<0.70
- Terra-human binary discordance가 20% 이상이거나 Wilson 95% CI가 실질적 저불일치 구간과 명확히 분리되지 않음
- condition별 disagreement 방향이 서로 반대
- representative output의 선택 근거가 disagreement 사례의 중심으로 의심됨

20%는 보편 타당성 cutoff가 아니라 n=36 triage용 운영 경계다. raw confusion과 Wilson CI를 함께 보고하며, 19%와 21%를 본질적으로 다른 현상처럼 해석하지 않는다.

### 7.2 Green / Gray / Red

| 상태 | 조건 | 다음 행동 |
|---|---|---|
| Green | human-human ≥85%, κ≥0.70; Terra-human discordance <20%; L3=0 | 자동 outcome을 제한적 보조지표로 유지. V2.3은 여전히 incomplete라 효과 주장은 금지 |
| Gray | agreement/discordance CI가 모호하거나 reviewer abstain·rubric 분쟁이 큼 | B로 108 outputs 확대 또는 독립 domain reviewer 추가 |
| Red | L3 ≥1, human-human 신뢰성 실패, 또는 Terra-human 방향성 체계적 불일치 | V2.3 자동 correctness와 blind-RAG construct를 논문 효과 근거에서 제외하고 rubric/corpus 재설계 |

### 7.3 분석 산출물

1. reviewer별 0/1/2/A 분포와 abstain 사유
2. raw agreement, Cohen's κ, weighted κ, 95% CI
3. Terra vs reviewer/adjudication confusion matrix와 discordance Wilson CI
4. condition별 disagreement 방향은 descriptive only
5. L0~L3 분포와 boolean shortcut flags
6. reviewer adjudication log; 원 review sheet는 append-only 보존

confirmatory effect size, McNemar p-value, RAG−placebo CI는 계산하지 않는다. sample이 outcome audit용이고 campaign이 incomplete이기 때문이다.

## 8. 타당성 위협과 falsifiability

### 구성 타당성

- human review도 incident-specific reference가 불완전하면 오류를 낸다.
- fault label을 완전히 숨기면 correctness 판단 자체가 불가능하므로 reviewer에게 anonymized scoring reference를 제공한다. 숨기는 것은 condition, Terra 결과, campaign identity다.
- L0~L3는 semantic shortcut severity이지 contamination의 객관적 물리량이 아니다.

### 내적 타당성

- deterministic hash는 결과를 보고 sample을 고르는 위험을 줄이지만 author choice를 논리적으로 불가능하게 만들지는 않는다. seed material과 선택 결과를 구현 전에 공개해 audit trail을 만든다.
- reviewer는 서로 상의하지 않고 sheet를 lock한 뒤 adjudication한다.
- answer key와 reviewer package는 물리적으로 분리하고 package scanner가 condition, score, fault/trial ID, provider/model string을 fail-closed한다.

### 외적 타당성

- Primary03 F1~F8, 한 cluster, Online Boutique, 한 corpus, Terra outputs에만 해당한다.
- human reviewer agreement가 높아도 다른 corpus/model의 judge reliability를 보증하지 않는다.

### 통계 타당성

- n=36은 20% discordance에서도 약 7건뿐이므로 구간이 넓다.
- κ는 prevalence imbalance에 민감하므로 raw agreement와 confusion matrix 없이 단독 사용하지 않는다.
- reviewer가 실제로 제공되지 않으면 점수를 생성하거나 결과 분석 완료를 주장하지 않는다.

### 반증 가능성

가설 A는 다음 관찰로 약화된다: 두 human reviewer가 충분히 합의하고 Terra와도 거의 모두 일치하며, semantic L3가 0이고 L2도 드물다. 이 경우 same-model judge/semantic shortcut이 Primary03 해석을 크게 흔든다는 우려는 이 표본에서 지지되지 않는다. 그래도 incomplete campaign 때문에 RAG 효과가 입증되는 것은 아니다.

## 9. 구현 전 hard gate

다음 상세 계획과 독립 방법론 리뷰가 승인되기 전 package generator를 구현하지 않는다.

1. 두 reviewer 역할과 독립 lock/adjudication 절차
2. review package에 제공할 anonymized case reference의 정확한 필드
3. correctness 0/1/2/A와 semantic L0~L3의 예시·경계
4. sample seed, 12 incident 목록, item-order randomization
5. answer-key separation과 leakage scanner forbidden fields
6. reviewer 부재 시 package-only 종료
7. LLM/API/Codex/Copilot 0, K8s mutation/fault injection 0

## 10. 최종 권고

V2.4는 논문의 본 실험을 대체하지 않는다. 그러나 지금 바로 새 2,124-call campaign을 반복하는 것보다 먼저 해야 할 가장 정보 효율적인 단계다. 측정기가 부적격이면 새 실험은 잘못된 outcome을 더 정밀하게 반복할 뿐이다.

권장 순서는 다음과 같다.

1. 가설 A의 상세 plan과 독립 방법론 비평을 완료한다.
2. 승인 후 zero-call package를 생성하고 두 사람 reviewer가 실제 채점한다.
3. Gray일 때만 가설 B로 확대한다.
4. Red면 judge rubric과 blind corpus를 재설계한다.
5. Green이고 논문의 핵심 주장이 여전히 “leakage-controlled RAG가 RCA를 개선한다”라면, model-free 59-incident lifecycle qualification을 먼저 완주한 뒤에만 fresh complete main campaign을 검토한다.

## 부록 A. 데이터·코드 검증 기록

- 모든 `results/experiment_results_v*.csv`를 Python `csv.DictReader`로 파싱했다.
- Primary03 CSV 117 rows와 raw 117 files의 정합성은 V2.3 독립 분석에서 검증됐다.
- 본 분석은 Primary03 조건별 threshold, split, agreement, paired discordance를 다시 계산했다.
- raw qualitative sampling은 정답 3건·오답 3건을 충족한다.
- 39 blind procedure blocks를 동결 Chroma에서 재구성했고 hash failure는 0건이다.
- 기존 CSV, raw JSON, ground truth, artifact를 수정하지 않았다.

## 부록 B. 해석 경계

이 문서에서 말하는 “Terra”는 V2.3 ledger의 command-bound requested model이다. provider-reported backend model identity는 아니다. `ai_credits=0.0`도 실제 비용 0의 증거가 아니다. V2.4는 어떤 inference subprocess도 실행하지 않으므로 이 두 불확실성을 추가로 확대하지 않는다.
