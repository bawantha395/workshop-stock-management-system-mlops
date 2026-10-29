# Kubernetes manifests

| Directory | What it deploys |
| --- | --- |
| `apps/` | Inventory, workshop, vision, shared application resources and model-index Job. |
| `platform/` | AWS Load Balancer Controller, cert-manager, External Secrets, metrics-server, StorageClass and CloudWatch logging. |
| `argocd/` | Argo CD installation, projects and root/child Applications. |
| `monitoring-operator/` | Prometheus Operator and its CRDs. |
| `monitoring/` | Prometheus, Alertmanager, Grafana, kube-state-metrics, dashboards and alert rules. |
| `bootstrap/` | Database bootstrap Job and configuration. |
| `vendor/` | Pinned upstream resources and licenses. |
| `upstream.lock.json` | Source versions and checksums for vendored resources. |
| `toolchain.lock.json` | Pinned tool downloads and checksums. |

Shared resources belong in `base/`; per-environment patches belong in
`overlays/dev`, `overlays/staging` or `overlays/prod` (same names as the
Terraform environments).
The Argo CD root Applications live in `argocd/root/`.

Run `python scripts/validate_kustomize.py` from the repository root after
installing the script requirements and pinned Kustomize tool as described in
[docs/KUSTOMIZE.md](../../docs/KUSTOMIZE.md). This validates the source without
applying resources to a cluster. Configured releases also validate with
`--configured` to reject unresolved account values and mutable application
images.

The checked-in templates need account-specific release rendering before live
deployment. The **Deploy environment** pipeline does this and the bootstrap in
the right order ([docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md)); applying
individual folders out of order can fail because their CRDs or controllers are
not ready.

Third-party components (Argo CD, cert-manager, External Secrets, the AWS Load
Balancer Controller, Prometheus Operator, metrics-server, kube-state-metrics)
are **vendored, version-pinned YAML** rather than Helm charts. Every file's
SHA256 is locked in `upstream.lock.json`, so a release can only ever deploy
reviewed bytes, and the private CodeBuild runner needs no access to chart
repositories. Upgrading one is a reviewed pull request that updates the
vendored files and the lock.

The metrics-server high-availability import declares an obsolete
`policy/v1beta1` PodDisruptionBudget. A shared Kustomize patch in
`platform/base/kustomization.yaml` renders it as `policy/v1` for every
environment, keeping the explicit pod selector and upstream checksums.

Validation rejects obsolete budget APIs even without kubeconform. When
kubeconform is installed, every ordinary built-in resource must have a schema;
missing schemas fail. CRD definitions must match the pinned API/spec, and custom
resources are validated separately against their served CRD schemas.
