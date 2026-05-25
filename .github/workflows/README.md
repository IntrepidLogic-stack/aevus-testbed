# GitHub Actions workflows — Aevus

| File | Purpose | Trigger | Notes |
|---|---|---|---|
| `ci-cd.yml` | **Primary deploy pipeline.** Lints + syntax-checks Python; on push to `main` or `workflow_dispatch`, assumes the OIDC `il-github-actions-deploy` IAM role and runs `deploy.sh` on the EC2 host via SSM Run Command. Records a GitHub Deployment so the UI rocket icon works. | push to main, PR to main, manual | Active. Replaces the SSH-key approach. |
| `ci.yml` | **Heavy CI** — full pytest suite + security scan. Does NOT deploy. | push to main, PR to main | Independent of `ci-cd.yml`. A failure here will NOT block dashboard / docs deploys. |
| `secret-scan.yml` | Gitleaks scan for credentials accidentally committed. | push to main, PR to main | Independent. |
| `ci-cd.ssh.yml.bak` | **Disabled** — the pre-SSM deploy that used a stored SSH key. Kept as a `.bak` (no `.yml` extension → not picked up by Actions) for rollback if SSM ever has an outage. | none | Inactive — safe to delete once SSM is verified stable. |

## Manual deploy (operator override)

When CI is red for reasons orthogonal to the deploy (flaky test, lint debt on legacy code, dashboard-only change) you can force a deploy from the Actions UI:

1. Repo → **Actions** tab
2. Pick **CI/CD** in the left sidebar
3. **Run workflow** button (top right)
4. Branch: `main`
5. **Skip CI gate** input: `true` if you need to skip the lint gate
6. **Run workflow**

The deploy job will assume the OIDC role and run `deploy.sh` via SSM. Audit trail lands in CloudTrail under the `il-github-actions-deploy` role.

## Required AWS-side resources

The `ci-cd.yml` workflow assumes these exist:

| Resource | ARN / ID |
|---|---|
| IAM role | `arn:aws:iam::676433090238:role/il-github-actions-deploy` |
| EC2 instance | `i-017562fca3e3401a8` (SSM agent running, attached to an instance profile that allows `ssm:UpdateInstanceInformation`) |
| Trust policy on the role | Allows `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`, restricted to this repo (`IntrepidLogic-stack/aevus-testbed`) and main / fix branches |
| Role permissions | `ssm:SendCommand`, `ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation` on the target instance |

If any of these are missing, the `Configure AWS credentials (OIDC)` or `Deploy via SSM` step will fail with a clear error message — fix the AWS-side resource, then **Re-run failed jobs** from the Actions UI.

## When CI red blocks deploy

The `deploy` job's `if:` condition lets the manual workflow_dispatch path bypass CI:

```yaml
if: |
  always() &&
  (needs.ci.result == 'success' || needs.ci.result == 'skipped') &&
  (github.event_name == 'push' || github.event_name == 'workflow_dispatch') &&
  github.ref == 'refs/heads/main'
```

This is intentional — CI failures should be visible signal, but they shouldn't block legitimate hotfix deploys (a typo in a docstring shouldn't keep a critical dashboard fix from reaching prod). Use the `skip_ci` input judiciously.
