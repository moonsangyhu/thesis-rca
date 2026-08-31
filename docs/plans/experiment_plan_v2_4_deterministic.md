# V2.4-D 결정론적 lexical concordance 실험 계획 — revision 6

> 작성일: 2026-08-31
>
> 단계: Experiment Track Step 1 — semantic review Revision 5 P0 반영본, 재구현·실행 전
>
> revision 6 근거: cumulative `docs/plans/review_v2_4_deterministic.md` Revision 5의
> commitment identity/review-before-real-access P0 두 개
>
> 선행 분석: `docs/surveys/deep_analysis_v2_4_deterministic.md`
>
> 기존 계획 보존: `docs/plans/experiment_plan_v2_4.md`는 사람 측정 감사의 정본으로 유지한다.

## 0. 결론과 승인 경계

V2.4-D는 새 생성 실험이 아니라, V2.3 Primary03에서 이미 동결된 12개 incident의
`blind_procedural_rag`와 `length_placebo` 대표 출력에 공개 benchmark 방식의 구조화
결정론적 채점을 적용하는 retrospective paired experiment다.

단일 검증 질문은 다음과 같다.

> **H-V2.4-D:** 동일 incident에서 blind procedural RAG는 length placebo보다
> deterministic Joint Lexical Concordance(`JLC-D`)를 높이는가?

- **독립변수:** `context_condition` 한 가지
  (`blind_procedural_rag` 대 `length_placebo`). 두 조건은 V2.3에서 이미 생성·동결됐다.
- **종속변수:** incident별 binary `JLC-D = CM ∧ FLM ∧ MCA`.
- **고정:** incident, representative-selection rule, 생성 결과, ground truth, 모델 provenance,
  scorer version, ontology, 정규화, 통계 절차.
- **새 호출:** LLM/API/Codex/Copilot 0, K8s/Prometheus/Loki/SSH 0, fault injection 0.
- **모델 정책:** 향후 호출이 있다면 `gpt-4o-mini` 고정 원칙을 적용하지만, 본 round에는
  모델 호출이나 모델 비교가 없다. Primary03의 봉인된 upstream model provenance를 그대로
  기록하며 모델을 독립변수로 해석하지 않는다.
- **구성개념 경계:** `CM`은 culprit localization이 아니라 component token mention이고,
  `FLM`은 fault 이해가 아니라 canonical label mention이다. 이 결과는 frozen synthetic
  ground-truth와 구조화 free-text의 lexical concordance다. Cloud-OpsBench CA/FA/JRA와
  호환되거나 동등하지 않으며 사람 의미 평가, production RCA, MTTR 개선을 뜻하지 않는다.

이 문서와 Step 2 독립 방법론 review가 확정되고, ontology·scorer·synthetic tests의 hash가
candidate 결과를 보기 전에 봉인된 뒤, 사용자가 그 bundle을 명시 승인하기 전에는 구현 결과를
실데이터에 적용하지 않는다. 이 문서 작성 과정에서는 candidate의
`identified_fault_type`, `root_cause`, `remediation` 본문을 열거나 출력하지 않는다.

## 1. 근거와 이전 결과

### 1.1 왜 측정법을 바꾸는가

- V2.3에는 완결 campaign이 0개여서 59-incident confirmatory 효과를 판정할 수 없다.
- 보존된 Primary03은 F1~F8의 비무작위 prefix지만, 선택된 12 incidents에는 runtime,
  length placebo, blind procedural RAG 대표 출력이 각각 하나씩 존재한다.
- 기존 V2.4 human audit package는 기술적으로 완성됐지만 human rating과 adjudication이 모두
  0이라 measurement gate가 `NOT_EVALUATED`다.
- 사람을 AI judge로 대체하면 same-family 평가 순환과 추가 호출이 생긴다. 따라서 이미 존재하는
  incident ground truth를 구조화 ontology로 고정해 deterministic하게 재채점한다.

### 1.2 공개 평가 계약

- [Cloud-OpsBench](https://github.com/LLM4Ops/Cloud-OpsBench)의 Component Accuracy,
  Fault-Type Accuracy, Joint RCA Accuracy는 구조화 축 분리의 선행 사례로만 참고한다. 자유서술
  token mention을 쓰는 본 실험은 그 metric을 재현하거나 compatible extension을 구성하지 않는다.
- [RCAEval](https://github.com/phamquiluan/RCAEval)은 root-cause service와 fault type의
  ground-truth 기반 exact scoring 근거다.
- [OpenRCA](https://github.com/microsoft/OpenRCA)는 free-text RCA의 최종 제출을 component와
  reason으로 구조화하는 근거다.
- [AIOps Challenge 2025](https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval/-/commit/57c36fa46fb2f4dec19b5f5ca9cbf5a90f9c9e00?file_path=AIOps2025/README.md)의
  key observation 구조는 mechanism concept atom을 사전 고정하는 근거다.

공개 dataset의 정답을 본 데이터에 이식하지 않는다. metric 구조와 taxonomy 명명만 차용하고,
정답은 기존 `results/ground_truth.csv`의 선택된 12행에서만 도출한다.

### 1.3 입력 표본

선택 집합은 다음으로 고정한다.

```text
F1-t2, F1-t3, F2-t1, F3-t3, F3-t4, F4-t1,
F5-t2, F5-t3, F6-t5, F7-t1, F7-t3, F8-t3
```

조건별 12행, 총 36행이어야 한다.

```text
runtime                 12  (secondary descriptive comparator)
length_placebo          12  (primary control)
blind_procedural_rag    12  (primary treatment)
```

Primary03 CSV의 사전 확인 SHA-256은 다음 값으로 고정한다.

```text
5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b
```

행 수 117, raw JSON 117, 선택 ground-truth 12, 선택 출력 36이라는 identity/schema 계수만
선행 분석에서 확인했다. candidate 문자열은 ontology 입력으로 사용하지 않는다.

## 2. 측정 정의

각 candidate에 다음 네 축을 계산한다.

| 축 | 허용 입력 field | 합격 조건 |
|---|---|---|
| `CM` | `root_cause`만 | canonical target component token이 언급됨 |
| `FLM` | `identified_fault_type`만 | canonical fault label의 orthographic variant가 언급됨 |
| `MCA` | `root_cause`만 | incident-specific mechanism positive path 만족, contradiction 없음 |
| `RA` | `remediation[]`만 | accepted recovery path 하나를 완성, contradiction 없음 |

- **Primary:** `JLC-D = CM ∧ FLM ∧ MCA`.
- **Secondary:** `FULL = JLC-D ∧ RA`, `CM`, `FLM`, `MCA`, `RA`.
- **Relaxed sensitivity:** `JLC-relaxed = CM ∧ FLM`.
- candidate의 한 field에 있는 정답 단어는 다른 축으로 이동하지 않는다.
- `RA`는 primary 판정에 포함하지 않는다. 복구 품질 저하는 별도
  `REMEDIATION_REGRESSION_FLAG`로 보고한다.

`CM`은 canonical component가 `root_cause` 안에서 어떤 문법적 역할을 하는지 판별하지 않는다.
피해 대상·dependency·배제된 대안으로 언급돼도 token 자체는 match할 수 있다. 따라서 primary의
정확한 명칭은 `JLC-D`이며, component localization, fault classification accuracy, JRA 또는
semantic correctness로 바꿔 부르지 않는다.

## 3. Ontology JSON 계약

구현 파일은 `experiments/v2_4_deterministic/ontology_v1.json` 하나다. 아래 JSON Schema와
§4~§6의 값이 의미 정본이다. 구현 중 표현 형식만 바꾸는 경우에도 review와 hash를 다시 받는다.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["ontology_version", "normalization", "token_predicates", "negation", "incidents"],
  "properties": {
    "ontology_version": {"const": "v2.4-d-ontology-1"},
    "normalization": {
      "type": "object",
      "additionalProperties": false,
      "required": ["unicode", "case", "clause_boundaries", "tokenization"],
      "properties": {
        "unicode": {"const": "NFKC"},
        "case": {"const": "casefold"},
        "clause_boundaries": {
          "const": [".", ";", ":", "!", "?", "\\n", "\\r"]
        },
        "tokenization": {"const": "maximal_unicode_alphanumeric_runs"}
      }
    },
    "token_predicates": {
      "const": {
        "MEMORY_LIMIT_EXCEEDED_V1": [
          ["exceeded", "memory", "limit"],
          ["exceeded", "16mi", "memory", "limit"],
          ["exceeded", "24mi", "memory", "limit"],
          ["exceeded", "16", "mib", "memory", "limit"],
          ["exceeded", "24", "mib", "memory", "limit"],
          ["memory", "exceeded", "limit"],
          ["memory", "exceeded", "the", "limit"],
          ["memory", "usage", "exceeded", "limit"],
          ["memory", "usage", "exceeded", "the", "limit"]
        ]
      }
    },
    "negation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["tokens", "phrases", "fillers", "coordinators", "contrasts",
                   "exceptions", "grammar_ids", "syntax"],
      "properties": {
        "tokens": {"const": ["no", "not", "never", "without", "neither", "nor",
                              "isnt", "wasnt", "arent", "werent", "cannot", "cant",
                              "didnt", "doesnt", "wont"]},
        "phrases": {"const": ["rule out", "ruled out", "not the cause", "not a cause",
                               "not the root cause", "not the issue", "not the fault"]},
        "fillers": {"const": ["a", "an", "the", "any", "evidence", "sign", "signs",
                               "indication", "indications", "of", "for"]},
        "coordinators": {"const": ["and", "or", "nor"]},
        "contrasts": {"const": ["but", "however", "instead", "rather"]},
        "exceptions": {"const": ["not only"]},
        "grammar_ids": {"const": ["PRE_DIRECT", "PRE_COORD", "PRE_RULE", "POST_RULE",
                                   "POST_CAUSE", "NOT_ONLY"]},
        "syntax": {
          "const": {
            "precedence": ["NOT_ONLY", "ABSENCE_ASSERTION", "PRE_COORD", "PRE_DIRECT",
                           "PRE_RULE", "POST_RULE", "POST_CAUSE", "UNRESOLVED_FAIL"],
            "PRE_DIRECT": ["NEG", "FILLER_0_3", "C"],
            "PRE_COORD": ["NEG", "FILLER_0_3", "C", "COORD", "FILLER_0_3", "C", "REPEAT_COORD_C"],
            "PRE_RULE": ["RULE_OUT", "FILLER_0_3", "C"],
            "POST_RULE": ["C", "OPTIONAL_COPULA_OR_HAS_BEEN", "RULED_OUT"],
            "POST_CAUSE": ["C", "COPULA", "NOT", "OPTIONAL_ARTICLE", "CAUSE_TERM"],
            "NOT_ONLY": ["NOT", "ONLY", "C1", "BUT", "C2"],
            "scope_terminators": ["COMMA", "CLAUSE_BOUNDARY", "but", "however", "instead", "rather"],
            "unresolved_action": "INVALID_UNSUPPORTED_NEGATION"
          }
        }
      }
    },
    "incidents": {
      "type": "array",
      "minItems": 12,
      "maxItems": 12,
      "items": {"$ref": "#/$defs/incident"}
    }
  },
  "$defs": {
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_kind", "source_ref"],
      "properties": {
        "source_kind": {"enum": ["ground_truth", "public_taxonomy"]},
        "source_ref": {"type": "string", "minLength": 1}
      }
    },
    "matcher": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "value", "polarity", "provenance"],
      "properties": {
        "kind": {"enum": ["literal", "token_predicate"]},
        "value": {"type": "string", "minLength": 1},
        "polarity": {"enum": ["affirmative", "absence_assertion"]},
        "provenance": {"$ref": "#/$defs/provenance"}
      },
      "allOf": [
        {
          "if": {"properties": {"kind": {"const": "token_predicate"}}},
          "then": {"properties": {"value": {"const": "MEMORY_LIMIT_EXCEEDED_V1"}}}
        }
      ]
    },
    "group": {
      "type": "object",
      "additionalProperties": false,
      "required": ["group_id", "any_of"],
      "properties": {
        "group_id": {"type": "string", "pattern": "^[A-Z0-9_]+$"},
        "any_of": {
          "type": "array", "minItems": 1,
          "items": {"$ref": "#/$defs/matcher"}
        }
      }
    },
    "path": {
      "type": "object",
      "additionalProperties": false,
      "required": ["path_id", "all_of"],
      "properties": {
        "path_id": {"type": "string", "pattern": "^[A-Z0-9_]+$"},
        "all_of": {
          "type": "array", "minItems": 1,
          "items": {"$ref": "#/$defs/group"}
        }
      }
    },
    "axis": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_fields", "positive_paths", "contradictions"],
      "properties": {
        "source_fields": {
          "type": "array", "minItems": 1, "uniqueItems": true,
          "items": {"enum": ["identified_fault_type", "root_cause", "remediation"]}
        },
        "positive_paths": {
          "type": "array", "minItems": 1,
          "items": {"$ref": "#/$defs/path"}
        },
        "contradictions": {
          "type": "array",
          "items": {"$ref": "#/$defs/group"}
        }
      }
    },
    "incident": {
      "type": "object",
      "additionalProperties": false,
      "required": ["incident_id", "fault_id", "trial", "canonical", "axes"],
      "properties": {
        "incident_id": {"type": "string", "pattern": "^F[1-8]-t[1-5]$"},
        "fault_id": {"type": "string", "pattern": "^F[1-8]$"},
        "trial": {"type": "integer", "minimum": 1, "maximum": 5},
        "canonical": {
          "type": "object", "additionalProperties": false,
          "required": ["component", "fault", "mechanism", "remediation"],
          "properties": {
            "component": {"type": "string"}, "fault": {"type": "string"},
            "mechanism": {"type": "string"}, "remediation": {"type": "string"}
          }
        },
        "axes": {
          "type": "object", "additionalProperties": false,
          "required": ["component_mention", "fault_label_mention", "mechanism", "remediation"],
          "properties": {
            "component_mention": {"$ref": "#/$defs/axis"},
            "fault_label_mention": {"$ref": "#/$defs/axis"},
            "mechanism": {"$ref": "#/$defs/axis"},
            "remediation": {"$ref": "#/$defs/axis"}
          }
        }
      }
    }
  }
}
```

`literal`은 normalization 후 완전한 token sequence로만 match한다. raw-text regex는 전면
금지한다. 유일한 `token_predicate` 값은 `MEMORY_LIMIT_EXCEEDED_V1`이며 다음 유한 token sequence
중 하나와 exact 일치한다.

```text
exceeded memory limit
exceeded 16mi memory limit
exceeded 24mi memory limit
exceeded 16 mib memory limit
exceeded 24 mib memory limit
memory exceeded limit
memory exceeded the limit
memory usage exceeded limit
memory usage exceeded the limit
```

다른 predicate ID, wildcard, substring, raw regex, fuzzy match는 schema validation에서 거부한다.
모든 matcher는 `provenance.source_ref`에 exact ground-truth row/column 또는 공개 taxonomy URL과
label을 기록한다. candidate 표현은 provenance가 될 수 없다.

`build_ontology.py`와 scorer loader는 같은 duplicate-rejecting JSON loader를 사용한다.
`json.loads(..., object_pairs_hook=reject_duplicate_pairs)`로 모든 nesting level의 duplicate key를
거부하며, standard `json.load()` fallback은 금지한다. schema 검증 뒤 static validator가 다음을
추가로 exact 강제한다.

- `ontology_version`, `normalization` 네 값과 배열 순서, `token_predicates` ID/9 sequences/order,
  `negation`의 tokens·phrases·fillers·coordinators·contrasts·exceptions·grammar_ids·`syntax` 전체를
  위 JSON literal과 canonical byte comparison한다.
- duplicate-rejecting loader가 보존한 object-pair order도 top-level
  `ontology_version,normalization,token_predicates,negation,incidents`, normalization
  `unicode,case,clause_boundaries,tokenization`, negation
  `tokens,phrases,fillers,coordinators,contrasts,exceptions,grammar_ids,syntax` exact 순서와
  일치해야 한다. key 순서를 임의 정렬해 이 gate를 우회하지 않는다.
- incident identity/order는
  `F1-t2,F1-t3,F2-t1,F3-t3,F3-t4,F4-t1,F5-t2,F5-t3,F6-t5,F7-t1,F7-t3,F8-t3`
  exact 12개이고 `incident_id == fault_id + "-t" + trial`이어야 한다.
- incident/fault/trial pattern, path/group ID `^[A-Z0-9_]+$`, axis별 path ID와 path별 group ID
  uniqueness, axis별 exact `source_fields`, positive path non-empty, contradiction array type를
  mutation test와 함께 강제한다.
- F1-t2/F1-t3의 `M_MEMORY_LIMIT.any_of`는
  `memory limit`, `memory cgroup limit`, `container memory limit` exact 3개다.
  두 F1 incident 모두 MCA 3 atoms/11 aliases이고 §6.2 전체 inventory가 exact 일치해야 한다.
- schema/static check 하나라도 실패하면 `ONTOLOGY_CHECK_PASS`를 출력하지 않고 non-zero로
  종료한다.

## 4. 공통 concept lexicon

표기법은 다음과 같다.

- `/`로 구분한 문자열은 각각 `kind=literal`, `polarity=affirmative`다.
- `absence:`는 그 부정어를 포함한 전체 phrase 자체가 장애 상태의 긍정 증거다.
- `pred:`는 위에서 고정한 token predicate ID다.
- literal과 token predicate는 normalization 후 token sequence에만 적용한다.

### 4.1 Component groups

| ID | exact `any_of` |
|---|---|
| `C_RECOMMENDATION` | `recommendationservice` / `recommendation service` |
| `C_CHECKOUT` | `checkoutservice` / `checkout service` |
| `C_PAYMENT` | `paymentservice` / `payment service` |
| `C_PRODUCTCATALOG` | `productcatalogservice` / `product catalog service` / `productcatalog service` |
| `C_WORKER01` | `worker01` / `worker 01` |
| `C_PROMETHEUS` | `prometheus` |
| `C_LOKI` | `loki` |
| `C_REDIS_CART` | `redis cart` / `rediscart` |
| `C_FRONTEND` | `frontend` / `front end` |

CM 축의 contradiction 배열은 전 incident에서 빈 배열이다. 다른 service를 영향 범위로
함께 적었다는 이유만으로 mention을 0으로 만들지 않는다. 따라서 CM은 `root_cause` 안의
canonical component token mention이며 target localization이나 문법적 culprit-role 판정이 아니다.

### 4.2 Fault-family groups

| ID | exact `any_of` |
|---|---|
| `FT_OOM` | `oomkilled` / `oom killed` |
| `FT_CRASHLOOP` | `crashloopbackoff` / `crash loop back off` / `crash loop backoff` |
| `FT_IMAGEPULL` | `imagepullbackoff` / `image pull back off` / `image pull backoff` |
| `FT_NODENOTREADY` | `nodenotready` / `node not ready` |
| `FT_PVCPENDING` | `pvcpending` / `pvc pending` |
| `FT_NETWORKPOLICY` | `networkpolicy` / `network policy` |
| `FT_CPUTHROTTLE` | `cputhrottle` / `cpu throttle` |
| `FT_SERVICEENDPOINT` | `serviceendpoint` / `service endpoint` |

FLM alias는 `results/ground_truth.csv:fault_name`의 case·separator 결합/분리만 허용한다.
mechanism·symptom·약어 확장으로 label acceptance set을 넓히지 않는다. 전 incident의 FLM
`contradictions`는 빈 배열이다. 다른 family label이 함께 있다는 사실만으로 mutually exclusive
root-cause assertion인지 판별할 finite grammar가 없기 때문이다. 그러므로 FLM은 classification
accuracy가 아니라 canonical fault-label mention일 뿐이다.

### 4.3 Mechanism groups

| ID | exact `any_of` |
|---|---|
| `M_MEMORY_LIMIT` | `memory limit` / `memory cgroup limit` / `container memory limit` |
| `M_LIMIT_TOO_LOW` | `memory limit too low` / `insufficient memory limit` / `pred:MEMORY_LIMIT_EXCEEDED_V1` |
| `M_OOM_TERMINATION` | `oom killer terminated` / `oom killed` / `oomkilled` / `killed by oom` / `exit code 137` |
| `M_BAD_ENTRYPOINT` | `corrupted entrypoint` / `corrupt entrypoint` / `invalid entrypoint` / `broken entrypoint` / `wrong entrypoint` / `misconfigured entrypoint` / `corrupted entry point` / `invalid entry point` / `broken startup command` / `invalid startup command` / `wrong container command` |
| `M_STARTUP_EXIT` | `crashes on startup` / `crashed on startup` / `startup failure` / `startup exit` / `exits on startup` / `exit code 1` |
| `M_REGISTRY_REFERENCE` | `registry url` / `registry hostname` / `image registry` / `image reference` |
| `M_REGISTRY_NAME_ERROR` | `registry url typo` / `registry hostname typo` / `misspelled registry` / `wrong registry url` / `invalid registry url` / `dns resolution failure` / `absence:no such host` |
| `M_IMAGE_DIGEST` | `image digest` / `sha256 digest` / `manifest digest` |
| `M_DIGEST_INVALID` | `invalid digest` / `digest mismatch` / `manifest verification failed` / `invalid sha256` |
| `M_KUBELET` | `kubelet` |
| `M_KUBELET_STOPPED` | `kubelet stopped` / `stopped kubelet` / `kubelet inactive` / `kubelet not running` / `kubelet unavailable` / `kubelet service stopped` |
| `M_PVC_REQUEST` | `pvc request` / `persistent volume claim request` / `requested volume` / `storage request` / `500gi` |
| `M_CAPACITY_INSUFFICIENT` | `insufficient storage` / `insufficient disk` / `exceeds available` / `exceeded available` / `too large` / `capacity cannot satisfy` / `500gi exceeds` |
| `M_LOCALPATH_PROVISIONER` | `local path provisioner` / `localpath provisioner` / `pvc provisioner` / `volume provisioner` |
| `M_PROVISIONER_UNAVAILABLE` | `provisioner unavailable` / `provisioner not available` / `provisioner not running` / `provisioner missing` / `provisioner deleted` / `deleted provisioner` / `provisioner pod not running` |
| `M_NETWORK_POLICY` | `networkpolicy` / `network policy` |
| `M_BLOCK_OR_DENY` | `blocks` / `blocked` / `blocking` / `denies` / `denied` / `deny rule` / `dropped by policy` |
| `M_CARTSERVICE` | `cartservice` / `cart service` |
| `M_REDIS_CART` | `redis cart` / `rediscart` |
| `M_PORT_6379` | `6379` / `redis port` |
| `M_CPU_LIMIT` | `cpu limit` / `cpu cgroup limit` / `container cpu limit` |
| `M_CPU_LIMIT_LOW` | `cpu limit too low` / `low cpu limit` / `insufficient cpu limit` / `10m` / `10 millicores` / `5m` / `5 millicores` |
| `M_CPU_THROTTLED` | `cpu throttled` / `cpu throttling` / `severely throttled` / `cpu starved` / `cfs throttled` |
| `M_SERVICE_SELECTOR` | `service selector` / `selector` |
| `M_LABEL_MISSING_MISMATCH` | `app label missing` / `missing app label` / `app label removed` / `removed app label` / `label mismatch` / `selector does not match` / `selector doesnt match` / `pods not selected` |
| `M_NO_ENDPOINTS` | `absence:no endpoints` / `absence:zero endpoints` / `endpoint list empty` / `endpoints list empty` / `absence:without endpoints` |

### 4.4 Contradiction groups

CM·FLM·MCA contradiction은 전 incident에서 빈 배열이다. 자유서술 안의 다른 component/fault/
mechanism phrase가 competing root-cause assertion인지 영향·배제·병기인지 판별할 승인된 finite
role grammar가 없기 때문이다. 단순 phrase presence로 정답 positive를 취소하지 않는다.

RA만 동일 item 안에서 완성된 **명시적 반대 action path**를 contradiction으로 허용한다. 예는
`decrease + memory limit`, `stop + kubelet`, `delete + local-path provisioner`다. action과 target이
같은 item에서 함께 match하지 않으면 contradiction이 아니다.

## 5. Incident별 positive path와 contradiction

모든 CM path는 `root_cause`, FLM path는 `identified_fault_type`, mechanism path는
`root_cause`, remediation path는 `remediation`만 읽는다. 아래 `A+B+C`는 한 path의
`all_of`, `P1 | P2`는 둘 중 하나의 완전한 path를 뜻한다.

### 5.1 F1 — memory limit OOM

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F1-t2` | recommendationservice, OOMKilled, 24Mi limit exceed/OOM | `C_RECOMMENDATION` | `FT_OOM` | `M_MEMORY_LIMIT + M_LIMIT_TOO_LOW + M_OOM_TERMINATION` | `[]` |
| `F1-t3` | checkoutservice, OOMKilled, 16Mi limit exceed/OOM | `C_CHECKOUT` | `FT_OOM` | `M_MEMORY_LIMIT + M_LIMIT_TOO_LOW + M_OOM_TERMINATION` | `[]` |

Remediation:

- `F1-t2`: `R_INCREASE + R_MEMORY_LIMIT + R_96MI`.
- `F1-t3`: `R_INCREASE + R_MEMORY_LIMIT + R_64MI`.
- contradiction: `R_DECREASE + R_MEMORY_LIMIT` path가 완성되면 RA=0.

### 5.2 F2 — corrupted entrypoint

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F2-t1` | paymentservice, CrashLoopBackOff, corrupted entrypoint startup exit | `C_PAYMENT` | `FT_CRASHLOOP` | `M_BAD_ENTRYPOINT + M_STARTUP_EXIT` | `[]` |

Remediation accepted paths:

- `R_FIX + R_ENTRYPOINT`
- `R_RESTORE + R_CORRECT_IMAGE`

Contradiction은 `R_BREAK + R_ENTRYPOINT`다.

### 5.3 F3 — image reference failures

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F3-t3` | productcatalogservice, ImagePullBackOff, registry hostname typo/DNS failure | `C_PRODUCTCATALOG` | `FT_IMAGEPULL` | `M_REGISTRY_REFERENCE + M_REGISTRY_NAME_ERROR` | `[]` |
| `F3-t4` | checkoutservice, ImagePullBackOff, invalid SHA256/digest mismatch | `C_CHECKOUT` | `FT_IMAGEPULL` | `M_IMAGE_DIGEST + M_DIGEST_INVALID` | `[]` |

Remediation:

- `F3-t3`: `R_FIX + R_REGISTRY_REFERENCE + R_VALID`.
- `F3-t4`: `(R_FIX + R_IMAGE_DIGEST + R_VALID) | (R_USE + R_VALID_TAG)`.
- contradiction: `R_KEEP + (R_INVALID_REGISTRY | R_INVALID_DIGEST)`.

### 5.4 F4 — stopped kubelet

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F4-t1` | worker01, NodeNotReady, kubelet stopped | `C_WORKER01` | `FT_NODENOTREADY` | `M_KUBELET + M_KUBELET_STOPPED` | `[]` |

Remediation은 `R_RESTART + R_KUBELET + R_UNCORDON` 하나만 허용한다. `R_STOP + R_KUBELET`이
완성되면 contradiction이다.

### 5.5 F5 — PVC provisioning

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F5-t2` | prometheus, PVCPending, 500Gi request exceeds capacity | `C_PROMETHEUS` | `FT_PVCPENDING` | `M_PVC_REQUEST + M_CAPACITY_INSUFFICIENT` | `[]` |
| `F5-t3` | loki, PVCPending, local-path provisioner unavailable/deleted | `C_LOKI` | `FT_PVCPENDING` | `M_LOCALPATH_PROVISIONER + M_PROVISIONER_UNAVAILABLE` | `[]` |

Remediation:

- `F5-t2`: `(R_REDUCE + R_PVC_SIZE) | (R_ADD + R_DISK_CAPACITY)`.
- `F5-t3`: `(R_RESTORE + R_LOCALPATH_PROVISIONER) | (R_RECONCILE + R_LOCALPATH_PROVISIONER)`.
- contradiction: t2의 `R_INCREASE + R_PVC_SIZE`, t3의 `R_DELETE + R_LOCALPATH_PROVISIONER`.

### 5.6 F6 — NetworkPolicy route denial

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F6-t5` | redis-cart, NetworkPolicy, cartservice→redis-cart:6379 ingress block | `C_REDIS_CART` | `FT_NETWORKPOLICY` | `M_NETWORK_POLICY + M_BLOCK_OR_DENY + M_CARTSERVICE + M_REDIS_CART + M_PORT_6379` | `[]` |

Remediation은 `R_ADD_ALLOW + R_NETWORK_POLICY + R_CARTSERVICE + R_REDIS_CART + R_PORT_6379`다.
`R_DENY + R_NETWORK_POLICY`가 완성되면 contradiction이다.

### 5.7 F7 — CPU limit throttling

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F7-t1` | frontend, CPUThrottle, 10m CPU limit | `C_FRONTEND` | `FT_CPUTHROTTLE` | `M_CPU_LIMIT + M_CPU_LIMIT_LOW + M_CPU_THROTTLED` | `[]` |
| `F7-t3` | productcatalogservice, CPUThrottle, 5m CPU limit | `C_PRODUCTCATALOG` | `FT_CPUTHROTTLE` | `M_CPU_LIMIT + M_CPU_LIMIT_LOW + M_CPU_THROTTLED` | `[]` |

Remediation:

- `F7-t1`: `(R_INCREASE + R_CPU_LIMIT + R_200M) | (R_REMOVE + R_CPU_LIMIT)`.
- `F7-t3`: `R_INCREASE + R_CPU_LIMIT + R_100M`.
- contradiction: `R_DECREASE + R_CPU_LIMIT`.

### 5.8 F8 — missing pod label/service endpoints

| Incident | Canonical | CM group | FLM group | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F8-t3` | paymentservice, ServiceEndpoint, removed app label→unselected pods→empty endpoints | `C_PAYMENT` | `FT_SERVICEENDPOINT` | `M_SERVICE_SELECTOR + M_LABEL_MISSING_MISMATCH + M_NO_ENDPOINTS` | `[]` |

Remediation은 `R_RESTORE + R_APP_LABEL + R_PAYMENT_PODS`다. `R_REMOVE + R_APP_LABEL`이
완성되면 contradiction이다. 더 넓은 “selector를 바꾼다”는 해결책은 ground-truth의 exact
recovery action이 아니므로 primary RA alias에 추가하지 않는다.

## 6. Remediation concept lexicon

| ID | exact `any_of` |
|---|---|
| `R_INCREASE` | `increase` / `raise` / `set higher` |
| `R_DECREASE` | `decrease` / `reduce the limit` / `lower the limit` |
| `R_MEMORY_LIMIT` | `memory limit` / `container memory limit` |
| `R_CPU_LIMIT` | `cpu limit` / `container cpu limit` |
| `R_96MI` | `96mi` / `96 mib` |
| `R_64MI` | `64mi` / `64 mib` |
| `R_200M` | `200m` / `200 millicores` |
| `R_100M` | `100m` / `100 millicores` |
| `R_FIX` | `fix` / `correct` / `repair` / `update` |
| `R_ENTRYPOINT` | `entrypoint` / `entry point` / `startup command` / `container command` |
| `R_RESTORE` | `restore` / `revert` |
| `R_CORRECT_IMAGE` | `correct container image` / `working container image` / `valid container image` / `previous image` |
| `R_REGISTRY_REFERENCE` | `registry url` / `registry hostname` / `image registry` / `image reference` |
| `R_VALID` | `valid` / `correct` / `working` |
| `R_IMAGE_DIGEST` | `image digest` / `sha256 digest` / `manifest digest` |
| `R_USE` | `use` / `switch to` |
| `R_VALID_TAG` | `valid tag` / `working tag` / `known good tag` / `tag based reference` |
| `R_RESTART` | `restart` / `start` |
| `R_KUBELET` | `kubelet` / `kubelet service` |
| `R_UNCORDON` | `uncordon` / `make schedulable` |
| `R_REDUCE` | `reduce` / `decrease` / `request less` |
| `R_PVC_SIZE` | `pvc size` / `pvc request` / `storage request` / `volume size` |
| `R_ADD` | `add` / `expand` / `increase` / `provision more` |
| `R_DISK_CAPACITY` | `disk capacity` / `storage capacity` / `node disk` / `available storage` |
| `R_RECONCILE` | `reconcile` / `flux reconcile` / `fluxcd reconcile` |
| `R_LOCALPATH_PROVISIONER` | `local path provisioner` / `localpath provisioner` / `volume provisioner` |
| `R_DELETE` | `delete` / `remove` |
| `R_ADD_ALLOW` | `add allow` / `allow ingress` / `permit ingress` / `create allow rule` / `update allow rule` |
| `R_NETWORK_POLICY` | `networkpolicy` / `network policy` / `policy rule` |
| `R_CARTSERVICE` | `cartservice` / `cart service` |
| `R_REDIS_CART` | `redis cart` / `rediscart` |
| `R_PORT_6379` | `6379` / `redis port` |
| `R_DENY` | `deny` / `block` / `drop` |
| `R_REMOVE` | `remove` / `unset` / `delete` |
| `R_APP_LABEL` | `app label` / `application label` |
| `R_PAYMENT_PODS` | `paymentservice pods` / `payment service pods` / `paymentservice pod` / `payment service pod` |
| `R_BREAK` | `break` / `corrupt` / `invalidate` |
| `R_KEEP` | `keep` / `retain` / `leave unchanged` |
| `R_INVALID_REGISTRY` | `invalid registry` / `wrong registry url` |
| `R_INVALID_DIGEST` | `invalid digest` / `wrong digest` |
| `R_STOP` | `stop` / `disable` |

`F5-t3`의 두 복구 경로는 ground truth의 “Restore ... via FluxCD reconcile”에서 직접 분리한
표현이다. generic `redeploy`와 값 없는 `higher/sufficient limit`은 acceptance set을 넓히므로
제거했다. 표 안의 괄호·OR는 모두 별도 positive path로 전개해 실행 중 동적 논리를 만들지
않는다. **각 remediation positive path의 모든 group은 동일한 `remediation[]` item 하나 안에서
완성돼야 한다.** 서로 다른 item 사이의 group cross-join은 금지한다.

### 6.1 Alias provenance 계약

- CM matcher의 `source_ref`는 `results/ground_truth.csv:<incident>:target_service`다.
- FLM matcher의 `source_ref`는 `results/ground_truth.csv:<incident>:fault_name`다. 결합/분리 외
  의미 확장은 없다.
- MCA matcher는 `expected_root_cause`, RA matcher는 `expected_recovery_action`의 incident와
  column을 기록한다. 다른 trial에서 가져온 contradiction은 그 exact row/column을 기록한다.
- 공개 taxonomy를 직접 근거로 쓴 matcher만 official URL과 exact taxonomy label을 기록한다.
- 하나의 matcher에 provenance가 없거나 candidate 관찰을 source로 적으면 ontology validation이
  실패한다.

### 6.2 사전 고정 positive matcher 난이도 표

alias 수는 literal과 token predicate를 각각 1개로 센다. RA의 atom 범위는 accepted path별
필수 group 수의 min~max이고 alias는 해당 incident가 참조하는 positive group의 unique matcher
합계다. contradiction alias는 포함하지 않는다.

| Incident | CM atoms/aliases | FLM atoms/aliases | MCA atoms/aliases | RA paths, atoms/aliases |
|---|---:|---:|---:|---:|
| F1-t2 | 1/2 | 1/2 | 3/11 | 1, 3/7 |
| F1-t3 | 1/2 | 1/2 | 3/11 | 1, 3/7 |
| F2-t1 | 1/2 | 1/3 | 2/17 | 2, 2/14 |
| F3-t3 | 1/3 | 1/3 | 2/11 | 1, 3/11 |
| F3-t4 | 1/2 | 1/3 | 2/7 | 2, 2~3/16 |
| F4-t1 | 1/2 | 1/2 | 2/7 | 1, 3/6 |
| F5-t2 | 1/1 | 1/2 | 2/12 | 2, 2/15 |
| F5-t3 | 1/1 | 1/2 | 2/11 | 2, 2/8 |
| F6-t5 | 1/2 | 1/2 | 5/15 | 1, 5/14 |
| F7-t1 | 1/2 | 1/2 | 3/15 | 2, 2~3/10 |
| F7-t3 | 1/3 | 1/2 | 3/15 | 1, 3/7 |
| F8-t3 | 1/2 | 1/2 | 3/15 | 1, 3/8 |

구현 validator가 ontology JSON에서 이 표를 재계산해 exact 일치를 synthetic test로 확인한다.
fault별 atom 수 차이는 ground-truth 복잡성으로 공개하며 결과를 본 뒤 균등화하지 않는다.

## 7. 정규화·부정·field isolation 알고리즘

처리 순서는 고정한다.

1. regular file 한 개의 candidate JSON byte length는 최대 24,576이다. 초과 시 전체 run을
   `INPUT_LIMIT_EXCEEDED`로 invalid 처리하며 partial parse하지 않는다.
2. JSON을 UTF-8 strict로 decode한다. literal U+FFFD replacement character가 어느 string의 어느
   위치에든 있으면 invalid다. duplicate key를 허용하지 않고 schema의 세 key 외에는 거부한다.
3. `identified_fault_type`는 최대 256 UTF-8 bytes·64 tokens, `root_cause`는 최대
   8,192 bytes·1,024 tokens다. `remediation`은 1~16개 string, item당 최대
   2,048 bytes·256 tokens, 전체 최대 8,192 bytes이며 **모든 item의 normalization 후 token 수
   합계가 최대 1,024**여야 한다. `identified_fault_type`, `root_cause`, 각 remediation item은
   raw empty, whitespace-only 또는 normalization 후 0 tokens이면 invalid다.
4. upstream generator prompt인 `experiments/v2_3/live_caller.py:27-32`에는 출력 언어 계약이
   없다. 본 matcher는 **영어 ASCII lexical subset만** 지원한다. normalization 후 ASCII 밖의
   alphanumeric token이 하나라도 있으면 언어를 추정하거나 번역하지 않고 전체 run을
   `LANGUAGE_UNSUPPORTED`로 invalid 처리한다. 이 gate는 English임을 증명하지 않으며 지원 범위를
   기계적으로 제한할 뿐이다.
5. 각 문자열에 Unicode NFKC 후 `casefold()`를 적용한다. 원문의 `. ; : ! ? CR LF`를 clause
   boundary로 먼저 분리한다.
6. 각 clause에서 maximal Unicode alphanumeric run만 token으로 남긴다. 나머지는 separator다.
   `redis-cart`와 `redis cart`, `local-path`와 `local path`는 같은 token sequence가 된다.
7. literal은 완전한 token sequence로만 match한다. substring과 raw regex는 금지한다.
   `MEMORY_LIMIT_EXCEEDED_V1`만 §3의 유한 token sequence로 평가한다.
8. negator token은 `no, not, never, without, neither, nor, isnt, wasnt, arent, werent,
   cannot, cant, didnt, doesnt, wont`다. postposed marker는 `ruled out`, `not the cause`,
   `not a cause`, `not the root cause`, `not the issue`, `not the fault`다.
9. negation은 아래 유한 grammar만 지원한다. `C`는 한 ontology concept span, `F`는
   `a|an|the|any|evidence|sign|signs|indication|indications|of|for`, `K`는 `and|or|nor`다.

   ```text
   PRE_DIRECT := NEG F{0,3} C
   PRE_COORD  := NEG F{0,3} C (K F{0,3} C)+
   PRE_RULE   := (rule out | ruled out) F{0,3} C
   POST_RULE  := C (is|was|are|were|has been|have been){0,1} ruled out
   POST_CAUSE := C (is|was|are|were) not (the|a|an){0,1}
                 (cause|root cause|issue|fault)
   NOT_ONLY   := not only C1 but C2
   ```

10. `NOT_ONLY`를 다른 negation grammar보다 먼저 exact parse한다. `not only` 두 token과 연결자
    `but`을 exception span으로 소비하고 C1·C2는 둘 다 affirmative unsuppressed match로 남긴다.
    예외 span을 소비한 뒤 같은 clause를 다시 scan하며, **남아 있는 unresolved negation marker
    또는 그 marker가 시작한 ontology-concept scope candidate가 있을 때만**
    `UNSUPPORTED_NEGATION`으로 fail-close한다. 이미 소비된 `not only` 때문에 clause의 다른
    ordinary concept를 미분류로 만들지 않는다.
11. `PRE_COORD`는 첫 NEG부터 같은 clause의 마지막 연속 conjunct까지만 전파한다. comma,
    contrast token `but|however|instead|rather`, clause boundary 또는 grammar 밖 token에서 끝난다.
    단, `NOT_ONLY`가 먼저 소비한 `but`은 contrast 종료점으로 재사용하지 않는다.
12. `polarity=absence_assertion`의 exact phrases `no endpoints`, `zero endpoints`,
    `without endpoints`는 자신 내부의 absence token을 상태의 긍정 증거로 먼저 소비한다.
    `no evidence of no endpoints`처럼 바깥 negator가 있으면 `PRE_DIRECT`가 전체 occurrence를
    suppress한다.
13. exception/absence span을 먼저 소비한 뒤, 남은 negation marker와 그 scope candidate를
    9~12의 grammar로 분류한다. 남은 marker/scope candidate가 suppressed 또는 명시적으로 종료된
    grammar로 분류되지 않으면 해석을 추정하지 않고 전체 run을 `UNSUPPORTED_NEGATION`으로
    invalid 처리한다. marker가 전혀 남지 않은 clause의 ordinary concept는 fail-close 대상이
    아니다.
14. ontology JSON Schema는 §3의 negation token·phrase·filler·coordinator·contrast·exception·
    grammar ID 배열을 `const`로 강제한다. static validator도 이 일곱 상수의 값과 순서가 plan과
    byte-for-byte 같은지 확인하고 하나라도 추가·누락·재정렬되면 실패한다.
15. positive와 contradiction에 동일한 span 분류를 적용한다. positive path는 모든 group이
    unsuppressed match를 가져야 한다. contradiction group 하나라도 unsuppressed match면 해당
    axis를 0으로 강제하고 group ID와 token index만 trace에 남긴다.
16. remediation은 item별로 독립 처리한다. alias와 accepted path 모두 item 경계를 넘지 못하며,
    한 item 안에서 한 positive path의 모든 group을 충족해야 RA=1이다.

빈/whitespace/0-token 문자열, U+FFFD, `null`, 예상 밖 key, duplicate key, non-list remediation,
remediation cumulative 1,024-token 초과는 오답으로 대체하지 않고 schema gate 실패로 전체 run을
`INVALID` 처리한다.

## 8. Synthetic-only 구현 검증

V2.4-D scorer가 실제 36개 candidate를 decode하기 전에 다음 test가 모두 통과하고 코드가
commit돼야 한다. fixture는 이 계획의 alias를 조합한 새 문장만 사용하며 candidate 문자열을
복사하지 않는다. 기존 generic machine-only parse는 §9.3에 별도 공개한다.

1. NFKC/casefold, hyphen·underscore·slash separator, token boundary.
2. `redis-cart`↔`redis cart`, `local-path`↔`local path` 동치.
3. substring 거부: `frontendish`, `notworker01x`, `redis carpeting`은 component 불일치.
4. field isolation: fault alias가 remediation에만 있어도 FLM=0; mechanism alias가 fault field에만
   있어도 MCA=0; recovery alias가 root cause에만 있어도 RA=0.
5. positive conjunction: 한 group이 빠지면 path=0.
6. alternative remediation path: 완전한 대안 하나는 pass, 서로 다른 불완전 대안의 잘못된
   cross-join은 fail.
7. RA contradiction precedence: 동일 item에 positive recovery와 affirmative 반대 action path가
   함께 완성되면 RA=0.
8. `PRE_DIRECT`, `PRE_COORD`, `PRE_RULE`, `POST_RULE`, `POST_CAUSE` 각각의 positive matcher와
   RA contradiction matcher 대칭 test.
9. 실제 ontology concept 두 개를 쓰는 `no cpu throttling or memory limit`에서
   `M_CPU_THROTTLED`와 `M_MEMORY_LIMIT` 두 positive span이 모두 suppressed임을 assertion하고,
   contrast/clause에서 scope가 끝나는 test.
10. absence assertion: `no endpoints`와 `endpoints list empty`는 `M_NO_ENDPOINTS` match.
11. negation exception positive test: `not only cpu throttling but memory limit`에서
    `M_CPU_THROTTLED`와 `M_MEMORY_LIMIT`가 둘 다 unsuppressed이고 `not only` marker가 consumed이며
    unresolved marker/scope candidate가 0임을 assertion. 같은 clause 뒤에 별도 미지원 negation을
    붙인 negative fixture는 그 **남은 marker/scope만** `UNSUPPORTED_NEGATION`으로 만든다.
12. clause scope: `not image pull; digest mismatch`에서 앞 negation이 뒤 clause에 전파되지 않음.
13. remediation path는 단일 item 안에서 완성되면 pass, 두 item cross-join이면 fail.
14. FLM orthographic variant만 pass하고 mechanism/symptom alias 및 다른 family 단순 병기는
    FLM contradiction을 만들지 않음.
15. schema와 static validator가 negation의 15 tokens·7 phrases·11 fillers·3 coordinators·4
    contrasts·1 exception·6 grammar IDs를 exact 순서로 강제하고, 추가/누락/재정렬을 거부함.
16. grammar 밖 negation, non-ASCII alphanumeric token, byte/token/list 상한 초과 fail-close.
17. malformed UTF-8, duplicate JSON key, missing/extra key, 잘못된 type, 빈 list fail-close.
18. incident/condition duplicate, 누락, unexpected incident, 36행 초과·미달 fail-close.
19. CSV/ground-truth/projection/raw-tree/ontology/scorer/plan hash mismatch fail-close.
20. 통계 known-answer:
    `b=5,c=0 → one-sided p=0.03125`, `b=4,c=0 → p=0.0625`,
    `b=0,c=5 → p=1`, `b=c=0 → p=1`.
21. fixed seed 20260831·50,000 paired bootstrap과 canonical float serialization byte equality.
22. 입력 순서 shuffle 뒤 canonical sort 결과 byte equality.
23. ontology mutation matrix: duplicate key at every object class; ontology version change;
    normalization value/order change; token-predicate add/remove/reorder; negation token/phrase/syntax
    add/remove/reorder; arbitrary incident/fault/trial; invalid/duplicate path/group ID를 모두 거부함.
24. ontology exact inventory: F1 `M_MEMORY_LIMIT` 3 aliases, F1 MCA 3 atoms/11 aliases, §6.2의
    12-row atom/alias count를 builder와 loader가 독립 재계산해 exact 일치함.
25. finite grammar matrix: `rule out the network policy`, `ruled out the network policy`,
    `network policy is/was/are/were/has been/have been ruled out`,
    `neither cpu throttling nor memory limit`, POST_CAUSE article variants를 승인된 suppression으로,
    `memory limit is not generally relevant`를 unresolved INVALID로 assertion함.
26. NOT_ONLY/coordination trace matrix: C1/C2 span ID, consumed marker span, scope terminator,
    unresolved marker count를 exact assertion하고 positive matcher와 same-item RA contradiction에
    같은 classifier가 쓰이는지 확인함.
27. absence test는 helper literal이 아니라 ontology의 actual
    `polarity=absence_assertion` matcher를 load해 `no/zero/without endpoints`, outer negation,
    ordinary affirmative phrase를 검증함.
28. candidate schema mutation: empty·whitespace·0-token fault/root/remediation, literal U+FFFD의
    field/item별 위치, remediation item/total byte·token 경계 1,023/1,024/1,025를 검증함.
29. identity/hash mutation matrix: duplicate/missing/unexpected incident/condition, fixed CSV/raw
    source digest, 새 commitment file/envelope digest/provenance, GT full/projection, ontology, builder,
    init, runner, commitment tool, scorer, analyzer, test, plan, semantic review, I0 safety-review
    receipt, deviation provenance, full implementation review, approval, interpreter hash를 각각
    단독 변조해 candidate decode 전에 거부함. old envelope digest를 새 commitment 승인값으로
    주입해도 반드시 거부함.
30. git freeze matrix: HEAD≠A, A^≠B, B^≠I1, I1^≠I0, I0→I1 allowlist 외 변경,
    I1→B extra/missing/modified file, B→A extra/missing/modified file,
    approved_bundle/execution_commit/implementation_candidate/blob OID/file hash mismatch를 모두
    candidate-source open spy count 0에서 거부함. detached I0 safety review 전 real source open
    spy count도 0이며, reviewed I0 tool blob과 commitment provenance tool blob 불일치도 거부함.
31. two-run publication matrix: run1 success/run2 failure, canonical mismatch, manifest mismatch,
    atomic rename failure에서 public final/replay/result/summary가 모두 absent이고 INVALID receipt만
    존재함; two-run complete+equal에서만 release root 하나가 atomic publish됨.
32. commitment path attacks: source/ancestor/final-entry symlink, path traversal, hard link,
    non-regular file, lstat→open swap, hash→parse mutation, pre/post stat drift, raw root의 nested dir·
    non-JSON·extra JSON·socket/device를 모두 거부함.
33. executable redaction self-test: synthetic sentinel을 success/error argv·stdout·stderr path에
    통과시켜 egress 0을 실제 assert하고, self-test command/time/commit/interpreter/tool/fixture/
    stdout/stderr digest/exit status가 provenance와 exact 일치함. 상수 PASS 주입은 실패함.
34. statistics known bytes: `b=c=0 → q/CI=NA,p=1`; `b=5,c=0`의 Clopper-Pearson
    `[0.4781762498950185,1]`; `b=0,c=5`의 `[0,0.5218237501049815]`. Synthetic paired vector
    `[1,1,1,1,1,0,0,0,-1,-1,0,0]`, seed 20260831의 50,000 replicate를 `.17g` newline으로
    serialize한 744,080 bytes SHA-256
    `aa089664652480d5565da1853d51635dd53310475585e3cccbc8516bb7aae4ca`, percentile
    `[-0.16666666666666666,0.66666666666666663]`와 비교함. shuffled-input 전체 canonical output도
    별도 frozen expected SHA-256와 비교함.
35. reviewed isolated bootstrap으로 exact `<python> -I tests/test_v2_4_deterministic.py`와
    `<python> -I experiments/v2_4_deterministic/run.py --self-test`가 detached clean checkout에서
    repo import와 모든 synthetic/static test를 성공함.
36. machine-parse deviation schema는 §9.3의 status와 네 evidence를 모두 요구하고,
    `process_access_zero=true` 또는 evidence 누락/모순을 approval-before-open에서 거부함.
37. no-text-egress spy는 machine-only regression parse 중 candidate value가 stdout/stderr/log/
    exception/agent fixture로 전달되지 않았고 V2.4-D scorer/ontology call count 및 그 이후
    observed-output-derived diff count가 각각 0임을 검증함.

실제 input을 이용한 test fixture 생성, snapshot/golden-output test, observed output에서 alias를
추출하는 coverage test는 금지한다.

## 9. 입력·hash hard gates

### 9.1 구현 전 gate

review는 semantic, commitment-safety, full implementation의 서로 다른 세 gate로 분리한다.

1. semantic review의 단일 정본은 `docs/plans/review_v2_4_deterministic.md`다. 최초 FAIL부터
   Revision 5 수정 요구까지의 기존 append 기록을 보존하고 Revision 6 재검토도 같은 파일에
   append할 예정이다. 정본 identity는 그 cumulative content와 code-only candidate commit `I0`
   tree의 exact git blob OID/path다.
   review 파일 안에는 자신의 최종 filesystem SHA-256를 기록하지 않는다. 최종 review file
   SHA-256는 `I0`가 고정된 뒤 외부에서 계산해 safety/full implementation review 문서, approval,
   사용자 보고에 기록한다. 별도 r2/r3 review 파일은 생성하거나 참조하지 않는다.
2. semantic Revision 6 PASS 뒤 candidate source를 열지 않고 implementation code와 synthetic
   fixtures만 완성해 code-only candidate commit `I0`를 만든다. 기존 FAIL candidate
   `e86e26b4eb00aca899f42eab008132c0664a5cfc`와 그때의 commitment는 역사로 보존한다. `I0` safety
   review scope는 아래 여덟 파일이며 real commitment는 scope/target에서 제외한다.

```text
experiments/v2_4_deterministic/ontology_v1.json
experiments/v2_4_deterministic/__init__.py
experiments/v2_4_deterministic/build_ontology.py
experiments/v2_4_deterministic/commit_inputs.py
experiments/v2_4_deterministic/scorer.py
experiments/v2_4_deterministic/analyze.py
experiments/v2_4_deterministic/run.py
tests/test_v2_4_deterministic.py
```

3. fresh commitment-safety reviewer는 candidate source path를 mount/전달하지 않은 detached clean
   `I0`에서 `commit_inputs.py`, reviewed bootstrap, no-follow/TOCTOU/path-attack, executable
   redaction test를 synthetic fixture로만 검토한다. real CSV/raw open count는 0이어야 한다. reviewer는
   reviewer/session identity, review UTC, exact `I0`, 위 여덟 파일의 blob OID·blob/filesystem
   SHA-256, interpreter identity, 실행 명령·exit status·stdout/stderr digest, fixture/sentinel digest와
   PASS 판정을 content-addressed external safety receipt로 먼저 봉인한다. FAIL 또는 receipt 부재 시
   real commitment 생성은 금지한다.
4. safety PASS receipt가 가리키는 exact `I0:experiments/v2_4_deterministic/commit_inputs.py`만 사용해
   human/agent text egress 없이 real hash-only commitment를 재생성한다. 새 commitment provenance는
   exact I0 tool blob과 external safety receipt digest를 포함한다. 동시에 §9.3 historical deviation
   evidence를 `docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json`에 봉인한다.
   그 두 경로만 변경한 full candidate commit `I1`을 만든다.

```text
I1^ == I0
git diff --name-status I0..I1
M  docs/plans/input_commitment_v2_4_deterministic.json
A  docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json
```

위 출력은 exact 두 줄이어야 한다. ontology/scorer/analyzer/runner/builder/commit tool/tests를 포함한
실행 code와 plan/semantic review의 `I0`·`I1` blob OID가 모두 같아야 한다. commitment 또는 deviation
provenance 외 변경, reviewed I0 tool과 provenance tool identity 불일치, safety review보다 이른 real
source open은 INVALID다.

full implementation candidate `I1`은 다음 target 전부를 포함한다. cumulative implementation review
파일에는 기존 FAIL 내용만 있고 Revision 6 full re-review PASS는 아직 없어야 하며 approval 문서는
없어야 한다.

```text
docs/plans/experiment_plan_v2_4_deterministic.md
docs/plans/review_v2_4_deterministic.md
docs/plans/input_commitment_v2_4_deterministic.json
docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json
experiments/v2_4_deterministic/ontology_v1.json
experiments/v2_4_deterministic/__init__.py
experiments/v2_4_deterministic/build_ontology.py
experiments/v2_4_deterministic/commit_inputs.py
experiments/v2_4_deterministic/scorer.py
experiments/v2_4_deterministic/analyze.py
experiments/v2_4_deterministic/run.py
tests/test_v2_4_deterministic.py
```

5. 또 다른 fresh full implementation reviewer는 detached clean checkout의 exact `I1`에서 실제
   ontology/code/tests/new commitment/deviation provenance와 prior I0 safety receipt를 검토한다.
   review 문서에는 exact I0/I1, detached/clean 증거, 위 I1 target **전부**의
   `I1:<path>` git blob OID·blob SHA-256·filesystem SHA-256, synthetic/static test 명령·exit status,
   I0 safety receipt hash와 `I0..I1` exact diff를 기록한다. approval provenance도 이 전체 target
   hash map을 그대로 포함해야 한다. 기존 FAIL을 보존한 같은 implementation review 문서에
   Revision 6 full re-review를 append하고, 그 문서 하나만 수정한 commit `B`를 만든다.

```text
B^ == I1
git diff --name-status I1..B
M  docs/plans/review_v2_4_deterministic_implementation.md
```

위 출력이 exact 한 줄이 아니거나, implementation review에 외부 계산·기록된 semantic review
filesystem SHA-256 및 target hash가 `I1`과 `B` tree에서 모두 같지 않으면 INVALID다. 사용자에게
exact `B`와 외부 계산된 review hash를 제시해 명시 승인을 받은 뒤 승인 문구·시각·`B`·semantic
review blob OID·filesystem SHA-256를 `docs/plans/approval_v2_4_deterministic.md`에 기록하고 그
문서 하나만 추가한 commit `A`를 만든다.

```text
A^ == B
git diff --name-status B..A
A  docs/plans/approval_v2_4_deterministic.md
```

이 출력도 exact 한 줄이어야 한다. `I0→I1`, `I1→B`, `B→A`의 parent/diff/hash 조건 하나라도 다르면
INVALID다. 실행 checkout은 반드시 exact `A`이고 approval 문서가 가리키는 approved bundle은
`B`여야 한다. self-referential `A` hash를 approval 문서 안에 쓰지 않으며 실행 manifest가
실제 `A`를 기록한다. candidate 본문을 읽는 명령은 이 모든 검증을 통과한 `A` 이후에만 가능하다.

현재 repository의 old `docs/plans/input_commitment_v2_4_deterministic.json`과 그 내부
`commitment_sha256=590e8e006d5adc449bb8e0bdd12b0beaaf7bc8197015dd65a7131525cf90ca64`는
status `DEPRECATED_MACHINE_HASH_ONLY_COMMITMENT`로만 보존한다. 이는 fresh safety review 전에
unreviewed tool로 생성됐으므로 confirmatory commitment, approval target, runtime envelope gate로
사용하지 않는다. 위 값과 old envelope bytes 자체를 새 commitment의 expected digest로 요구하는
모든 계약을 폐기한다.

단, old artifact에 이미 opaque하게 기록된 fixed Primary03 CSV SHA-256
`5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b`와 정렬된 117개
`relative_path,size,sha256` source-identity map은 **source drift 부재만** 검증하는 legacy reference로
사용한다. I0의 reviewed tool이 생성한 새 commitment의 CSV digest와 117개 entry digest가 이 map과
각각 exact 일치해야 하며 하나라도 다르면 INVALID다. 이 비교는 old provenance/envelope 안전성을
승인하지 않는다. provenance가 바뀌므로 새 canonical self-excluding commitment envelope digest는
old 값과 달라도 되며, 생성 후 `I1` blob/filesystem hash와 내부 recomputation 값을 fresh full
implementation review `B` 및 approval `A`에서 새 값으로 freeze한다. plan에는 그 새 값을 사전
하드코딩하지 않는다.

`input_commitment_v2_4_deterministic.json`은 이 예외적으로 허용된 **opaque hash-only** 단계에서
만든다. 파일 본문을 decode, parse, search, preview하거나 stdout에 쓰지 않고 SHA-256
stream으로만 읽어 117 raw relative paths·sizes·digests와 CSV digest를 canonical JSON에
봉인한다.

`commit_inputs.py` 자체도 source root와 각 ancestor를 component별 `lstat`해 symlink를 거부하고,
raw root 바로 아래에 정확히 117개의 `.json` regular file만 허용한다. nested directory,
non-JSON regular file, 추가 JSON, symlink, socket, FIFO, device, hard-link(`st_nlink != 1`)를 모두
unexpected entry로 거부한다. 각 entry는 `os.open(O_RDONLY|O_NOFOLLOW)`→`fstat` regular/
device/inode/size 확인→동일 fd pre-hash→seek→opaque stream→seek→post-hash→post-fstat→path
`lstat` 순으로 검증한다. 두 hash, 전후 stat, path device/inode가 하나라도 다르면 TOCTOU로
실패한다. CSV도 같은 no-follow/fd/pre-post-rehash 계약을 적용한다.

도구는 real commitment 전에 executable `--self-test-redaction`을 별도 synthetic fixture에서
실행한다. sentinel을 success/error argv·stdout·stderr·exception 후보에 주입하고 실제 captured
stdout/stderr/receipt 어디에도 sentinel bytes가 없음을 assertion해야 한다. 코드 상수
`redaction_test=PASS`는 증거로 인정하지 않는다. provenance는 exact tool git blob OID/SHA-256,
interpreter path/version/binary SHA-256, cwd, canonical argv array, allowlisted environment, source-root
device/inode, start/end UTC, exit status, synthetic fixture/sentinel digest, captured stdout/stderr
SHA-256, sentinel match count 0, raw count 117, CSV SHA-256, entry manifest SHA-256,
external I0 safety receipt SHA-256, reviewed `I0` commit, source-drift comparison result,
`commitment_sha256`, operator attestation을 required로 기록한다. stdout/stderr에는 count와
commitment hash만 허용한다. 이는 hash-only process의 감사 provenance이지 cryptographic proof나
process access 0의 증거라고 주장하지 않는다. commitment 자체도 candidate scoring 전에
`I1` commit·fresh full implementation review·승인한다.

Ground truth commitment는 다음으로 고정한다.

```text
results/ground_truth.csv full SHA-256
d00115766dbfaa844b5325ff60aac8170b83689ccf2f2d2cd427faad9f8115c6

selected 12-row canonical projection SHA-256
be456f903354d581ae66c8f7051ea271a9add2cb7b6a58e28d1d768aaee57b1b
```

projection은 선택 12행을 numeric `fault_id`, numeric `trial`로 정렬하고
`fault_id,trial,fault_name,target_service,expected_root_cause,expected_recovery_action`만 남긴
object list를 Python `json.dumps(ensure_ascii=False, sort_keys=True, separators=(",", ":"))`로
UTF-8 encode한 3,318 bytes다. 두 digest와 projection algorithm은 commit `I0`부터 포함하고
`I0→I1→B→A`에서 변하지 않아야 한다.

### 9.2 실행 preflight gate

- `run.py`는 candidate source path를 `open/stat/glob`하기 전에 repository gate를 먼저 실행한다.
  CLI의 `--execution-commit A`, `--approved-bundle B`, `--implementation-candidate I1`,
  `--code-candidate I0`를 required로 받고 current git `HEAD == A`, `A^ == B`, `B^ == I1`,
  `I1^ == I0`를 exact 비교한다.
- `git diff --name-status I0..I1`은 §9.1 commitment modification과 deviation provenance addition
  두 줄, `git diff --name-status I1..B`는 cumulative implementation review modification 한 줄,
  `git diff --name-status B..A`는 approval addition 한 줄이어야 한다. approval의
  `approved_bundle == B`, external execution authorization의 `execution_commit == A`,
  implementation review의 `code_candidate == I0`, `implementation_candidate == I1`이어야 한다.
- implementation review와 approval provenance에 기록된 semantic review blob OID/filesystem
  SHA-256, I0 external safety receipt SHA-256, implementation review blob OID/SHA-256, §9.1의
  I0 safety-scope와 I1 전체 target blob OID·blob/filesystem SHA-256를 `git cat-file`과 checkout
  bytes에서 재계산한다. `run.py`, `build_ontology.py`, `commit_inputs.py`, `__init__.py`, 새
  commitment와 deviation provenance도 반드시 포함한다. I0→I1에서 code blob은 exact 동일해야 한다.
- approval 문서 자체의 hash는 self-reference를 피하기 위해 문서 내부 값과 비교하지 않는다.
  `A:path` blob OID·filesystem SHA-256를 external execution authorization과 preflight manifest에
  기록·비교한다. implementation review/approval/execution authorization 중 target map이나
  I0/I1/B/A identity 하나라도 다르면 INVALID다.
- fixed Primary03 CSV SHA-256는
  `5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b`와 exact 비교한다.
  새 commitment의 file SHA-256와 내부 canonical self-excluding `commitment_sha256`는 I1/B/A에
  freeze된 **새 값**으로 recompute하고, §9.1 exact provenance, 117-entry manifest digest와 각
  entry hash를 approval target map 및 preflight 값과 비교한다. CSV와 117개
  `relative_path,size,sha256`는 deprecated artifact의 legacy source-identity map에도 exact 일치해야
  한다. old `590e8e...` envelope digest를 새 expected 값으로 비교하면 구현 오류이며 INVALID다.
- candidate decode 전에 plan, cumulative semantic review, implementation review, approval,
  I0 safety receipt, ontology, init, builder, runner, commitment tool, scorer, analyzer, tests, new input
  commitment, deviation provenance, ground-truth full/projection, interpreter의 blob/filesystem/manifest
  hash map을 완성하고 검증한다.
  이 단계까지 candidate-source open spy count는 0이어야 한다. gate mismatch는 candidate를 열지
  않고 machine-readable INVALID receipt만 원자적으로 남긴다.
- source root와 모든 ancestor/entry는 `lstat`으로 검사해 symlink를 거부한다. relative path의
  absolute component, `..`, NUL을 거부한다.
- 결과 CSV SHA-256이 §1.3 값과 일치해야 한다.
- raw directory는 root 바로 아래 117 regular `.json` files 외의 **모든 entry**를 거부한다.
  상대경로·size·SHA-256을 정렬한 manifest가
  사전 승인된 `input_commitment_v2_4_deterministic.json`과 byte-for-byte 일치해야 하며 그
  manifest SHA-256을 실행 manifest에 기록한다.
- 각 source는 `os.open(..., O_RDONLY|O_NOFOLLOW)`로 열고 `fstat`에서 regular file,
  `st_nlink=1`, committed device/inode/size를 확인한다. 같은 file descriptor에서 hash→seek→parse
  →seek→rehash하고 두 hash와 전후 fstat identity/time/size가 모두 같아야 한다. path를 다시
  `lstat`했을 때 같은 device/inode가 아니면 TOCTOU로 INVALID다.
- CSV identity와 raw identity가 117:117로 1:1이어야 한다.
- 선택 identity는 12 incidents×3 conditions=36이고 각 cell은 정확히 하나여야 한다.
- ground truth 전체와 12행 projection은 위 두 SHA-256에 exact 일치해야 한다. ontology의
  incident별 component/fault/mechanism/action provenance도 projection과 일치해야 한다.
- candidate schema는 36/36 동일해야 한다. 본문은 로그에 출력하지 않는다.
- 실행 output directory는 사전에 존재하지 않아야 하며 부분 파일을 원자 rename으로 publish한다.
- 어느 gate든 실패하면 scoring 결과·부분 summary를 publish하지 않고 `INVALID` receipt만 남긴다.

### 9.3 사전 machine-only parse 편차 provenance

기존 `tests.test_v2_4_audit` real-input regression이 generic V2.4 parser에서 candidate JSON을
machine-only로 decode/parse했을 가능성을 숨기지 않는다.
`docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json`과 approval provenance에
상태 `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION` 및 동일 evidence digest를 required로 기록하며
`candidate/process access 0` 또는
`process_access_zero=true`라고 표현하지 않는다. 이 편차가 confirmatory anti-overfitting gate를
통과하려면 다음 네 evidence가 모두 있어야 한다.

1. 실행 명령·시각·git commit, exact interpreter와 stdout/stderr/log digest 및 exit status.
2. candidate body/value가 stdout, stderr, log, exception, agent/human context로 전달되지 않았다는
   operator attestation과 executable no-text-egress evidence.
3. V2.4-D scorer·ontology·alias extraction·condition score가 실행되지 않았다는 static call-graph,
   command/log, import/call counter evidence.
4. machine parse 이후 ontology/metric/alias/threshold/status에 observed-output-derived change가
   없다는 parse 시점 commit→code-only candidate `I0`→full candidate `I1`의 file/diff provenance와 operator
   attestation.

네 evidence 중 하나라도 없거나 candidate text가 human/agent context로 egress됐으면 승인 gate는
실패한다. 네 evidence가 모두 맞으면 이 사건은 결과 정보를 구현자에게 전달하지 않은
non-informative process deviation으로 보존하며 semantic outcome 정의를 바꾸거나 candidate 표현에
맞춘 alias를 허용하지 않는다. 이후 보고는 각각 `human_agent_text_egress=0`,
`v2_4_d_scorer_execution=0`, `observed_output_derived_changes=0`이라고 구체적으로 쓰며 포괄적인
“candidate 접근 0”을 쓰지 않는다.

## 10. 통계 분석

### 10.1 Primary comparison

incident `i`마다 `R_i=JLC-D(blind_procedural_rag)`,
`P_i=JLC-D(length_placebo)`를 둔다.

- paired risk difference: `RD = mean(R_i - P_i)`.
- `b = count(R_i=1,P_i=0)` (RAG-only success).
- `c = count(R_i=0,P_i=1)` (placebo-only success).
- exact one-sided McNemar/binomial test:
  `p = Pr[X >= b | X ~ Binomial(b+c, 0.5)]`.
- `b+c=0`이면 `p=1.0`으로 고정한다.
- 유의수준은 one-sided `alpha=0.05`다. 방향은 ontology freeze 전에 사전등록됐다.
- discordant dominance `q=b/(b+c)`의 two-sided 95% Clopper-Pearson exact CI를 보고한다.
  discordance 0이면 q와 CI는 `NA`, p만 1.0으로 보고한다.
- RD의 95% percentile paired bootstrap CI는 12 incident pair를 replacement로 50,000회
  resample하고 Python stdlib `random.Random(20260831)`로 계산한다. 정렬 표본에서
  `h=(n-1)p`, `j=floor(h)`, `g=h-j`, `x[j]+g*(x[j+1]-x[j])`인 linear percentile을
  p=.025/.975에 적용한다. float는 finite 검사 후 `format(x, ".17g")`, negative zero는 `0`으로
  canonical serialize한다. NumPy/SciPy에는 의존하지 않는다. 이 CI는 small-n exact CI라고
  부르지 않는다.

### 10.2 Secondary/exploratory

- RAG 대 runtime `JLC-D`: RD와 discordance count만 descriptive.
- CM, FLM, MCA, RA, FULL, JLC-relaxed: 조건별 count/rate와 paired difference descriptive.
- secondary/exploratory inferential test 수는 **0**으로 고정한다. Cochran's Q, secondary
  McNemar, fault별 test, secondary CI와 p-value를 생성하거나 보고하지 않는다.
- fault-group matrix와 atom-hit matrix는 count/rate만 descriptive다.
- fault별 n=1~2이므로 fault-specific p-value와 성공 판정은 금지한다.
- FULL에서 `rate_RAG < rate_placebo`이면 `REMEDIATION_REGRESSION_FLAG=true`; 이는 primary
  유의성 판정을 바꾸지 않고 함께 보고한다.

### 10.3 Missingness

이 실험은 완전한 frozen 12 pairs를 전제로 한다. candidate missing, parse/schema failure,
identity duplication, ontology miss, hash mismatch를 0으로 impute하지 않는다. 하나라도 있으면
confirmatory 분석 전체를 `INVALID`로 두며 complete-case 분석을 primary로 대체하지 않는다.

## 11. 사전등록 상태 판정

판정 우선순위는 위에서 아래다.

| 상태 | exact 조건 | 허용되는 결론 |
|---|---|---|
| `INVALID` | hash/schema/identity/blinding/freeze/replay gate 하나 이상 실패 | 효과 판정 불가 |
| `REVERSED` | 유효 run에서 `RD < 0` | RAG가 낮은 방향 |
| `NO_EVIDENCE` | `RD = 0` | 차이 증거 없음; discordance 0도 포함 |
| `DIRECTIONAL_ONLY` | `RD > 0`이고 one-sided `p >= 0.05` | RAG 우세 방향이나 입증 아님 |
| `SUPPORTED` | `RD > 0`이고 one-sided `p < 0.05` | 이 12 incidents의 JLC-D에서 RAG 우세 지지 |

machine-readable summary는 `primary_status`와 `remediation_regression_flag`를 별도 required
field로 저장한다. 합성 status는 만들지 않는다. presentation 문구에 경고를 병기할 수 있지만
단순히 FULL이 “낮지 않음”을 non-inferiority로 주장하지 않는다. remediation flag가 true이면
“RCA 전반 개선”이라는 표현은 금지한다.

n=12에서는 `c=0`일 때도 `b>=5`가 되어야 p<0.05다. 따라서 `DIRECTIONAL_ONLY`는 논문에서
효과 입증으로 서술하지 않는다.

## 12. 구현·실행 계획

### Step 2 — fresh 방법론 비평

최초 FAIL부터 Revision 5 수정 요구까지의 기존 section을 보존하고 같은 cumulative 정본
`docs/plans/review_v2_4_deterministic.md`에 Revision 6 semantic 재검토를 append할 예정이다.
별도 semantic review 파일을 만들지 않는다. review 파일은 자신의 최종 SHA를 포함하지 않으며
cumulative append content와 새 commit `I0`의 git blob/tree identity로 정본화한다. 최종 filesystem
SHA-256는 파일 밖 provenance에서만 기록한다.

1. candidate를 보지 않고 ontology가 ground truth/public taxonomy만으로 도출됐는가.
2. CM/FLM/MCA/RA field isolation과 DNF semantics가 모호하지 않은가.
3. alias가 지나치게 넓거나 incident별로 비대칭이지 않은가.
4. negation, absence assertion, contradiction 우선순위가 synthetic test로 반증 가능한가.
5. primary 하나, one-sided 방향, multiplicity, missingness, small-n 해석이 타당한가.
6. FULL secondary가 primary status를 사후 변경하지 않는가.
7. hash/freeze/clean-checkout/replay가 result-independent change control을 보장하는가.
8. 주장 경계가 human semantic evaluation과 external validity로 확장되지 않는가.

### Step 3 — 구현

- ontology JSON과 parser/scorer/analyzer를 독립 모듈로 만든다.
- `tests/test_v2_4_deterministic.py`, `run.py`, `build_ontology.py`는 reviewed bootstrap만 사용한다.
  각 script는 자신의 `Path(__file__).resolve()`에서 expected repo root를 계산하고 ancestor
  no-symlink·git identity를 확인한 뒤 그 root 하나만 `sys.path.insert(0, ...)`한다. arbitrary cwd,
  `PYTHONPATH`, user site, namespace fallback은 금지하고 bootstrap code/hash도 `I0` safety scope와
  `I1` target review에
  포함한다.
- source를 쓰기 모드로 열지 않는다.
- candidate text, matched substring, full response를 stdout/stderr에 출력하지 않는다.
  trace에는 identity, group ID, boolean, span의 token index만 저장한다.
- synthetic tests와 static validation을 통과한 code-only candidate `I0`를 먼저 만든다. old
  commitment는 deprecated artifact일 뿐 `I0` safety target이나 confirmatory input이 아니다.
- fresh safety reviewer가 real source 없이 detached `I0`의 exact commitment tool과 synthetic
  no-follow/TOCTOU/redaction tests를 PASS하고 external safety receipt를 봉인하기 전에는
  `commit_inputs.py`를 real input에 실행하지 않는다.
- exact reviewed I0 tool로 candidate를 decode하지 않는 opaque commitment를 재생성하고 historical
  deviation provenance와 함께 **그 두 파일만** 추가/수정한 full candidate `I1`을 만든다. `I0..I1`
  code diff는 0이어야 한다.
- `docs/plans/review_v2_4_deterministic_implementation.md`의 fresh full review는 ontology JSON이
  revision 6과 일치하는지, 새 commitment/envelope digest·legacy source digest·deviation evidence,
  모든 provenance/count와 synthetic test가 실제 PASS하는지를 exact detached `I1`에서 실데이터
  score 없이 검증한다.
- implementation review 문서 하나만 수정한 `B`와 approval 문서 하나만 추가한 `A`를 §9.1의
  parent/diff/hash gate로 만든다.

### Step 4 — clean-checkout 실행

1. `I0→I1→B→A` parent/diff/hash gate를 다시 확인하고 승인 문서를 포함한 exact commit `A`를
   detached clean worktree에 checkout한다.
2. `git status --porcelain`이 빈 값인지 확인한다.
3. commitment에 기록된 absolute Python interpreter의 binary SHA-256·`sys.version`이 같은지
   확인한다. stdlib-only scorer/analyzer를 `python -I`로 실행해 user-site·sitecustomize·현재
   directory import를 차단한다.
4. `env -i` 아래 exact PATH, `LC_ALL=C`, `TZ=UTC`, `PYTHONHASHSEED=0`, source/output/run ID만
   전달한다. `-I`가 Python env를 무시하므로 code는 set/dict iteration에 의존하지 않고 모든
   collection을 explicit sort하며 이를 synthetic test한다.
5. API key, cloud credential, kubeconfig, SSH agent, proxy env를 전달하지 않는다.
6. exact `<python> -I tests/test_v2_4_deterministic.py`,
   `<python> -I experiments/v2_4_deterministic/build_ontology.py --ontology
   experiments/v2_4_deterministic/ontology_v1.json`,
   `<python> -I experiments/v2_4_deterministic/run.py --self-test`를 실행한다. 세 command가 reviewed
   bootstrap으로 import되고 전부 PASS해야 한다.
7. metadata/hash preflight 후 mode 0700의 absent hidden staging parent 하나를 만든다. staging
   path와 run1 중간 결과·score·summary를 stdout/stderr, tracked result, public artifact path에
   노출하지 않는다.
8. hidden staging 안의 `run1/`과 `run2/`에서 **각각 독립된 full 36-row scoring+analysis run을
   끝까지 완료**한다. run1 성공 뒤에도 어떤 final/result/summary를 rename·copy·출력하지 않는다.
9. canonical sort는 `incident_id`, condition order
   `runtime,length_placebo,blind_procedural_rag`로 고정한다.
10. 두 full run의 result CSV, trace, paired table, summary와 timestamp/run path를 제외한 canonical
    manifest를 독립 재생성해 file별 SHA-256 및 aggregate canonical digest가 byte-identical인지
    확인한다.
11. run2 failure, canonical mismatch, hash/manifest/replay gate 실패면 public final/replay/result/
    summary는 모두 absent로 유지하고 결과 본문 없는 INVALID receipt만 publish한다. run1 artifact는
    공개하지 않고 mode-0700 quarantine에 둔다.
12. 두 run이 complete+equal일 때만 hidden parent 안에 `final/`, `replay/`, final manifest와 tracked
    result candidate를 포함한 **단일 release root**를 조립해 모든 file과 parent를 fsync한다. 그
    release root 하나를 absent public destination으로 한 번 atomic rename한다. 따라서 final과
    replay 중 하나만 보이는 partial release는 허용하지 않는다.

본 실험은 offline scoring이므로 `/lab-tunnel`과 `/lab-restore`를 실행하지 않는다. 연결을 열거나
cluster를 mutation하는 것이 오히려 protocol 위반이다.

## 13. 출력 경로와 manifest

Tracked 결과:

```text
results/experiment_results_v2_4_deterministic.csv
results/analysis_v2_4_deterministic.md
```

Append-only 변경 기록:

```text
results/experiment_changes_v2_4.md
```

Run artifact:

```text
artifacts/v2_4_deterministic/<run_id>/
  manifest.json
  input_manifest.json
  score_trace.jsonl
  paired_table.csv
  summary.json
  execution.log
  replay_manifest.json
```

결과 CSV는 36행이며 최소 다음 열을 갖는다.

```text
incident_id,fault_id,trial,condition,cm,flm,mca,ra,jlc_d,jlc_relaxed,full,
component_mention_path,fault_label_mention_path,mechanism_path,remediation_path,contradiction_ids,
ontology_sha256,scorer_sha256,input_csv_sha256,raw_manifest_sha256
```

본문과 matched text는 CSV에 넣지 않는다. `manifest.json`에는 I0/I1/B/A와 verified parent/diff,
approved_bundle/execution_commit/code_candidate/implementation_candidate, semantic/safety/full-
implementation/approval identity, §9.1 I0 safety scope와 I1 target 전체 blob/filesystem SHA-256,
plan/review/approval/ontology/init/builder/runner/commitment-tool/scorer/analyzer/test/new-input/
deviation/ground-truth/projection/interpreter hash, new commitment digest/provenance와 deprecated
source-identity comparison 결과,
Python version, seed, row counts, started/finished UTC, run1/run2 file별·aggregate canonical digest,
replay result, machine-parse deviation evidence digest, external/model/K8s call count 0을 기록한다.
`summary.json`은 `primary_status`와 `remediation_regression_flag`를 서로 독립된 required field로
저장하며 합성 status field를 금지한다.

## 14. Result-independent change control

1. V2.4-D scoring 및 candidate text의 human/agent egress 전에 plan·review·ontology·code·synthetic
   test를 commit하고 승인한다. 기존 machine-only parse는 §9.3 deviation으로 별도 기록한다.
2. 첫 실데이터 scoring 후 alias, contradiction, negation, field, metric, status threshold를
   in-place 수정하지 않는다.
3. candidate 표현을 보고 추가한 alias는 어떤 이유로도 V2.4-D confirmatory result에 소급 적용하지
   않는다.
4. 구현 결함이 발견되면 기존 run을 `INVALIDATED`로 보존하고 scorer/ontology version을 올린다.
   수정 근거는 synthetic counterexample 또는 ground-truth/public taxonomy여야 하며 observed arm
   score 방향을 근거로 삼지 않는다.
5. 수정 시 세 조건 36행 전체를 다시 score하고 old/new 결과를 모두 공개한다.
6. 실수로 freeze 전에 candidate를 본 사람이 ontology를 수정했다면 그 사람의 변경은 받지 않고
   fresh reviewer가 결과를 모르는 상태에서 새 version을 작성하거나, 불가능하면 분석을
   `EXPLORATORY_ONLY`로 강등한다.
7. primary가 불리하다는 이유로 relaxed, FULL, runtime 비교를 primary로 승격하지 않는다.

## 15. 예상 시간·비용·리스크

- 설계 review: 1~2시간.
- 구현·synthetic tests: 2~4시간.
- local scoring·replay·분석: 수분 이내.
- 외부 과금: 0원. 새 AI credit/API 호출 없음.
- cluster risk: 없음. K8s 접근 자체를 금지한다.

주요 한계:

- 12 pairs라 검정력이 낮고 incomplete non-random prefix다.
- representative output은 upstream 자동 선택 편향이 있을 수 있다.
- lexical matcher는 옳은 paraphrase를 놓치거나 component의 문법적 역할을 구분하지 못한다.
- upstream language contract가 없어 ASCII 밖 alphanumeric token이 있으면 run 전체가
  `LANGUAGE_UNSUPPORTED`로 invalid된다. 따라서 비영어·비ASCII 출력에는 결론이 없다.
- 공개 benchmark metric 구조 차용이 데이터셋 외적 타당성을 주지는 않는다.
- JLC-D 개선은 canonical label/phrase 사용 증가일 수 있으며 실제 조사 reasoning 개선과 동일하지 않다.

## 16. Definition of Done

다음을 모두 만족해야 V2.4-D round가 완료된다.

- [ ] cumulative semantic review 정본에 Revision 6 PASS content가 append되고 새 `I0` blob/tree로 고정됨.
- [ ] semantic review 최종 filesystem SHA-256가 review 파일 밖 implementation review·approval·
      사용자 보고에 기록됨.
- [ ] candidate source 없이 detached `I0` commitment-safety review와 synthetic
      no-follow/TOCTOU/redaction tests가 fresh PASS하고 external receipt가 봉인됨.
- [ ] reviewed exact I0 tool로만 새 commitment가 생성되고 old artifact는
      `DEPRECATED_MACHINE_HASH_ONLY_COMMITMENT`/confirmatory-use 금지로 기록됨.
- [ ] fixed CSV SHA와 117개 source digest는 old opaque map에 exact 일치하고, 새 envelope digest는
      `I1`에서 freeze됨.
- [ ] `I1^=I0`, I0→I1 diff가 commitment modification+deviation provenance addition exact 두 줄이며
      실행 code hash가 불변임.
- [ ] detached full candidate commit `I1`의 별도 implementation review가 fresh PASS함.
- [ ] `B^=I1`, I1→B implementation-review-only diff와 target hash 일치가 확인됨.
- [ ] `A^=B`, B→A approval-only diff와 exact execution commit `A`가 확인됨.
- [ ] I0/I1/approval target에 init·builder·runner·commitment tool·new commitment·deviation provenance를
      포함한 전체 file hash map이 존재함.
- [ ] ontology JSON이 schema-valid이고 §4~§6과 exact 일치함.
- [ ] synthetic/static tests 37개 범주가 전부 PASS함.
- [ ] `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION`과 §9.3 네 evidence가 approval에 기록됨.
- [ ] human/agent candidate text egress 0, V2.4-D scorer 실행 0,
      observed-output-derived change 0이 입증되며 process-access 0 표현을 쓰지 않음.
- [ ] clean detached checkout과 빈 git status가 확인됨.
- [ ] ground-truth full/projection, input CSV, opaque raw commitment hash가 exact match함.
- [ ] raw 117, identity 117:117, 선택 36 완전성, lstat/no-follow/rehash gate가 PASS함.
- [ ] `python -I`, exact interpreter hash/version, canonical environment/replay가 확인됨.
- [ ] commit_inputs no-follow/TOCTOU/unexpected-entry/redaction executable gates가 PASS함.
- [ ] 원본 CSV/raw/ground truth 수정 0.
- [ ] 모델/API/K8s/SSH 호출 0.
- [ ] 결과 CSV 36행과 condition별 12행이 확인됨.
- [ ] paired table의 b/c, p, exact CI, RD/bootstrap CI를 독립 재계산함.
- [ ] secondary inferential p-value/CI/Cochran Q 생성 0이 확인됨.
- [ ] `primary_status`와 `remediation_regression_flag`가 별도 field로 존재함.
- [ ] hidden two-full-run이 완료되고 canonical hash 일치 뒤 single-root atomic release됨.
- [ ] run1 사전 공개 및 partial final/replay publication 0이 확인됨.
- [ ] fresh `results_critic`이 원자료 계수·통계·타당성·대안가설을 독립 검증함.
- [ ] `results/analysis_v2_4_deterministic.md`가 상태를 §11 중 하나로 판정함.
- [ ] `results/experiment_changes_v2_4.md`가 append-only 갱신됨.
- [ ] 다음 goal·새 세션 prompt·TickTick handoff가 생성됨.
- [ ] feature branch commit/push와 한국어 PR, 사용자 승인 merge가 완료됨.

이 목록의 일부만 완료된 상태에서는 `SCORING_PACKAGE_READY`, `RUN_INVALID`, 또는
`ANALYSIS_PENDING`처럼 실제 상태만 보고하며 “RAG가 RCA를 개선했다”고 결론내리지 않는다.
