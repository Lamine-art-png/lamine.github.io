# Disaster Recovery Playbook (Pilot)

RTO: 4h | RPO: 24h

## Backups
- RDS automated snapshots (daily)
- S3 versioning enabled
- Terraform state in S3 + DynamoDB lock

## DR Drill (Staging)
1. Create RDS snapshot; note ID.
2. Simulate failure (stop ECS); confirm alarms.
3. Restore DB to new instance; swap `DATABASE_URL` secret.
4. Terraform apply to redeploy.
5. Re-run ingestion on last day’s drops.
6. Validate KPIs & readiness probes.

Evidence: logs + snapshot ARNs in `ops/evidence/`.
