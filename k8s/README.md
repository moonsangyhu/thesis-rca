# k8s/ — Kubernetes 매니페스트 (GitOps 관리)

## 목적

모든 클러스터 인프라가 이 디렉토리에 선언적으로 정의되어 있으며, **FluxCD GitOps**를 통해 배포된다. FluxCD는 이 저장소를 감시하고 클러스터 상태를 매니페스트와 자동으로 일치시킨다.

이것이 논문의 핵심이다: Git 커밋 이력과 FluxCD 재조정 상태가 곧 **GitOps 컨텍스트 신호**가 되며, System B는 이 신호를 활용하여 향상된 RCA를 수행한다. 모든 인프라 변경은 Git → FluxCD → 클러스터로 흐르며, RCA 파이프라인이 장애 이벤트와 상관 분석할 수 있는 감사 가능한 배포 이력을 생성한다.

## 구조

```
k8s/
├── flux/                # FluxCD Kustomization CR (오케스트레이션 레이어)
│   ├── flux-system/     # FluxCD 부트스트랩 컴포넌트
│   ├── infrastructure/  # → ../infrastructure/ 참조
│   ├── monitoring/      # → ../monitoring/ 참조
│   └── argocd/          # → ../argocd/ 참조
├── infrastructure/      # 클러스터 레벨 리소스
│   └── local-path-provisioner  # 기본 StorageClass (v0.0.28)
├── monitoring/          # 관측성 스택 (HelmRelease)
│   ├── kube-prometheus-stack v65.8.1  # Prometheus, Grafana, node-exporter
│   ├── loki v6.55.0                   # 로그 집계 (SingleBinary)
│   └── promtail v6.17.1              # 로그 전송 (DaemonSet)
├── argocd/              # ArgoCD 듀얼 GitOps (v7.9.1)
└── app/                 # Online Boutique 배포 (예정)
```

## 의존성 체인

```
flux-system → infrastructure → monitoring
                             → argocd
                             → app (예정)
```

FluxCD Kustomization은 `dependsOn`으로 순서를 보장한다 — monitoring과 argocd는 infrastructure(StorageClass)가 Ready된 후에만 배포된다.

## 듀얼 GitOps 아키텍처

본 실험은 **FluxCD**와 **ArgoCD**를 동시에 운용한다:

- **FluxCD**: 모든 인프라를 관리하는 주(primary) GitOps 오퍼레이터. 재조정 이벤트, Helm release 상태, Kustomization 헬스 신호를 생성한다.
- **ArgoCD**: 애플리케이션 동기화 상태, drift 감지, 리소스 추적을 제공하는 보조 GitOps 도구. FluxCD *에 의해* 배포된다.

두 도구 모두 GitOps 신호(동기화 상태, drift, 재조정 타이밍)를 생성하며, System B는 이를 런타임 장애와 상관 분석하여 RCA 정확도를 높인다.
