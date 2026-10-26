# Resume EKS platform bootstrap after the metrics-server API error

The failed build was `stocklane-dev-platform-bootstrap:6acc8a5f-74e7-4933-9faa-8cf9309d1629`.
Its first actionable error was:

```text
no matches for kind "PodDisruptionBudget" in version "policy/v1beta1"
```

PodDisruptionBudget is a built-in Kubernetes resource. Kubernetes stopped serving
its `policy/v1beta1` API in version 1.25; this cluster uses Kubernetes 1.35.
The supported API is `policy/v1`. The accompanying CRD hint is generic kubectl
output and does not identify a missing PDB custom-resource definition.

## What changed

The shared platform Kustomization now applies a JSON patch to the metrics-server
budget's `apiVersion`. All four environments inherit it. The budget still uses
`minAvailable: 1` and the nonempty selector `k8s-app: metrics-server`; the
metrics APIService retains its separate `metrics.k8s.io/v1beta1` endpoint.
Pinned vendor files and their checksum lock remain intact.

The validation gap was kubeconform's global `-ignore-missing-schemas` option:
an unavailable schema for a removed API could be silently skipped. The checker
now rejects beta PDBs even when kubeconform is absent. With kubeconform installed,
ordinary built-in resources require schemas. CRD definitions, whose schemas are
not supplied by this catalog, must exactly match the checksum-pinned API/spec;
custom resources are checked against the vendored served CRD schemas.
CodeBuild also validates the complete configured platform before contacting
the Kubernetes API.

## Update the existing repository

This update is based on main commit
`9aa71910eb625fb24bcda56a869248d7b9c75bff`, including merged release PR #10.
The archive retains that release's image digests, model reference and frontend
manifest. Apply the changed files to the same repository:

- `deploy/kubernetes/platform/base/kustomization.yaml`
- `scripts/validate_kustomize.py`
- `scripts/bootstrap_eks.py`
- `tests/test_kustomize.py`

The archive also contains this guide, the updated Kubernetes README and
validation notes. Commit and push the update to `main` through your usual Git
or GitHub upload workflow.

## Run the corrected platform workflow

1. Wait for **Validate platform** on the new main commit.
2. A successful main push containing the platform patch automatically selects
   **Bootstrap EKS platform**. Follow that new run if it starts.
3. To start it manually, open **Actions → Bootstrap EKS platform → Run workflow
   → main**. A new run selects the corrected commit; GitHub's **Re-run jobs**
   operation keeps the old run's commit.
4. The bootstrap reapplies the existing controller resources and creates the
   supported budget, then continues its rollout/readiness checks.
5. After the platform succeeds, **Publish reviewed frontend** is dispatched.

This is a Kubernetes source update. Infrastructure provisioning and application
image builds are already completed; this platform patch is delivered through
the platform workflow.

## Validation evidence

- 123 targeted tests passed; two training tests were deselected.
- All four environments render a `policy/v1` metrics-server budget with its
  original selector and availability setting.
- Tests reject the obsolete budget API without relying on a schema download.
- Tests allow pinned CRD specs with metadata patches and reject changed or
  unreviewed CRD specs.
- Strict kubeconform validation checks built-in schemas separately from custom
  resources; results are recorded in VALIDATION.md.

The live AWS retry remains to be run with this new commit.

Reference: [Kubernetes deprecated API migration guide](https://kubernetes.io/docs/reference/using-api/deprecation-guide/#poddisruptionbudget-v125).
