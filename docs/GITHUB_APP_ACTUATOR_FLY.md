# GitHub App actuator on Fly

This runbook enables the existing `github.*` actuator family in the live
Fly apps. The app code already supports the actuator; the remaining work
is one GitHub-owner approval flow plus non-secret config IDs and a Fly
secret.

## Current target

- Fixture repo: `jaydenpiao/quorum-actuator-fixtures`
- Smoke issue: `jaydenpiao/quorum-actuator-fixtures#1`
- Safe smoke actions: `github.comment_issue`, then `github.add_labels`
- Label prepared in the fixture repo: `quorum-smoke`

Keep the first live proof on the fixture repo. Do not point the actuator
at `jaydenpiao/quorum` until the fixture path has executed through
Quorum's proposal, vote, execute, and rollback flow.

## 1. Register and install the GitHub App

Run:

```bash
uv run python -m apps.api.app.tools.bootstrap_github_app \
  --owner jaydenpiao \
  --repo quorum-actuator-fixtures \
  --output json
```

The helper opens GitHub's manifest flow in a browser. Approve the App
creation, then install it on **only**
`jaydenpiao/quorum-actuator-fixtures`.

The helper captures the one-time manifest callback locally, exchanges it
for the App metadata, stores a base64-encoded PEM private key in macOS
Keychain under `quorum-github-app-private-key-b64`, and prints only
non-secret values:

```json
{
  "app_id": 123456,
  "app_slug": "quorum-actuator",
  "fly_secret_name": "QUORUM_GITHUB_APP_PRIVATE_KEY_B64",
  "installation_id": 78910,
  "keychain_service": "quorum-github-app-private-key-b64",
  "target_repository": "jaydenpiao/quorum-actuator-fixtures"
}
```

If the helper times out after App creation but before installation,
open the printed `install_url`, install the App on the fixture repo, and
rerun the helper only if you need a fresh PEM. GitHub manifest callback
codes expire after one hour.

## 2. Commit the non-secret config IDs

Update `config/github.yaml`:

```yaml
app:
  app_id: <app_id>
  installations:
    - owner: jaydenpiao
      repo: quorum-actuator-fixtures
      installation_id: <installation_id>
```

These IDs are not secrets, but they are deploy-specific runtime config.
Land the change through a normal PR and wait for image-push to publish
the new image.

## 3. Deploy staging with the config image

Deploy the new staging image digest produced by image-push. Use the
manifest-list digest from the GitHub Actions job summary:

```bash
FLY_API_TOKEN="$(security find-generic-password -a "$USER" -s quorum-fly-api-token -w)"
fly deploy \
  --app quorum-staging \
  --image registry.fly.io/quorum-staging@sha256:<digest> \
  --strategy immediate \
  --ha=false \
  --yes
```

## 4. Set the staging private-key secret

Read the base64 PEM from Keychain into the Fly secret. Keep the
assignment and `fly` invocation as separate shell statements so
expansion is not empty:

```bash
GITHUB_APP_PEM_B64="$(security find-generic-password -a "$USER" -s quorum-github-app-private-key-b64 -w)"
FLY_API_TOKEN="$(security find-generic-password -a "$USER" -s quorum-fly-api-token -w)"
fly secrets set QUORUM_GITHUB_APP_PRIVATE_KEY_B64="$GITHUB_APP_PEM_B64" --app quorum-staging
```

Re-check staging:

```bash
curl -fsS https://quorum-staging.fly.dev/readiness
curl -fsS https://quorum-staging.fly.dev/api/v1/health
curl -fsS https://quorum-staging.fly.dev/metrics >/dev/null
```

## 5. Smoke through Quorum

Create an intent and proposal against fixture issue #1, vote it through,
execute it, and verify the fixture repo changed. Start with
`github.comment_issue` because rollback can delete the comment.

Payload shape:

```json
{
  "action_type": "github.comment_issue",
  "target": "github:jaydenpiao/quorum-actuator-fixtures#1",
  "payload": {
    "owner": "jaydenpiao",
    "repo": "quorum-actuator-fixtures",
    "issue_number": 1,
    "body": "Quorum staging GitHub actuator smoke."
  },
  "risk": "low",
  "environment": "staging",
  "health_checks": [],
  "rollback_steps": ["Delete the created issue comment via actuator rollback."]
}
```

Expected Quorum event chain:

- `intent_created`
- `proposal_created`
- `policy_evaluated`
- at least two `proposal_voted`
- `proposal_approved`
- `execution_started`
- `execution_succeeded`

Only after staging proves the fixture path should prod receive
`QUORUM_GITHUB_APP_PRIVATE_KEY_B64`. Keep prod installed on the fixture
repo until a separate PR switches `config/github.yaml` to a production
target.
