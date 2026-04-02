# Known Issue: CronJob Schedule Uses UTC Causing KST Confusion

## Issue ID
KI-010

## Affected Components
- CronJob (batch/v1)
- All time-sensitive scheduled jobs (backups, reports, cleanup tasks)
- Operations teams working in KST (UTC+9) timezone

## Symptoms
- CronJob executes 9 hours later or earlier than expected in KST
- Daily backup job scheduled for "midnight" runs at 09:00 KST (midnight UTC) instead
- Business-hours maintenance job runs during off-hours KST
- `kubectl get cronjob` shows correct cron expression but jobs fire at unexpected local times
- Confusion when correlating CronJob execution times with application logs (which may use local time)
- Report generation jobs deliver data for wrong date boundaries

## Root Cause
Kubernetes CronJob schedule expressions always use UTC (Coordinated Universal Time). There is no implicit timezone conversion. South Korea Standard Time (KST) is UTC+9, meaning:

| Desired KST Time | UTC Schedule Expression |
|-----------------|-------------------------|
| 00:00 KST (midnight) | `0 15 * * *` (3 PM UTC previous day) |
| 09:00 KST | `0 0 * * *` (midnight UTC) |
| 18:00 KST | `0 9 * * *` |
| 02:00 KST (backup) | `0 17 * * *` |

Teams familiar with cron on Linux systems where the system timezone is KST will write `0 2 * * *` expecting it to mean 02:00 KST, but in Kubernetes it means 02:00 UTC = 11:00 KST.

Additionally, K8s 1.25 introduced the `spec.timeZone` field (graduated to stable in 1.27), but many teams are unaware of it or use cluster versions below 1.25.

## Diagnostic Commands
```bash
# List all CronJobs and their schedules
kubectl get cronjob -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,SCHEDULE:.spec.schedule,TIMEZONE:.spec.timeZone,LAST-SCHEDULE:.status.lastScheduleTime"

# Check when the last job actually ran
kubectl describe cronjob <name> -n <namespace> | grep -E "Last Schedule|Schedule:"

# Convert a UTC cron time to KST
# Example: "0 15 * * *" (15:00 UTC) = 00:00 KST next day (UTC+9)
python3 -c "
from datetime import datetime, timezone, timedelta
utc_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
kst = timezone(timedelta(hours=9))
print(utc_time.astimezone(kst).strftime('%Y-%m-%d %H:%M KST'))
"

# Check if the cluster version supports timeZone field
kubectl version --short | grep Server
# Supported if Server Version >= v1.25

# Check CronJob spec for timeZone field
kubectl get cronjob <name> -n <namespace> -o yaml | grep -i timezone
```

## Resolution
**Option A (K8s 1.27+, recommended)**: Use the `spec.timeZone` field:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-backup
spec:
  schedule: "0 2 * * *"       # This is now 02:00 KST
  timeZone: "Asia/Seoul"       # Explicitly set timezone
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: backup-tool:v1.0
          restartPolicy: OnFailure
```

Verify supported timezones from the IANA database: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

**Option B (All K8s versions)**: Manually convert KST to UTC in the schedule:
```yaml
# To run at 02:00 KST (UTC+9), subtract 9 hours: 02:00 - 09:00 = 17:00 UTC previous day
spec:
  schedule: "0 17 * * *"   # 17:00 UTC = 02:00 KST
```

Add a comment to the CronJob annotations documenting the intended KST time:
```yaml
metadata:
  annotations:
    description: "Daily backup - runs at 02:00 KST (0 17 * * * UTC)"
```

**Option C**: Deploy a timezone-aware CronJob controller or use an operator that handles timezone conversion.

## Workaround
Document all CronJob schedules in a central spreadsheet or annotation with both UTC and KST times. Use `kubectl annotate cronjob <name> "intended-kst-time=02:00"` for quick reference.

## Prevention
- Establish a cluster convention: always use `spec.timeZone: "Asia/Seoul"` for new CronJobs on clusters running K8s 1.27+
- Add timezone documentation to all CronJob manifests via annotations
- Include a `cron-schedule-checker` step in CI/CD that validates CronJob schedules have a `timeZone` field or have UTC-time documentation
- Create a cluster-wide policy (Kyverno/OPA) that warns when CronJobs are created without `spec.timeZone` on K8s 1.27+

## References
- K8s CronJob documentation: https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
- CronJob timeZone field (K8s 1.25+): https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#time-zones
- IANA timezone database: https://www.iana.org/time-zones
- Cron expression guide: https://crontab.guru/
