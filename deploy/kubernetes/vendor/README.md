# Pinned upstream Kubernetes resources

These are upstream installation resources split into one Kubernetes object per
file. `../upstream.lock.json` records their release versions, download URLs,
source SHA256 values and per-file hashes. CI rejects changes that do not match
the reviewed lock. Updates require an explicit vendor/version review.

Argo CD, Prometheus Operator, cert-manager, AWS Load Balancer Controller, metrics
server and kube-state-metrics come from their projects' published manifests.
External Secrets Operator is a one-time export of its official 2.14.0 upstream
chart. Its source chart digest and export provenance are recorded in the lock;
only the exported YAML is committed. No Helm binary or chart is required by
this project's deployment/bootstrap workflows.

The split resources retain upstream definitions and receive Argo CD sync-wave
annotations. Kustomize applies namespace/configuration patches outside this
vendor directory. Read the upstream licenses in `licenses/`.
