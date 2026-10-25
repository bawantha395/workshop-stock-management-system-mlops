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
`overlays/dev`, `overlays/test`, `overlays/uat` or `overlays/production`.
The Argo CD root Applications live in `argocd/root/`.

Run `python scripts/validate_kustomize.py` from the repository root after
installing the script requirements and pinned Kustomize tool as described in
[docs/KUSTOMIZE.md](../../docs/KUSTOMIZE.md). This validates the source without
applying resources to a cluster. Configured releases also validate with
`--configured` to reject unresolved account values and mutable application
images.

The checked-in templates need account-specific release rendering before live
deployment. Follow [docs/AWS_DEPLOYMENT.md](../../docs/AWS_DEPLOYMENT.md) for
bootstrap order; applying individual folders out of order can fail because
their CRDs or controllers are not ready.
