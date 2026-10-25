# Operate the workshop platform

## Stock and invoice rules

- PostgreSQL owns current quantity and the movement ledger. Do not correct a
  quantity by editing Redis, a job projection or a reference-image record.
- Each user command has a durable idempotency key and stored response. Retrying
  unchanged data uses that key; a new physical receipt gets a new key.
- Camera encounter identity is independent of image identity. Identical photos
  can belong to different deliveries. The capture ledger reference is unique.
- Receipt/issue/return, command response and inventory outbox commit together.
  Outbox delivery is at least once; consumers deduplicate durably.
- Return against the original issue. Its original selling price is preserved,
  including if later catalogue prices change. More than the issued outstanding
  quantity is rejected.
- A finalisation locks the job record, freezes its inventory gate, obtains the
  authoritative net usage and saves the invoice. Issues/returns after freezing
  are rejected. Other jobs and receipts continue normally.
- If a temporary PDF/S3/database failure occurs during finalisation, retry the
  same finalisation after restoring the dependency. The frozen gate keeps its
  snapshot stable. An operator recovery/unfreeze interface is a later feature;
  do not manually unfreeze a job that has an invoice.

PDF invoice fields currently use English/Latin labels. Non-ASCII customer and
vehicle invoice labels are rejected when creating the job, rather than silently
changing a customer's name. The web catalogue can display Unicode descriptions.
Multi-page PDF invoices preserve long parts lists and totals. Tax rules and
tax-invoice compliance are not implemented; configure real business billing
requirements before replacing the workshop's official billing process.

## Healthy operation

The initial operational targets are **proposed**, not measured achievements:

| Signal | Initial alert / investigation trigger |
| --- | --- |
| API error ratio | >5% server errors over 5 minutes |
| API latency | Track p95; establish a target after load tests |
| Model latency | Compare to a representative photo workload baseline |
| SQS oldest message | >120 seconds for 3 periods |
| DLQ visible messages | Any visible message |
| Pod restarts / readiness | Unexpected increase or missing replicas |
| Recognition corrections | Review wrong SKU/size/grade selections; never treat raw similarity as accuracy |
| Cache availability | Fallback continues; investigate sustained miss/error increases |

CloudWatch queue alarms and Alertmanager publish to the encrypted operations
SNS topic with scoped permissions. Confirm the owner email subscription and
verify firing/resolved alerts before enabling business traffic. Prometheus has
two replicas and seven-day local retention; Alertmanager has three replicas.
Grafana is a private single-instance UI with a persistent volume. These settings
are source configuration, not evidence of an achieved availability target. CloudWatch investigations can be added for AIOps;
no autonomous remediation is enabled in this milestone.

## Recovery drills

1. **Cache loss:** fail over or temporarily block the cache in a disposable environment, perform a receipt and image match, and
   confirm inventory remains correct. Restart Redis; it repopulates on misses.
2. **Duplicate command:** retry an unchanged receipt with its original key.
   Confirm one movement. Reuse the key with a changed quantity; expect 409.
3. **Queue consumer outage:** pause a consumer in a disposable lab, generate a
   stock issue and inspect pending projection/queue age. Restart it and confirm
   the allocation appears once.
4. **Invalid return:** try returning more than the original issue. Expect 409
   and unchanged shelf quantity.
5. **Model checksum mismatch:** deploy an intentionally wrong archive hash in
   a disposable environment. The init container must fail; readiness must not
   claim a healthy model.
6. **Rollback:** revert a reviewed GitOps image/model change. Check the old
   encoder uses its old versioned reference vectors. Keep API contracts and
   database migrations backward compatible through the rollback window.

## Data and credentials

RDS backups and S3 versioning are configured. Execute an actual restore into a
separate environment and compare stock balances, invoices and reference counts
before declaring an RPO/RTO. Never use `docker compose down -v` on records you
need. The local activity table shows the latest 200 movements; the database
retains the ledger. A paginated long-term reporting UI is a later feature.

Private internal APIs use separate inventory-read, inventory-control and
capture-verification capabilities, separate from metrics tokens, staff Cognito
tokens and AWS IAM identities. Vision is not given the inventory-control
capability. Consider service-bound short-lived identities or mTLS for stronger
multi-team isolation. Secrets injected as pod
environment values require coordinated pod restarts after rotation; External
Secrets refresh does not restart existing processes. RDS master-secret rotation
is managed by AWS; application-role password rotation requires updating the
database role and restarting the relevant workloads in a controlled sequence.

Collect only the tray region, keep the camera workstation/spool private, and
define retention for raw photos. Hardware counting/direction thresholds need
real tests. The software cannot infer quantities inside bags, identify obscured
labels or measure the remaining oil in an opaque container.
