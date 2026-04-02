# GitOps 컨텍스트 기반 Kubernetes 근본 원인 분석 (RCA)

> **논문 주제**: Kubernetes 클러스터 장애에 대한 LLM 기반 근본 원인 분석에서 GitOps 컨텍스트 통합의 효과 평가

## 연구 목적

기존 Kubernetes RCA(Root Cause Analysis)는 런타임 관측 데이터(메트릭, 로그, 이벤트)에만 의존한다. 본 연구는 LLM 기반 RCA에 **GitOps 컨텍스트**(배포 이력, 매니페스트 diff, FluxCD/ArgoCD 재조정 상태)를 결합하면 관측 데이터만 사용하는 접근법 대비 진단 정확도가 유의미하게 향상되는지 검증한다.

### 연구 질문

| ID | 질문 |
|----|------|
| **RQ1** | GitOps 컨텍스트(FluxCD/ArgoCD 상태, 매니페스트 diff)를 결합하면 LLM 기반 RCA 정확도가 관측 데이터만 사용하는 방식 대비 향상되는가? |
| **RQ2** | GitOps 신호(배포 이력, drift 감지, 재조정 상태) 중 RCA 성능에 가장 크게 기여하는 요소는 무엇인가? |

### 실험 설계

**System A (기준선)**: LLM + Prometheus 메트릭 + Loki 로그 + kubectl 이벤트
**System B (제안)**: System A + FluxCD 재조정 상태 + ArgoCD 동기화 상태 + Git 커밋 diff + RAG 지식베이스

10가지 장애 유형(F1~F10)을 각 5회씩 총 50건 주입하여 두 시스템을 평가하며, Wilcoxon signed-rank test로 통계적 유의성을 검증한다.

## 장애 유형 (F1~F10)

| ID | 이름 | 설명 |
|----|------|------|
| F1 | OOMKilled | 컨테이너 메모리 limit 초과, OOM killer에 의한 종료 |
| F2 | CrashLoopBackOff | 애플리케이션 반복 크래시 및 재시작 |
| F3 | ImagePullBackOff | 컨테이너 이미지 레지스트리 풀 실패 |
| F4 | NodeNotReady | 노드 장애 또는 네트워크 파티션 |
| F5 | PVCPending | 스토리지 프로비저닝 실패 |
| F6 | NetworkPolicy | 네트워크 정책에 의한 통신 차단 |
| F7 | CPUThrottle | CPU 리소스 경합 및 쓰로틀링 |
| F8 | ServiceEndpoint | 서비스 셀렉터 미스매치 |
| F9 | SecretConfigMap | 시크릿/컨피그맵 누락 또는 오류 |
| F10 | ResourceQuota | 네임스페이스 리소스 쿼터 초과 |

## 클러스터 환경

- **Kubernetes** v1.29.15 (kubeadm, 마스터 3대 + 워커 3대)
- **CNI**: Cilium 1.15.6 (VXLAN, MTU 1450)
- **GitOps**: FluxCD v2.3.0 + ArgoCD v7.9.1 (듀얼 GitOps)
- **모니터링**: kube-prometheus-stack v65.8.1 + Loki v6.55.0 + Promtail v6.17.1
- **스토리지**: local-path-provisioner v0.0.28
- **대상 애플리케이션**: Google Online Boutique (마이크로서비스 데모)

## 저장소 구조

```
.
├── README.md
├── docs/                    # RAG 지식베이스 (65건)
│   ├── debugging/           # K8s 장애 디버깅 가이드 (20건)
│   ├── runbooks/            # 장애별 RCA 런북 (20건)
│   └── known-issues/        # 클러스터 기존 이슈 및 해결 사례 (25건)
├── k8s/                     # Kubernetes 매니페스트 (GitOps 관리)
│   ├── flux/                # FluxCD 부트스트랩 및 Kustomization CR
│   ├── infrastructure/      # StorageClass 등 클러스터 레벨 리소스
│   ├── monitoring/          # Prometheus, Loki, Promtail HelmRelease
│   ├── argocd/              # ArgoCD HelmRelease (듀얼 GitOps)
│   └── app/                 # Online Boutique 배포 (예정)
├── src/                     # 파이프라인 소스코드
│   ├── collector/           # Prometheus/Loki 데이터 수집
│   ├── processor/           # 특징 추출 및 전처리
│   ├── llm/                 # LLM 기반 RCA 추론
│   └── rag/                 # ChromaDB RAG 파이프라인
├── scripts/                 # 실험 자동화 (예정)
│   ├── fault_inject/        # 장애 주입 스크립트
│   ├── stabilize/           # 주입 후 안정화
│   └── evaluate/            # 평가 및 채점
├── results/                 # 실험 결과
│   └── ground_truth.csv     # 50건 레이블 (F1-F10 × 5회)
├── configs/                 # 파이프라인 설정
└── requirements.txt         # Python 의존성
```

## 실험 워크플로우

```
1. 사전 점검    → 클러스터, 모니터링, GitOps 상태 확인
2. RAG 구축     → 65건 문서 → ChromaDB 인제스트 (1,243 chunks)
3. Ground Truth → 50건 레이블 정의 (F1-F10 × 5회)
4. 앱 배포      → Online Boutique (FluxCD HelmRelease)
5. 장애 주입    → F1-F10, System A/B 비교
6. 절삭 실험    → AB-1~AB-5 (GitOps 신호별 기여도 분석)
7. 통계 분석    → Wilcoxon signed-rank test
```

## 빠른 시작

```bash
# RAG 지식베이스 인제스트
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.rag.ingest --reset

# 클러스터 접속 (SSH 터널 필요)
ssh -N -f k8s-lab-tunnel
export KUBECONFIG=~/.kube/config-k8s-lab
kubectl get nodes
```
