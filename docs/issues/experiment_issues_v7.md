# V7 실험 이슈 트래커

## 요약
- 총 이슈: 4건
- 심각(P0, 실험 무효화): 0건
- 경고(P1, 다수 trial 영향): 2건
- 참고(P2-P3, 다음 실험 시 수정): 2건

---

## 이슈 목록

### [ISS-001] comprehensive_health_check SSH 인증 실패
- **카테고리**: code
- **심각도**: P1 (warning)
- **영향**: 매 trial recovery 시 health check가 항상 실패 → 불필요한 full_reset 실행
- **발생 빈도**: 매 trial (18/18 확인)
- **근본 원인**: `health_verify.py`의 `_check_disk_usage()`가 `ssh_node()`를 호출하는데, `ssh_node()`는 `-J debian@211.62.97.71:22015` jump host를 사용. 하지만 실험 런타임에서 SSH 키(`yms-classic-key.pem`)가 `-i` 옵션 없이 호출되어 `Permission denied (publickey)` 발생.
- **현재 영향**: 실험 자체는 계속 진행됨 (health check 실패 시 로그만 남김). 하지만 매 trial마다 불필요한 full_reset이 실행되어 recovery 시간 증가 + 불필요한 manifest 재적용.
- **수정 방안**: `ssh_node()` 함수가 SSH 키를 자동으로 포함하도록 수정하거나, `health_verify.py`의 disk check에서 SSH 키 경로를 명시적으로 전달. 또는 disk check를 `kubectl exec`로 대체.
- **관련 로그**:
  ```
  worker01 disk check failed: invalid literal for int() with base 10: 
  'debian@211.62.97.71: Permission denied (publickey).\nConnection closed by UNKNOWN port 65535'
  ```

### [ISS-002] frontend endpoint 미복원 (recovery 후)
- **카테고리**: recovery
- **심각도**: P1 (warning)
- **영향**: F3, F4 recovery 후 frontend endpoint가 0 → health check 실패 트리거
- **발생 빈도**: F3 t4, t5 및 F4 전체 (약 7건)
- **근본 원인**: F3(ImagePull)/F4(NodeNotReady) recovery 시 `rollout undo` 후 frontend pod가 재생성되지만, readiness probe 통과까지 시간이 필요. `_wait_for_healthy()` 300초 내에 endpoint가 복원되지 않는 경우 존재.
- **현재 영향**: comprehensive_health_check에서 CRITICAL 로그 발생. 다음 trial 시작 전 health_check(기존)는 pod 수만 확인하므로 endpoint 미복원 상태에서 다음 trial 진행 가능.
- **수정 방안**: `_wait_for_healthy()`에 endpoint 복원 확인 추가. 또는 comprehensive_health_check에서 endpoint 0인 경우 해당 deployment `rollout restart` 수행.

### [ISS-003] full_reset manifest 경로 미존재
- **카테고리**: code
- **심각도**: P2 (info)
- **영향**: full_reset 실행 시 `/tmp/thesis-rca-work/k8s/app/online-boutique.yaml` 없어 실패
- **발생 빈도**: ISS-001 트리거 시마다 (매 trial)
- **근본 원인**: `ORIGINAL_MANIFEST` 경로가 실험 환경과 맞지 않음. `/tmp/thesis-rca-work/` 디렉토리가 로컬에 없음.
- **현재 영향**: full_reset이 실패하지만, recovery 자체는 fault-specific recoverer에서 이미 수행되었으므로 대부분 정상 복구됨.
- **수정 방안**: 올바른 manifest 경로로 수정하거나, FluxCD/ArgoCD sync를 full_reset 대안으로 사용.

### [ISS-004] Loki 500 Internal Server Error (F4 trial 중)
- **카테고리**: infra
- **심각도**: P2 (info)
- **영향**: F4 t3 (worker03 stress-ng) 동안 Loki가 500 에러 반환 → 로그 수집 실패
- **발생 빈도**: 4건 (F4 t3 System A/B 수집 시)
- **근본 원인**: F4 t3에서 worker03에 stress-ng 메모리 고갈을 주입하면, Loki pod가 worker03에 스케줄된 경우 Loki 자체가 메모리 압박을 받아 쿼리 실패.
- **현재 영향**: F4 t3의 로그 데이터 부재 → 진단 정보 불완전. F4는 이미 0% 정확도이므로 결과에 큰 영향 없음.
- **수정 방안**: Loki pod를 control-plane 노드에 고정 (nodeSelector/toleration) 또는 F4 fault 주입 시 Loki가 있는 노드를 피하는 로직 추가.

---

## 이전 버전 이슈 해결 상태 (V6 → V7)

| V6 이슈 | V7 상태 |
|---------|---------|
| DiskPressure 오진단 (V6 1차 실험 20/26) | ✅ 해결 (실험 전 디스크 정리 + 환경 정상화) |
| Prometheus port-forward 불안정 (V6 F1 t2,t3 SKIP) | ⚠️ 부분 해결 (auto-restart 로직 존재, 이번에는 미발생) |
| Step 3 흡수 문제 (F6 0%, F9 -60pp) | 🔄 검증 중 (V7 Step 3 역추적 적용, F5-F10 결과 대기) |
