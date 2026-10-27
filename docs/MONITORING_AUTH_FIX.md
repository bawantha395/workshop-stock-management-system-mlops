# Monitoring Authentication and Grafana Provisioning Correction

## Confirmed observations

The Grafana container can query the Prometheus API. Vision, Forecast, Grafana and
kube-state-metrics scrape successfully. Inventory and Workshop metrics return
HTTP 401. The Grafana dashboard separately reports `Datasource prometheus was
not found`.

These are separate authentication and data-source provisioning failures.

## Source changes

The Java resource-server resolver leaves the exact `/actuator/prometheus`
endpoint to the existing constant-time internal-token validator. Cognito JWT
validation remains active for application APIs. This does not make metrics public.

The Grafana configuration explicitly names UID `prometheus`, organization 1 and
the internal Prometheus URL. `GF_PATHS_PROVISIONING` selects the mounted directory.
The release renderer hashes data-source and dashboard-provider configuration
into a pod-template annotation, so a configuration change triggers a rollout.
Separate ConfigMap and Deployment YAML files are retained.

Tests exercise the real cloud-mode filter chain with a local signed JWT issuer.
They verify valid/invalid scrape tokens, API isolation, JWT client/expiry checks
and owner-role enforcement. Kubernetes tests verify provisioning and configuration
rollout/rollback across all four environment overlays.

Preparation validation: full Maven verify passed with 36 Java tests, including
10 cloud-mode security tests. The selected monitoring, domain and Kustomize
suite passed 28 tests. The valid-token regression was reproduced as HTTP 401
against the original SecurityConfig before running the fixed tests. These are
local verification results, not a claim that the live AWS release has completed.

## Deploy through the existing release process

1. Update your local checkout to the current main branch.
2. Apply the companion patch with `git apply --check` before `git apply`.
3. Review and commit the changes, then push them to your repository.
4. Pass **Validate platform**.
5. Complete **Prepare AWS release**, or use its already triggered run.
6. Review and merge the generated GitOps release PR.
7. Complete **Bootstrap EKS platform** and inspect the child Applications.

New Java images are required. Uploading Java source alone does not change a live
pod. The monitoring manifests also need to reach the live monitoring Application.
Grafana uses a Recreate strategy, so its rollout briefly interrupts that dashboard
while retaining its existing PVC.

## Verify the deployed result

```bash
aws eks update-kubeconfig --region ap-southeast-2 --name stocklane-dev
kubectl -n stocklane-dev rollout status deployment/inventory --timeout=180s
kubectl -n stocklane-dev rollout status deployment/workshop --timeout=180s
kubectl -n monitoring rollout status deployment/grafana --timeout=180s
kubectl -n argocd get applications
```

In Grafana, open **Connections > Data sources > Prometheus**. Verify its UID is
`prometheus`, run the data-source test, then use **Explore** with this expression:

```promql
up{namespace="stocklane-dev"}
```

Inventory, Workshop, Vision and Forecast should each show 1 after the next
successful scrapes. In the dashboard, select **Last 1 hour** and refresh. Create
ordinary test traffic through the UI and allow several scrapes for rate panels.
A series that has never had an event may still be absent; a missing data-source
error is a different failure.

If Java metrics still return 401, inspect token configuration without printing
the token values. If the Grafana UID is still missing, inspect the mounted
provisioning file and the new pod's startup logs. Do not remove metrics security
or create an unrelated dashboard data source with a random UID as the permanent fix.

## Important scope

The correction is source and Kubernetes configuration. The existing AWS platform
can be reused. It does not alter stock quantities or train an ML model. Runtime
success still requires the release and live checks above.
