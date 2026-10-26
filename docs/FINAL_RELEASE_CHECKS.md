# Final release verification and scope

This package includes the earlier stock-only UX, permanent Inventory Service
network-policy selectors, optional Bedrock/SageMaker lifecycle code, custom app
and admin domains, owner stock analysis, daily usage export and a separate Forecast microservice with a SageMaker train/evaluate/publish workflow.

## Checks completed

- Frontend TypeScript/Vite build passed; live scanner is split into a deferred
  chunk so stock screens do not load the QR decoder immediately.
- All 10 frontend tests passed, including analysis date conversion and report values.
- Python vision/platform/domain/forecast suite passed: 180 tests, 5 integration skips.
- Terraform format and Python compilation checks passed.
- The actual StockAnalysis Java service was compiled with a checksum-verified
  Java 21 toolchain and tested against H2 in PostgreSQL compatibility mode with
  all inventory migrations. Historical/current balances, exclusive end boundaries,
  >200 movement rows, SKU/category/archive filters and Sri Lanka daily grouping passed.
- The actual ForecastHistory Java service passed an H2 migration-backed check of 120 complete Colombo days, zero filling after confirmation, censor masks, partial-day exclusion and ledger reconciliation.
- Additional Spring integration tests cover the same boundaries and OWNER access.
  The full Maven/Spring Boot suite could not complete here because this runtime's
  Maven proxy/dependency resolution was unavailable. Existing Java 21 GitHub CI
  must pass before deployment; do not treat the standalone check as full CI.

## Still requires your account/device

AWS trust update, reviewed Terraform plan/apply, ACM issuance and DNS publication,
Argo CD deployment, native phone camera/printing checks, paid Bedrock invocation,
and SageMaker training on reviewed real workshop images were not performed here.
Demand forecasting code, service and workflow are included; no workshop-trained forecast artifact or room-wide CCTV detector is included.

## Start in this order

1. Read CUSTOM_DOMAINS.md and synchronise main before uploading changes.
2. Pass Validate platform, including the inventory Java tests.
3. Update the existing pipeline trust for domain/certificate permissions.
4. Merge custom-domain/Bedrock keys into existing TFVARS_JSON; supply your actual
   HOME/OFFICE public IP/32 for admin_allowed_cidrs. Keep all other values intact.
5. Review/apply the new Terraform plan; prepare a release and merge its GitOps PR.
6. Deploy platform, then publish frontend. Test stock, reference photos and analysis.
7. Follow AI_MLOPS_RELEASE.md to collect/upload real images, train, review and promote.

STOCK_ANALYSIS.md explains current/past reports. DEMAND_FORECASTING.md explains the separate forecasting service and protected training/publish workflow. Run it after the ordinary reviewed deployment.

Forecast-specific checks also cover accepted ML on a synthetic trend, preserving a perfect weekday baseline, time-split hyperparameter isolation, stale projections, quantity rounding, owner-only access, and skipping paid training for insufficient history. Synthetic data is test-only. No real AWS model training or deployment was performed here.
