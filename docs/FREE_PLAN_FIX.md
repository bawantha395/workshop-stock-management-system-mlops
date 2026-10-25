# Resume after the IAM OIDC provider denial

For `bawantha395/workshop-stock-management-system-mlops`, AWS account
`721274598579`, Sydney `ap-southeast-2`.

The account's Free-plan organization policy denied
`iam:ListOpenIDConnectProviders`. AWS's published Free-plan policy denies
`iam:*Provider*`, including creating the provider. The previous OIDC-only
bootstrap cannot finish under that restriction.

## 1. Update the same repository

Copy this updated project's contents into your existing local Git checkout,
including `.github/`, then commit and push. Keep your existing repository
history and six main-only GitHub environments.

Wait for all eight **Validate platform** jobs to pass for the new commit.

## 2. Run the corrected CloudShell bootstrap

```bash
export AWS_REGION=ap-southeast-2
export AWS_DEFAULT_REGION=ap-southeast-2
cd ~/workshop-stock-management-system-mlops
git pull --ff-only

python3 scripts/bootstrap_pipeline.py \
  --repository bawantha395/workshop-stock-management-system-mlops \
  --project-name stocklane-dev \
  --environment dev \
  --capacity-profile demo \
  --auth-mode access-key \
  --region ap-southeast-2 \
  --expected-account 721274598579 \
  --hosted-zone-id Z035879924YQHJ4M5G2A3 \
  --api-domain api.stocklane.bawantha-rathnayake.tech \
  --execute \
  --create-access-key
```

Enter your budget-alert email locally. This creates the pipeline trust stack
and restricted CI user, then writes the user's first key privately. Its only
identity permission is to assume six exact project pipeline roles. It has no
console login. The setup does not change the account plan or SCPs.

IAM user/key creation and role assumption must be permitted in the account.
If AWS denies another API, retain the error and resolve its policy with the
account owner/AWS Support before proceeding.

## 3. Copy the generated GitHub settings

```bash
cat deploy/generated/github-setup.json
cat deploy/generated/github-credentials.json
```

In GitHub **Settings → Secrets and variables → Actions**:

| Location | Add |
| --- | --- |
| Variables | Every entry under `repository_variables`; `AWS_AUTH_MODE` must be `access-key`. |
| Secret `TFVARS_JSON` | The object under `repository_secret.value` in `github-setup.json`. |
| Secret `AWS_ACCESS_KEY_ID` | The matching value under `repository_secrets` in `github-credentials.json`. |
| Secret `AWS_SECRET_ACCESS_KEY` | The matching value under `repository_secrets` in `github-credentials.json`. |

Keep the credentials file private. The helper does not print key values;
the `cat` command is solely for copying them directly into GitHub secrets.
No session token is needed.

## 4. Resume the pipeline

Run **Bootstrap Terraform backend** on `main`. After it succeeds, run
**Plan AWS infrastructure**. Review the plan before using the apply workflow.

After the first successful backend run, remove the local key handoff file:

```bash
rm deploy/generated/github-credentials.json
```

On later bootstrap runs omit `--create-access-key`. The helper refuses duplicate
keys or an existing handoff file. Rotate keys deliberately through the operator
identity; the CI user cannot manage its own credentials. AWS does not enforce
GitHub environment claims in key mode, so protect main, workflow changes and
the GitHub environments. See [PIPELINE_SETUP.md](PIPELINE_SETUP.md) for role,
capacity, rotation and deployment details.
