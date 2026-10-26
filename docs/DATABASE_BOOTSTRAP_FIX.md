# PostgreSQL Schema Ownership Recovery

## Confirmed Failure

The supplied database Job logs show two Pods exiting with status 1 while running
`CREATE SCHEMA IF NOT EXISTS inventory AUTHORIZATION inventory`:

```text
psycopg.errors.InsufficientPrivilege: must be able to SET ROLE "inventory"
```

Image pull, credential retrieval, and the PostgreSQL TLS connection succeeded.
The Job reached its retry limit after two attempts. The later 300-second
`kubectl wait` timeout was a consequence of waiting only for completion.

RDS PostgreSQL administrators are not PostgreSQL superusers. PostgreSQL 17
requires the ability to SET ROLE to the intended schema owner, while the
automatic membership given to a role creator has SET FALSE. CREATEROLE alone
does not satisfy schema ownership checks.

References:

- https://www.postgresql.org/docs/17/sql-createschema.html
- https://www.postgresql.org/docs/17/role-attributes.html
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html

## Source Correction

`scripts/bootstrap_database.py` grants the current bootstrap administrator
temporary SET membership in a service role before creating its schema. Each
service runs in a transaction. The script removes only its own temporary grant,
or restores its previous SET option, before committing. Existing memberships
and administrative grants are retained. A failed service transaction rolls back
its password, role, schema, and temporary membership changes together.

The service remains the schema owner. Runtime users receive no administrative
role or access to another service's schema. An existing schema with a different
owner causes an explicit failure rather than silently changing its ownership.
Successful reruns retain existing application tables and rows.

The AWS entry point still fetches passwords from Secrets Manager in memory and
verifies the RDS TLS certificate. It prints service progress without passwords.
No Terraform, AWS IAM, RDS instance, or Kubernetes resource change is required
for this SQL correction.

The release eligibility filter now includes `scripts/bootstrap_database.py`:
changing this file must rebuild the operations container, because the running
Job uses the copy inside its immutable image.

## Files To Upload

Copy these files from the updated archive into the existing repository after
syncing main. Preserve any unrelated local changes.

```text
scripts/bootstrap_database.py
scripts/workflow_eligibility.py
.github/workflows/ci.yml
tests/test_database_bootstrap.py
tests/test_pipeline.py
docs/DATABASE_BOOTSTRAP_FIX.md
docs/VALIDATION.md
```

## Release And Retry

1. Commit and push the correction to main. Wait for **Validate platform**,
   including the new **database-bootstrap** test job, to succeed.
2. The successful main validation selects **Prepare AWS release** automatically
   because the database script is included in the application filter. If no
   release starts, run **Prepare AWS release** on main manually once.
3. Review and merge the new GitOps release pull request. Confirm that
   `deploy/kubernetes/bootstrap/overlays/dev/kustomization.yaml` has the newly
   built operations image digest. The failed image's digest was
   `sha256:7a7dbc0ad201303f45c15a4abc82320355f9a5427f3a7594a10c2e8e6a943788`.
4. Once the GitOps change is on main and previous bootstrap runs have finished,
   remove the failed Kubernetes Job in the VPC CloudShell:

   ```bash
   kubectl -n stocklane-dev delete job database-bootstrap \
     --wait=true --timeout=60s
   ```

   This removes the failed Job and its Pods. The RDS database and its existing
   users, schemas, and records remain for recovery by the fixed script.

5. Start a new **Bootstrap EKS platform** run on main. A new workflow run selects
   current source; re-running an older workflow retains its older source commit.
   The bootstrap creates the Job with the newly reviewed image. Look for
   `Initialised service schema:` messages and Job completion before continuing
   to the Argo CD application checks.

An unchanged failed Job stops bootstrap intentionally. Retrying the platform
before replacing the operations image and clearing that failed Job does not
apply the source correction. No additional Terraform apply is needed here.

## Verification

The existing 123 targeted pipeline, Kustomize, and delivery checks passed with
two unrelated training tests deselected. Workflow lint, Python compilation, and
diff whitespace checks passed.

Five new integration tests use a non-superuser CREATEROLE administrator. They
reproduce the old ownership error, recover the partially created role, check
all service schema owners and isolation, retain existing application data on
rerun, preserve existing membership options, and roll back a wrong-owner
failure. The new GitHub CI job supplies a real PostgreSQL 17 service. This build
environment could not start its local PostgreSQL test server because creation
of the server's operating-system user was unavailable; these five integration
tests still need to pass in GitHub. No live AWS database recovery was executed
from this build environment.
