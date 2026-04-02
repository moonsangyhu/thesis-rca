# scripts/ — 실험 자동화

## 목적

장애 주입 실험의 전체 생명주기를 자동화하는 스크립트이다: Online Boutique 애플리케이션에 장애를 주입하고, 시행 간 클러스터를 안정화하며, RCA 파이프라인 출력을 Ground Truth 레이블과 비교 평가한다.

이 스크립트들은 **재현 가능한 실험**을 보장한다 — 50건의 모든 시행에서 동일한 절차, 타이밍, 데이터 수집 프로토콜을 따른다.

## 구조

| 디렉토리/파일 | 상태 | 설명 |
|--------------|------|------|
| `fault_inject/` | **완료** | F1~F10 장애 주입 구현. kubectl patch/apply/delete 및 SSH로 장애 적용 |
| `stabilize/` | **완료** | 시행 후 복구 스크립트. rollout undo, 리소스 삭제, 노드 복원 |
| `evaluate/` | **완료** | Wilcoxon signed-rank test, 정확도/신뢰도 분석, 보고서 생성 |
| `run_experiment.py` | **완료** | 실험 오케스트레이터 — 주입→수집→RCA(A/B)→기록→복구 전체 자동화 |

## fault_inject/ — 장애 주입

| 파일 | 역할 |
|------|------|
| `config.py` | KUBECONFIG, SSH 접속 정보 (worker01~03), 장애별 대기 시간 (F1: 120s ~ F6: 60s) |
| `base.py` | kubectl/SSH/git 헬퍼 함수 (kubectl_apply, kubectl_patch, ssh_node, git_commit_and_push) |
| `injector.py` | `FaultInjector` 클래스: F1~F10 × 5 trial 전체 구현 |

장애별 주입 방식:
- **F1 OOMKilled**: 메모리 limit을 극도로 낮게 설정 (16Mi~32Mi)
- **F2 CrashLoopBackOff**: 컨테이너 command를 `exit 1`로 오버라이드
- **F3 ImagePullBackOff**: 존재하지 않는 이미지 태그/레지스트리로 변경
- **F4 NodeNotReady**: SSH로 kubelet 중지, iptables 차단, stress-ng, 디스크 채움, containerd 중지
- **F5 PVCPending**: 존재하지 않는 StorageClass, 과도한 용량, RWX 모드 등
- **F6 NetworkPolicy**: deny-all, 포트 차단, DNS 차단, egress 차단 등
- **F7 CPUThrottle**: CPU limit을 5m~10m으로 설정
- **F8 ServiceEndpoint**: 셀렉터 변경, targetPort 변경, 레이블 제거, readinessProbe 실패
- **F9 SecretConfigMap**: 존재하지 않는 Secret/ConfigMap 참조, 잘못된 키/값
- **F10 ResourceQuota**: pods=5, cpu=100m, memory=128Mi, services=3, LimitRange max=32Mi

## stabilize/ — 복구

| 파일 | 역할 |
|------|------|
| `recovery.py` | `Recovery` 클래스: 장애별 복구 구현 + `_wait_for_healthy()` (모든 Deployment Available 대기) |

복구 방식:
- F1/F2/F3/F7: `kubectl rollout undo` (이전 리비전 복원)
- F4: SSH로 서비스 재시작 (kubelet, containerd), iptables/stress-ng/diskfill 정리, `uncordon`
- F5: 잘못된 PVC/PV 삭제, provisioner 복원
- F6: NetworkPolicy 삭제
- F8: 원본 매니페스트 재적용 또는 `rollout undo`
- F9: `rollout undo` + 더미 Secret 삭제
- F10: ResourceQuota/LimitRange 삭제 + 전체 `rollout restart`

## evaluate/ — 평가 및 통계 분석

| 파일 | 역할 |
|------|------|
| `analyze.py` | `experiment_results.csv` 로드 → 정확도/신뢰도 산출 → Wilcoxon signed-rank test → 보고서 생성 |

출력:
- Overall accuracy (System A vs B)
- Per-fault accuracy (F1~F10 × A/B)
- Wilcoxon signed-rank test (정확도, 신뢰도)
- `results/experiment_report.json` 저장

## run_experiment.py — 실험 오케스트레이터

```bash
# 전체 50건 실행 (F1~F10 × 5 trials)
python -m scripts.run_experiment

# 특정 장애만 실행
python -m scripts.run_experiment --fault F1

# 특정 시행만 실행
python -m scripts.run_experiment --fault F1 --trial 3

# 드라이 런 (장애 주입 없이 신호 수집만 테스트)
python -m scripts.run_experiment --dry-run

# 모델/프로바이더 변경
python -m scripts.run_experiment --model gpt-4o --provider openai

# 장애 유형 간 쿨다운 시간 조정 (기본 1800초 = 30분)
python -m scripts.run_experiment --cooldown 600
```

## 실험 프로토콜

```
각 장애 F_i (i = 1..10)에 대해:
  각 시행 t (t = 1..5)에 대해:
    1. 장애 F_i 시행 t 주입           (fault_inject/)
    2. 증상 발현 대기 (60~180초)
    3. 신호 수집 (5분 윈도우)          (src/collector/)
    4. System A RCA 실행              (관측 데이터만 → src/llm/)
    5. System B RCA 실행              (+ GitOps + RAG → src/llm/)
    6. 결과 CSV 기록                  (results/experiment_results.csv)
    7. Raw 데이터 JSON 저장            (results/raw/)
    8. 복구 및 안정화                  (stabilize/)
    9. 시행 간 60초 대기, 장애 유형 간 30분 대기
```

## 출력 파일

| 파일 | 설명 |
|------|------|
| `results/experiment_results.csv` | 100행 (50 trials × System A/B), 15개 컬럼 |
| `results/raw/{F_id}_t{trial}_{system}_{timestamp}.json` | 시행별 전체 raw 데이터 (신호, 컨텍스트, LLM 응답) |
| `results/experiment.log` | 실험 전체 로그 |
| `results/experiment_report.json` | 최종 통계 분석 보고서 |
