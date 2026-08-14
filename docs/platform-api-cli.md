# AGRO-AI Platform API — CLI

`agroai` is the first-class command-line interface for the AGRO-AI Platform API. It is built on the official Python SDK, not on shelling out to `curl`.

## Public installation

macOS / Linux:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

The installer requires Git and Python 3.10 or newer. It uses `pipx` when available. Otherwise it creates an isolated virtual environment under `~/.local/share/agroai-cli` and links the executable into `~/.local/bin`. It does not require `sudo`.

For a reproducible source pin:

```bash
AGROAI_CLI_REF=<commit-sha> curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

PyPI, npm and Homebrew are separate distribution channels. Do not advertise a registry install until namespace ownership and release credentials are verified.

## Authentication model

The CLI separates human control-plane credentials from machine API keys.

### Human control plane

```bash
agroai login
```

The CLI starts a short-lived first-party browser/device authorization flow. After the user signs in and approves the device, the CLI receives an organization-bound human session. The session is stored in the operating-system keychain when available, with a `0600` local-file fallback. A machine API key is never treated as human identity.

```bash
agroai logout
```

Logout revokes the CLI session server-side before removing the local credential.

### Machine data plane

Project API calls use a scoped `agro_test_` or `agro_live_` key:

```bash
export AGROAI_API_KEY="agro_test_..."
agroai doctor
```

Public self-service creates TEST credentials only. LIVE remains separately reviewed.

## Fastest TEST quickstart

Once public TEST activation is enabled, a new developer can go from installation to a working TEST key entirely from the terminal plus the browser sign-in/approval step:

```bash
# 1. Install.
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh

# 2. Sign in. The browser opens for first-party authentication and device approval.
agroai login

# 3. Create the complete safe TEST chain: project -> service account -> one-time key.
agroai --json bootstrap --name "First AGRO-AI integration"

# 4. Copy the one-time api_key value returned by bootstrap.
export AGROAI_API_KEY="agro_test_..."

# 5. Verify the data plane and use deterministic agricultural TEST resources.
agroai doctor
agroai fields list --json
agroai usage --json
```

`bootstrap` never requests a LIVE project, provider-write permission, or physical-action scope. Its default scope set is limited to the normal TEST quickstart operations. The API key is printed once because the backend deliberately returns new key material once; the CLI does not save it to disk.

## Control-plane commands

```bash
agroai projects list
agroai projects create --name "My integration" --environment test

agroai service-accounts list [--project-id <id>]
agroai service-accounts create \
  --project-id <id> \
  --name local-dev \
  --scope fields:read \
  --scope fields:write

agroai keys list
agroai keys create --service-account-id <id> --name primary --scope fields:read
agroai keys rotate <key-id> --overlap-minutes 0
agroai keys revoke <key-id>

agroai webhooks list
```

These commands require the human session created by `agroai login`.

## Data-plane commands

```bash
agroai doctor
agroai me
agroai usage
agroai fields list [--limit N] [--cursor C] [--all]
agroai fields get <field-id>
agroai fields create --name "North block" --crop almond --area-hectares 12.5
agroai providers list
agroai providers status <provider>
agroai jobs get <job-id>
```

These commands require the appropriate project API-key scopes. Add `--json` for machine-readable output.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | success |
| 1 | generic error |
| 2 | usage error |
| 3 | authentication or authorization error |
| 4 | rate limited |
| 5 | not found |
| 6 | configuration or connectivity error |

## Security notes

- The CLI never prints a stored human session token.
- `doctor` displays only a short API-key prefix and derived TEST/LIVE environment.
- API-key plaintext is returned only by deliberate key creation or rotation responses.
- `bootstrap` deliberately prints the newly created TEST key once and never persists it.
- Use the smallest scopes required for the integration.
- Rotate or revoke a key immediately if it is exposed.
- TEST access does not enable real provider credentials, production customer data, production webhooks, billing, LIVE projects, or physical execution.
