# V2.4-D 결정론적 RCA 채점 실험 계획

> 작성일: 2026-08-31
>
> 단계: Experiment Track Step 1 — 상세 설계, 구현·실행 전
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
> deterministic Joint RCA Accuracy(`JRA-D`)를 높이는가?

- **독립변수:** `context_condition` 한 가지
  (`blind_procedural_rag` 대 `length_placebo`). 두 조건은 V2.3에서 이미 생성·동결됐다.
- **종속변수:** incident별 binary `JRA-D = CA ∧ FA ∧ MCA`.
- **고정:** incident, representative-selection rule, 생성 결과, ground truth, 모델 provenance,
  scorer version, ontology, 정규화, 통계 절차.
- **새 호출:** LLM/API/Codex/Copilot 0, K8s/Prometheus/Loki/SSH 0, fault injection 0.
- **모델 정책:** 향후 호출이 있다면 `gpt-4o-mini` 고정 원칙을 적용하지만, 본 round에는
  모델 호출이나 모델 비교가 없다. Primary03의 봉인된 upstream model provenance를 그대로
  기록하며 모델을 독립변수로 해석하지 않는다.
- **구성개념 경계:** 이 결과는 frozen synthetic ground-truth와 구조화 free-text의 lexical
  concordance다. 사람과 동등한 의미 평가, production RCA, MTTR 개선을 뜻하지 않는다.

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
  Fault-Type Accuracy, Joint RCA Accuracy를 기본 구조로 쓴다.
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
| `CA` | `root_cause`만 | canonical target component positive path 만족, contradiction 없음 |
| `FA` | `identified_fault_type`만 | canonical fault family positive path 만족, contradiction 없음 |
| `MCA` | `root_cause`만 | incident-specific mechanism positive path 만족, contradiction 없음 |
| `RA` | `remediation[]`만 | accepted recovery path 하나를 완성, contradiction 없음 |

- **Primary:** `JRA-D = CA ∧ FA ∧ MCA`.
- **Secondary:** `FULL = JRA-D ∧ RA`, `CA`, `FA`, `MCA`, `RA`.
- **Relaxed sensitivity:** `JRA-relaxed = CA ∧ FA`.
- candidate의 한 field에 있는 정답 단어는 다른 축으로 이동하지 않는다.
- `RA`는 primary 판정에 포함하지 않는다. 복구 품질 저하는 별도
  `REMEDIATION_REGRESSION_FLAG`로 보고한다.

`JRA-D`는 Cloud-OpsBench JRA에 mechanism gate를 추가한 local compatible extension이다.
공식 Cloud-OpsBench score라고 부르지 않는다.

## 3. Ontology JSON 계약

구현 파일은 `experiments/v2_4_deterministic/ontology_v1.json` 하나다. 아래 JSON Schema와
§4~§6의 값이 의미 정본이다. 구현 중 표현 형식만 바꾸는 경우에도 review와 hash를 다시 받는다.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["ontology_version", "normalization", "negation", "incidents"],
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
    "negation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["window_tokens", "tokens", "phrases", "exceptions"],
      "properties": {
        "window_tokens": {"const": 3},
        "tokens": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
        "phrases": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
        "exceptions": {"const": ["not only"]}
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
    "matcher": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "value", "polarity"],
      "properties": {
        "kind": {"enum": ["literal", "regex"]},
        "value": {"type": "string", "minLength": 1},
        "polarity": {"enum": ["affirmative", "absence_assertion"]}
      }
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
          "required": ["component", "fault", "mechanism", "remediation"],
          "properties": {
            "component": {"$ref": "#/$defs/axis"},
            "fault": {"$ref": "#/$defs/axis"},
            "mechanism": {"$ref": "#/$defs/axis"},
            "remediation": {"$ref": "#/$defs/axis"}
          }
        }
      }
    }
  }
}
```

`literal`은 normalization 후 완전한 token sequence로만 match한다. `regex`는 normalized
token stream 전체에 Python `re.fullmatch`가 아니라 `re.search`로 적용하되, 모든 패턴은
계획에 명시된 `(?<![0-9a-z])`와 `(?![0-9a-z])` 경계를 포함해야 한다. 구현자가 새 alias나
regex를 추가할 수 없다.

## 4. 공통 concept lexicon

표기법은 다음과 같다.

- `/`로 구분한 문자열은 각각 `kind=literal`, `polarity=affirmative`다.
- `absence:`는 그 부정어를 포함한 전체 phrase 자체가 장애 상태의 긍정 증거다.
- `re:`는 그대로 저장하는 regex다.
- literal과 regex는 normalization 후 값이다.

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

Component 축의 contradiction 배열은 전 incident에서 빈 배열이다. 다른 service를 영향 범위로
함께 적었다는 이유만으로 target localization을 0으로 만들지 않는다. 따라서 CA는
`root_cause` 안의 canonical component 언급 정확도이며 문법적 culprit-role 판정은 아니다.

### 4.2 Fault-family groups

| ID | exact `any_of` |
|---|---|
| `FT_OOM` | `oomkilled` / `oom killed` / `out of memory` / `memory limit exceeded` / `container memory limit too low` |
| `FT_CRASHLOOP` | `crashloopbackoff` / `crash loop back off` / `crash loop` / `startup crash` |
| `FT_IMAGEPULL` | `imagepullbackoff` / `image pull back off` / `errimagepull` / `err image pull` / `failed to pull image` / `image pull failure` |
| `FT_NODENOTREADY` | `nodenotready` / `node not ready` / `kubelet unavailable` |
| `FT_PVCPENDING` | `pvcpending` / `pvc pending` / `persistent volume claim pending` / `volume provisioning failed` |
| `FT_NETWORKPOLICY` | `networkpolicy` / `network policy` / `network policy denied` / `dropped by policy` |
| `FT_CPUTHROTTLE` | `cputhrottle` / `cpu throttle` / `cpu throttled` / `cpu throttling` / `cfs throttled` / `container cpu limit too low` |
| `FT_SERVICEENDPOINT` | `serviceendpoint` / `service endpoint` / `service selector mismatch` / `selector mismatch` / `absence:no endpoints` / `absence:zero endpoints` |

각 incident의 FA contradiction은 위 표에서 자신의 group을 제외한 나머지 7개 group 전부다.
다중 fault family를 긍정적으로 나열한 모호한 진단은 FA=0이다. negated alternative는
contradiction으로 세지 않는다.

### 4.3 Mechanism groups

| ID | exact `any_of` |
|---|---|
| `M_MEMORY_LIMIT` | `memory limit` / `memory cgroup limit` / `container memory limit` |
| `M_LIMIT_TOO_LOW` | `memory limit too low` / `insufficient memory limit` / `re:(?<![0-9a-z])exceeded(?: [0-9]+(?:mi|mib)?)? memory limit(?![0-9a-z])` / `re:(?<![0-9a-z])memory(?: usage)? exceeded(?: the)? limit(?![0-9a-z])` |
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

| ID | exact `any_of` |
|---|---|
| `X_CPU_LIMIT` | `cpu limit too low` / `cpu throttling` / `cpu throttled` |
| `X_MEMORY_LIMIT` | `memory limit too low` / `oom killed` / `out of memory` |
| `X_IMAGE_REFERENCE` | `image pull` / `image tag` / `image digest` / `registry url` |
| `X_NETWORK_POLICY` | `network policy` / `networkpolicy` / `dropped by policy` |
| `X_SERVICE_SELECTOR` | `service selector` / `selector mismatch` / `no endpoints` |
| `X_SMTP` | `smtp configuration` / `smtp connection` |
| `X_NULL_POINTER` | `nullpointerexception` / `null pointer exception` |
| `X_PORT_CONFLICT` | `port conflict` / `address already in use` / `bind failure` |
| `X_MISSING_FLAG` | `missing required flag` / `missing command line flag` |
| `X_REGISTRY_DNS` | `registry url typo` / `dns resolution failure` / `no such host` |
| `X_DIGEST` | `digest mismatch` / `invalid digest` / `invalid sha256` |
| `X_REGISTRY_AUTH` | `missing imagepullsecret` / `authentication required` / `registry authentication` / `unauthorized registry` |
| `X_RATE_LIMIT` | `rate limit` / `too many requests` / `429` |
| `X_IMAGE_TAG_MISSING` | `nonexistent image tag` / `manifest unknown` / `tag does not exist` |
| `X_NETWORK_PARTITION` | `network partition` / `iptables blocking api` / `lease expired` |
| `X_MEMORY_PRESSURE` | `memory pressure` / `stress ng` / `kernel oom` |
| `X_DISK_PRESSURE` | `disk pressure` / `filesystem full` / `disk full` |
| `X_RUNTIME_DOWN` | `containerd stopped` / `container runtime down` / `pleg not healthy` |
| `X_STORAGECLASS` | `storageclass not found` / `storage class not found` / `premium ssd` |
| `X_PROVISIONER` | `provisioner unavailable` / `provisioner not running` / `provisioner deleted` |
| `X_STORAGE_CAPACITY` | `insufficient storage` / `500gi` / `request too large` |
| `X_ACCESS_MODE` | `readwritemany` / `access mode mismatch` / `unsupported access mode` |
| `X_NODE_AFFINITY` | `node affinity conflict` / `node affinity mismatch` |
| `X_REDIS_FAILURE` | `redis crashed` / `redis unavailable` / `redis server down` |
| `X_CPU_REQUEST` | `cpu request too low` / `low cpu request` / `insufficient cpu request` |
| `X_CPU_OVERLOAD_ONLY` | `cpu demand spike` / `cpu usage spike` / `traffic overload is the root cause` |
| `X_POD_CRASH` | `pod crash is the root cause` / `crashloopbackoff` |
| `X_WRONG_PORT` | `service targetport mismatch` / `wrong target port` / `wrong service port` |
| `X_DNS` | `dns failure` / `dns resolution failure` |

## 5. Incident별 positive path와 contradiction

모든 component path는 `root_cause`, fault path는 `identified_fault_type`, mechanism path는
`root_cause`, remediation path는 `remediation`만 읽는다. 아래 `A+B+C`는 한 path의
`all_of`, `P1 | P2`는 둘 중 하나의 완전한 path를 뜻한다.

### 5.1 F1 — memory limit OOM

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F1-t2` | recommendationservice, OOMKilled, 24Mi limit exceed/OOM | `C_RECOMMENDATION` | `FT_OOM` | `M_MEMORY_LIMIT + M_LIMIT_TOO_LOW + M_OOM_TERMINATION` | `X_CPU_LIMIT`, `X_IMAGE_REFERENCE`, `X_NETWORK_POLICY`, `X_SERVICE_SELECTOR` |
| `F1-t3` | checkoutservice, OOMKilled, 16Mi limit exceed/OOM | `C_CHECKOUT` | `FT_OOM` | `M_MEMORY_LIMIT + M_LIMIT_TOO_LOW + M_OOM_TERMINATION` | 동일 |

Remediation:

- `F1-t2`: `R_INCREASE + R_MEMORY_LIMIT + (R_96MI | R_HIGHER_SUFFICIENT)`.
- `F1-t3`: `R_INCREASE + R_MEMORY_LIMIT + (R_64MI | R_HIGHER_SUFFICIENT)`.
- contradiction: `R_DECREASE + R_MEMORY_LIMIT` path가 완성되면 RA=0.

### 5.2 F2 — corrupted entrypoint

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F2-t1` | paymentservice, CrashLoopBackOff, corrupted entrypoint startup exit | `C_PAYMENT` | `FT_CRASHLOOP` | `M_BAD_ENTRYPOINT + M_STARTUP_EXIT` | `X_MEMORY_LIMIT`, `X_IMAGE_REFERENCE`, `X_NETWORK_POLICY`, `X_SMTP`, `X_NULL_POINTER`, `X_PORT_CONFLICT`, `X_MISSING_FLAG` |

Remediation accepted paths:

- `R_FIX + R_ENTRYPOINT`
- `R_RESTORE + R_CORRECT_IMAGE`

Contradiction은 `R_BREAK + R_ENTRYPOINT`다.

### 5.3 F3 — image reference failures

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F3-t3` | productcatalogservice, ImagePullBackOff, registry hostname typo/DNS failure | `C_PRODUCTCATALOG` | `FT_IMAGEPULL` | `M_REGISTRY_REFERENCE + M_REGISTRY_NAME_ERROR` | `X_DIGEST`, `X_REGISTRY_AUTH`, `X_RATE_LIMIT`, `X_IMAGE_TAG_MISSING` |
| `F3-t4` | checkoutservice, ImagePullBackOff, invalid SHA256/digest mismatch | `C_CHECKOUT` | `FT_IMAGEPULL` | `M_IMAGE_DIGEST + M_DIGEST_INVALID` | `X_REGISTRY_DNS`, `X_REGISTRY_AUTH`, `X_RATE_LIMIT`, `X_IMAGE_TAG_MISSING` |

Remediation:

- `F3-t3`: `R_FIX + R_REGISTRY_REFERENCE + R_VALID`.
- `F3-t4`: `(R_FIX + R_IMAGE_DIGEST + R_VALID) | (R_USE + R_VALID_TAG)`.
- contradiction: `R_KEEP + (R_INVALID_REGISTRY | R_INVALID_DIGEST)`.

### 5.4 F4 — stopped kubelet

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F4-t1` | worker01, NodeNotReady, kubelet stopped | `C_WORKER01` | `FT_NODENOTREADY` | `M_KUBELET + M_KUBELET_STOPPED` | `X_NETWORK_PARTITION`, `X_MEMORY_PRESSURE`, `X_DISK_PRESSURE`, `X_RUNTIME_DOWN` |

Remediation은 `R_RESTART + R_KUBELET + R_UNCORDON` 하나만 허용한다. `R_STOP + R_KUBELET`이
완성되면 contradiction이다.

### 5.5 F5 — PVC provisioning

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F5-t2` | prometheus, PVCPending, 500Gi request exceeds capacity | `C_PROMETHEUS` | `FT_PVCPENDING` | `M_PVC_REQUEST + M_CAPACITY_INSUFFICIENT` | `X_STORAGECLASS`, `X_PROVISIONER`, `X_ACCESS_MODE`, `X_NODE_AFFINITY` |
| `F5-t3` | loki, PVCPending, local-path provisioner unavailable/deleted | `C_LOKI` | `FT_PVCPENDING` | `M_LOCALPATH_PROVISIONER + M_PROVISIONER_UNAVAILABLE` | `X_STORAGE_CAPACITY`, `X_STORAGECLASS`, `X_ACCESS_MODE`, `X_NODE_AFFINITY` |

Remediation:

- `F5-t2`: `(R_REDUCE + R_PVC_SIZE) | (R_ADD + R_DISK_CAPACITY)`.
- `F5-t3`: `(R_RESTORE | R_REDEPLOY | R_RECONCILE) + R_LOCALPATH_PROVISIONER`.
- contradiction: t2의 `R_INCREASE + R_PVC_SIZE`, t3의 `R_DELETE + R_LOCALPATH_PROVISIONER`.

### 5.6 F6 — NetworkPolicy route denial

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F6-t5` | redis-cart, NetworkPolicy, cartservice→redis-cart:6379 ingress block | `C_REDIS_CART` | `FT_NETWORKPOLICY` | `M_NETWORK_POLICY + M_BLOCK_OR_DENY + M_CARTSERVICE + M_REDIS_CART + M_PORT_6379` | `X_REDIS_FAILURE`, `X_SERVICE_SELECTOR`, `X_DNS`, `X_CPU_LIMIT` |

Remediation은 `R_ADD_ALLOW + R_NETWORK_POLICY + R_CARTSERVICE + R_REDIS_CART + R_PORT_6379`다.
`R_DENY + R_NETWORK_POLICY`가 완성되면 contradiction이다.

### 5.7 F7 — CPU limit throttling

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F7-t1` | frontend, CPUThrottle, 10m CPU limit | `C_FRONTEND` | `FT_CPUTHROTTLE` | `M_CPU_LIMIT + M_CPU_LIMIT_LOW + M_CPU_THROTTLED` | `X_MEMORY_LIMIT`, `X_CPU_REQUEST`, `X_CPU_OVERLOAD_ONLY`, `X_NETWORK_POLICY` |
| `F7-t3` | productcatalogservice, CPUThrottle, 5m CPU limit | `C_PRODUCTCATALOG` | `FT_CPUTHROTTLE` | `M_CPU_LIMIT + M_CPU_LIMIT_LOW + M_CPU_THROTTLED` | 동일 |

Remediation:

- `F7-t1`: `(R_INCREASE + R_CPU_LIMIT + (R_200M | R_HIGHER_SUFFICIENT)) | (R_REMOVE + R_CPU_LIMIT)`.
- `F7-t3`: `R_INCREASE + R_CPU_LIMIT + (R_100M | R_HIGHER_SUFFICIENT)`.
- contradiction: `R_DECREASE + R_CPU_LIMIT`.

### 5.8 F8 — missing pod label/service endpoints

| Incident | Canonical | Component | Fault | Mechanism positive | Mechanism contradictions |
|---|---|---|---|---|---|
| `F8-t3` | paymentservice, ServiceEndpoint, removed app label→unselected pods→empty endpoints | `C_PAYMENT` | `FT_SERVICEENDPOINT` | `M_SERVICE_SELECTOR + M_LABEL_MISSING_MISMATCH + M_NO_ENDPOINTS` | `X_POD_CRASH`, `X_NETWORK_POLICY`, `X_WRONG_PORT`, `X_DNS` |

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
| `R_HIGHER_SUFFICIENT` | `sufficient limit` / `adequate limit` / `appropriate limit` / `higher limit` |
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
| `R_REDEPLOY` | `redeploy` / `deploy again` |
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

`F5-t3`의 `(R_RESTORE | R_REDEPLOY | R_RECONCILE)`는 JSON에서 세 path로 전개한다.
표 안의 다른 괄호·OR도 모두 별도 positive path로 전개해 실행 중 동적 논리를 만들지 않는다.

## 7. 정규화·부정·field isolation 알고리즘

처리 순서는 고정한다.

1. JSON을 UTF-8 strict로 decode한다. replacement character가 있으면 전체 run을 invalid 처리한다.
2. field type을 확인한다. `identified_fault_type`와 `root_cause`는 string,
   `remediation`은 non-empty string의 list여야 한다.
3. 각 문자열에 Unicode NFKC 후 `casefold()`를 적용한다.
4. 원문의 `. ; : ! ? CR LF`를 clause boundary로 먼저 분리한다.
5. 각 clause에서 maximal Unicode alphanumeric run만 token으로 남긴다. 나머지는 separator다.
   따라서 `redis-cart`와 `redis cart`, `local-path`와 `local path`는 같은 token sequence가 된다.
6. literal은 token-sequence boundary에서만 match한다. substring match는 금지한다.
7. regex는 normalized clause에만 적용하며 clause를 넘지 않는다.
8. negation token은 `no, not, never, without, neither, nor, isnt, wasnt, arent, werent,
   cannot, cant, didnt, doesnt, wont`로 고정한다. phrase는 `rule out, ruled out`이다.
9. affirmative matcher 시작 전 같은 clause의 직전 최대 3 tokens 안에 negator의 끝이 있으면 그
   occurrence를 suppress한다. `not only`는 negation exception이다.
10. `polarity=absence_assertion` matcher는 자신이 포함한 `no/zero/without`을 장애 상태의 긍정
    표현으로 계산한다. 다만 그 matcher 자체 앞에 별도 negator가 있으면 suppress한다.
11. positive와 contradiction에 같은 negation 규칙을 적용한다.
12. positive path는 모든 group이 하나 이상의 unsuppressed occurrence를 가질 때만 pass한다.
13. contradiction group 하나라도 unsuppressed match면 해당 axis를 0으로 강제하고 matched span과
    group ID를 trace에 남긴다.
14. remediation list는 item별로 1~13을 수행한다. 하나의 alias가 item 경계를 넘을 수 없지만,
    path의 서로 다른 group은 여러 item에서 충족될 수 있다.

빈 문자열, `null`, 예상 밖 key, duplicate key, non-list remediation, empty remediation item은
오답으로 대체하지 않고 schema gate 실패로 전체 run을 `INVALID` 처리한다.

## 8. Synthetic-only 구현 검증

실제 36개 candidate를 처음 여는 시점 전에 다음 test가 모두 통과하고 코드가 commit돼야 한다.
fixture는 이 계획의 alias를 조합한 새 문장만 사용하며 candidate 문자열을 복사하지 않는다.

1. NFKC/casefold, hyphen·underscore·slash separator, token boundary.
2. `redis-cart`↔`redis cart`, `local-path`↔`local path` 동치.
3. substring 거부: `frontendish`, `notworker01x`, `redis carpeting`은 component 불일치.
4. field isolation: fault alias가 remediation에만 있어도 FA=0; mechanism alias가 fault field에만
   있어도 MCA=0; recovery alias가 root cause에만 있어도 RA=0.
5. positive conjunction: 한 group이 빠지면 path=0.
6. alternative remediation path: 완전한 대안 하나는 pass, 서로 다른 불완전 대안의 잘못된
   cross-join은 fail.
7. contradiction precedence: positive와 affirmative contradiction이 함께 있으면 0.
8. negation: `not a network policy issue`는 positive/contradiction 모두 match하지 않음.
9. coordinated negation: `no cpu or memory pressure`에서 두 concept 모두 suppress.
10. absence assertion: `no endpoints`와 `endpoints list empty`는 `M_NO_ENDPOINTS` match.
11. negation exception: `not only cpu throttling`에서 `cpu throttling`은 suppress하지 않음.
12. clause scope: `not image pull; digest mismatch`에서 앞 negation이 뒤 clause에 전파되지 않음.
13. remediation list item boundary와 multi-item group 결합.
14. FA 다중 긍정 family contradiction.
15. malformed UTF-8, duplicate JSON key, missing/extra key, 잘못된 type, 빈 list fail-close.
16. incident/condition duplicate, 누락, unexpected incident, 36행 초과·미달 fail-close.
17. CSV SHA mismatch, raw-tree manifest mismatch, ontology/scorer/plan hash mismatch fail-close.
18. 통계 known-answer:
    `b=5,c=0 → one-sided p=0.03125`, `b=4,c=0 → p=0.0625`,
    `b=0,c=5 → p=1`, `b=c=0 → p=1`.
19. fixed seed 20260831·50,000 paired bootstrap replay byte equality.
20. 입력 순서 shuffle 뒤 canonical sort 결과 byte equality.

실제 input을 이용한 test fixture 생성, snapshot/golden-output test, observed output에서 alias를
추출하는 coverage test는 금지한다.

## 9. 입력·hash hard gates

### 9.1 구현 전 gate

다음 파일을 feature branch에서 commit·push하고 fresh methodology reviewer의 P0 승인을 받는다.

```text
docs/plans/experiment_plan_v2_4_deterministic.md
docs/plans/review_v2_4_deterministic.md
docs/plans/input_commitment_v2_4_deterministic.json
experiments/v2_4_deterministic/ontology_v1.json
experiments/v2_4_deterministic/scorer.py
experiments/v2_4_deterministic/analyze.py
tests/test_v2_4_deterministic.py
```

review 이후 plan, review, ontology, scorer, analyzer, test의 SHA-256와 git commit을
`docs/plans/approval_v2_4_deterministic.md`에 기록하고 사용자 명시 승인을 받는다. 실제 candidate
본문을 읽는 명령은 이 승인 기록 이후에만 가능하다.

`input_commitment_v2_4_deterministic.json`은 이 예외적으로 허용된 **opaque hash-only** 단계에서
만든다. 파일 본문을 decode, parse, search, preview하거나 stdout에 쓰지 않고 SHA-256
stream으로만 읽어 117 raw relative paths·sizes·digests와 CSV digest를 canonical JSON에
봉인한다. 이 commitment 자체도 candidate scoring 전에 commit·review·승인한다.

### 9.2 실행 preflight gate

- source path는 Primary03 artifact 한 개로 exact resolve하고 symlink를 거부한다.
- 결과 CSV SHA-256이 §1.3 값과 일치해야 한다.
- raw directory는 117 regular JSON files만 허용한다. 상대경로·size·SHA-256을 정렬한 manifest가
  사전 승인된 `input_commitment_v2_4_deterministic.json`과 byte-for-byte 일치해야 하며 그
  manifest SHA-256을 실행 manifest에 기록한다.
- CSV identity와 raw identity가 117:117로 1:1이어야 한다.
- 선택 identity는 12 incidents×3 conditions=36이고 각 cell은 정확히 하나여야 한다.
- 선택 ground truth는 repository의 immutable `results/ground_truth.csv` SHA-256와 12행
  identity를 기록한다. ontology와 canonical truth의 incident별 component/fault/mechanism/action
  provenance가 일치해야 한다.
- candidate schema는 36/36 동일해야 한다. 본문은 로그에 출력하지 않는다.
- 실행 output directory는 사전에 존재하지 않아야 하며 부분 파일을 원자 rename으로 publish한다.
- 어느 gate든 실패하면 scoring 결과·부분 summary를 publish하지 않고 `INVALID` receipt만 남긴다.

## 10. 통계 분석

### 10.1 Primary comparison

incident `i`마다 `R_i=JRA-D(blind_procedural_rag)`,
`P_i=JRA-D(length_placebo)`를 둔다.

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
  resample하고 seed `20260831`, NumPy `PCG64`로 계산한다. 2.5/97.5 percentile의
  `method=linear`을 쓴다. 이 CI는 small-n exact CI라고 부르지 않는다.

### 10.2 Secondary/exploratory

- RAG 대 runtime `JRA-D`: RD와 discordance table만 descriptive.
- CA, FA, MCA, RA, FULL, JRA-relaxed: 조건별 count/rate와 paired difference descriptive.
- 세 조건 Cochran's Q와 fault-group matrix는 exploratory.
- secondary p-value를 생성한다면 Cochran Q와 모든 추가 paired tests를 한 family로 묶어 Holm
  보정하고 `exploratory`로 표시한다. primary p-value에는 보정하지 않는다.
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
| `SUPPORTED` | `RD > 0`이고 one-sided `p < 0.05` | 이 12 incidents의 JRA-D에서 RAG 우세 지지 |

`REMEDIATION_REGRESSION_FLAG`가 있으면 `SUPPORTED_WITH_REMEDIATION_WARNING`이라는 별도
표시를 덧붙이되 primary 상태 자체를 재정의하지 않는다. 단순히 FULL이 “낮지 않음”을
non-inferiority로 주장하지 않는다.

n=12에서는 `c=0`일 때도 `b>=5`가 되어야 p<0.05다. 따라서 `DIRECTIONAL_ONLY`는 논문에서
효과 입증으로 서술하지 않는다.

## 12. 구현·실행 계획

### Step 2 — fresh 방법론 비평

`docs/plans/review_v2_4_deterministic.md`에서 다음 P0를 독립 검토한다.

1. candidate를 보지 않고 ontology가 ground truth/public taxonomy만으로 도출됐는가.
2. CA/FA/MCA/RA field isolation과 DNF semantics가 모호하지 않은가.
3. alias가 지나치게 넓거나 incident별로 비대칭이지 않은가.
4. negation, absence assertion, contradiction 우선순위가 synthetic test로 반증 가능한가.
5. primary 하나, one-sided 방향, multiplicity, missingness, small-n 해석이 타당한가.
6. FULL secondary가 primary status를 사후 변경하지 않는가.
7. hash/freeze/clean-checkout/replay가 result-independent change control을 보장하는가.
8. 주장 경계가 human semantic evaluation과 external validity로 확장되지 않는가.

### Step 3 — 구현

- ontology JSON과 parser/scorer/analyzer를 독립 모듈로 만든다.
- source를 쓰기 모드로 열지 않는다.
- candidate text, matched substring, full response를 stdout/stderr에 출력하지 않는다.
  trace에는 identity, group ID, boolean, span의 token index만 저장한다.
- synthetic tests와 static validation을 통과한 뒤 commit한다.
- code review는 실데이터 score를 보지 않고 수행한다.
- 계획·review·ontology·code·test hash bundle을 사용자 승인받는다.

### Step 4 — clean-checkout 실행

1. 승인된 commit을 detached clean worktree에 checkout한다.
2. `git status --porcelain`이 빈 값인지 확인한다.
3. `env -i` 아래 최소 PATH, locale `C.UTF-8`, source/output/run ID만 전달한다.
4. API key, cloud credential, kubeconfig, SSH agent, proxy env를 전달하지 않는다.
5. synthetic test를 다시 실행한다.
6. metadata/hash preflight 후 36행을 한 번에 score한다. arm별 중간 결과를 보지 않는다.
7. canonical sort는 `incident_id`, condition order
   `runtime,length_placebo,blind_procedural_rag`로 고정한다.
8. output을 absent staging directory에 쓰고 fsync 후 atomic rename한다.
9. 같은 commit/input으로 두 번째 absent directory에 replay하고 canonical outputs의 SHA-256가
   byte-identical인지 확인한다. timestamp/run path는 canonical comparison에서 제외한다.
10. 두 run이 같을 때만 result report를 release한다.

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
incident_id,fault_id,trial,condition,ca,fa,mca,ra,jra_d,jra_relaxed,full,
component_path,fault_path,mechanism_path,remediation_path,contradiction_ids,
ontology_sha256,scorer_sha256,input_csv_sha256,raw_manifest_sha256
```

본문과 matched text는 CSV에 넣지 않는다. `manifest.json`에는 git commit, plan/review/approval,
ontology/scorer/analyzer/test/input/ground-truth hash, Python/NumPy version, seed, row counts,
started/finished UTC, replay result, external/model/K8s call count 0을 기록한다.

## 14. Result-independent change control

1. candidate 본문 접근 전 plan·review·ontology·code·synthetic test를 commit하고 승인한다.
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
- ontology alias가 영어 중심이라 다른 언어 출력을 과소평가할 수 있다.
- 공개 benchmark metric 구조 차용이 데이터셋 외적 타당성을 주지는 않는다.
- JRA-D 개선은 canonical label/phrase 사용 증가일 수 있으며 실제 조사 reasoning 개선과 동일하지 않다.

## 16. Definition of Done

다음을 모두 만족해야 V2.4-D round가 완료된다.

- [ ] 이 plan과 fresh method review의 hash가 고정되고 사용자 승인이 기록됨.
- [ ] ontology JSON이 schema-valid이고 §4~§6과 exact 일치함.
- [ ] synthetic-only tests 20개 범주가 전부 PASS함.
- [ ] 승인 전 candidate output 본문 접근 0이 provenance에 기록됨.
- [ ] clean detached checkout과 빈 git status가 확인됨.
- [ ] input CSV hash exact match, raw 117, identity 117:117, 선택 36 완전성 PASS.
- [ ] 원본 CSV/raw/ground truth 수정 0.
- [ ] 모델/API/K8s/SSH 호출 0.
- [ ] 결과 CSV 36행과 condition별 12행이 확인됨.
- [ ] paired table의 b/c, p, exact CI, RD/bootstrap CI를 독립 재계산함.
- [ ] same-commit replay의 canonical output hash가 일치함.
- [ ] fresh `results_critic`이 원자료 계수·통계·타당성·대안가설을 독립 검증함.
- [ ] `results/analysis_v2_4_deterministic.md`가 상태를 §11 중 하나로 판정함.
- [ ] `results/experiment_changes_v2_4.md`가 append-only 갱신됨.
- [ ] 다음 goal·새 세션 prompt·TickTick handoff가 생성됨.
- [ ] feature branch commit/push와 한국어 PR, 사용자 승인 merge가 완료됨.

이 목록의 일부만 완료된 상태에서는 `SCORING_PACKAGE_READY`, `RUN_INVALID`, 또는
`ANALYSIS_PENDING`처럼 실제 상태만 보고하며 “RAG가 RCA를 개선했다”고 결론내리지 않는다.
