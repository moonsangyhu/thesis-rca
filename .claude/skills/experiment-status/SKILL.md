---
name: experiment-status
description: 실험 진행상황 확인 스킬. "/experiment-status", "/실험상황", "실험 진행상황" 등으로 호출. trial별 결과와 의미를 보여줌.
---

# Experiment Status — 실험 진행상황 확인

실험 CSV 결과를 읽고, 프로세스 상태와 trial별 결과 + 각 trial의 실험 의미를 보여준다.

## Workflow

### 1. 프로세스 상태 확인

```bash
ps aux | grep "experiments.v[0-9].run" | grep -v grep | head -3
```

실행 중인 실험 프로세스 PID와 경과 시간을 확인한다. 없으면 "실험 프로세스 없음"으로 표시.

### 2. 결과 CSV 읽기

**중요: CSV에 쉼표가 포함된 quoted 필드가 있으므로 반드시 Python csv 모듈로 파싱해야 한다. awk -F',' 사용 금지.**

현재 실행 중인 버전의 CSV를 확인한다:
- v1: `results/experiment_results_v1.csv`
- v2: `results/experiment_results_v2.csv`
- v3: `results/experiment_results_v3.csv`

가장 최근 수정된 CSV를 대상으로 한다. 아래 Python 명령으로 파싱한다:

```bash
python3 -c "
import csv, sys
with open('results/experiment_results_v2.csv') as f:
    for r in csv.reader(f):
        if r[0]=='timestamp': continue
        print(f'{r[1]:4s} t{r[2]:<2s} {r[3]}  {r[4]:25s} correct={r[5]:<2s} score={r[6]}')
"
```

v1이나 v3를 볼 때는 파일명만 변경한다.

### 3. Trial별 결과 + 의미 출력

CSV를 파싱하여 아래 형식으로 출력한다. **반드시 각 trial의 실험 의미(어떤 서비스에 어떤 fault를 주입했는지)를 함께 표시**해야 한다.

## Ground Truth 참조 (trial별 실험 의미)

아래 정보를 `results/ground_truth.csv`에서 읽어 각 trial 결과 옆에 표시한다.

### F1 — OOMKill (메모리 초과 → OOM 종료)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | cartservice | 메모리 32Mi 제한 |
| t2 | recommendationservice | 메모리 24Mi 제한 |
| t3 | checkoutservice | 메모리 16Mi 제한 |
| t4 | productcatalogservice | 메모리 16Mi 제한 |
| t5 | frontend | 메모리 32Mi 제한 |

### F2 — CrashLoopBackOff (컨테이너 시작 실패 → 반복 재시작)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | paymentservice | 진입점 스크립트 손상 |
| t2 | emailservice | 잘못된 SMTP 설정 |
| t3 | currencyservice | 초기화 중 NPE 주입 |
| t4 | shippingservice | 포트 충돌로 바인드 실패 |
| t5 | adservice | 필수 플래그 누락 |

### F3 — ImagePullBackOff (이미지 풀 실패)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | frontend | 존재하지 않는 태그 (v99.99.99) |
| t2 | cartservice | 인증 없는 프라이빗 레지스트리 |
| t3 | productcatalogservice | 레지스트리 URL 오타 |
| t4 | checkoutservice | 잘못된 SHA256 다이제스트 |
| t5 | loadgenerator | 레이트 리밋 걸린 레지스트리 |

### F4 — NodeNotReady (워커 노드 장애)
| Trial | 대상 노드 | 주입 방법 |
|-------|----------|----------|
| t1 | worker01 | kubelet 중지 + cordon |
| t2 | worker02 | iptables로 API 서버 차단 |
| t3 | worker03 | stress-ng 메모리 고갈 |
| t4 | worker01 | 디스크 95% 채움 |
| t5 | worker02 | containerd 중지 |

### F5 — PVCPending (PVC 바인딩 실패)
| Trial | 대상 | 주입 방법 |
|-------|------|----------|
| t1 | redis-cart | 존재하지 않는 StorageClass |
| t2 | prometheus | 500Gi 초과 요청 |
| t3 | loki | local-path-provisioner 삭제 |
| t4 | redis-cart | ReadWriteMany 비지원 모드 |
| t5 | grafana | 불가능한 노드 어피니티 |

### F6 — NetworkPolicy (네트워크 정책으로 통신 차단)
| Trial | 대상 | 주입 방법 |
|-------|------|----------|
| t1 | 전체 | deny-all ingress 정책 |
| t2 | cartservice | frontend→cart gRPC 7070 차단 |
| t3 | checkoutservice | checkout→payment egress 차단 |
| t4 | productcatalogservice | DNS egress (포트 53) 차단 |
| t5 | redis-cart | cart→redis 6379 차단 |

### F7 — CPUThrottle (CPU 제한으로 극심한 쓰로틀링)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | frontend | CPU 10m 제한 |
| t2 | checkoutservice | CPU 5m 제한 |
| t3 | productcatalogservice | CPU 5m 제한 |
| t4 | adservice | CPU 5m 제한 (Java) |
| t5 | currencyservice | CPU 5m 제한 |

### F8 — ServiceEndpoint (서비스 엔드포인트 오설정)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | frontend | selector를 미매칭 라벨로 변경 |
| t2 | cartservice | targetPort를 9999로 변경 |
| t3 | paymentservice | 파드에서 app 라벨 제거 |
| t4 | shippingservice | 항상 실패하는 readinessProbe |
| t5 | emailservice | 서비스 포트를 9999로 변경 |

### F9 — SecretConfigMap (시크릿/컨피그맵 오설정)
| Trial | 대상 서비스 | 주입 방법 |
|-------|-----------|----------|
| t1 | cartservice | 존재하지 않는 Secret 참조 |
| t2 | frontend | ConfigMap에 잘못된 포트 |
| t3 | paymentservice | 볼륨 마운트할 ConfigMap 삭제 |
| t4 | checkoutservice | Secret 키 이름 오류 |
| t5 | emailservice | base64 인코딩 손상 |

### F10 — ResourceQuota (리소스 쿼터 제한)
| Trial | 대상 | 주입 방법 |
|-------|------|----------|
| t1 | boutique NS | pods=5 쿼터 |
| t2 | boutique NS | requests.cpu=100m 쿼터 |
| t3 | boutique NS | requests.memory=128Mi 쿼터 |
| t4 | boutique NS | services=3 쿼터 |
| t5 | boutique NS | LimitRange max memory=32Mi |

## 4. 출력 형식

각 fault 그룹별로 테이블을 출력한다:

```
### F{N} — {fault_name} ({설명})
| Trial | 대상 | 주입 | System A | System B |
|-------|------|------|----------|----------|
| t1 | {service} | {method} | {prediction} ({score}) ✓/✗ | {prediction} ({score}) ✓/✗ |
```

마지막에 전체 요약 테이블을 추가한다:

```
### 전체 요약
| Fault | A 정답률 | A 평균점수 | B 정답률 | B 평균점수 |
```

### 5. 로그 꼬리 확인

```bash
tail -3 results/experiment_v2.log
```

현재 어떤 trial이 진행 중인지 표시한다.
