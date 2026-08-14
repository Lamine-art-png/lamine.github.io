# AGRO-AI Platform API — CLI

`agroai` is the first-class command-line interface for the AGRO-AI Platform API. It is built on the official Python SDK, not on shelling out to `curl`.

## Public installation

The CLI can be installed directly from the public AGRO-AI repository without waiting for a package-registry release.

macOS / Linux:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

The installer requires Git and Python 3.10 or newer. It uses `pipx` when available. Otherwise it creates an isolated virtual environment under `~/.local/share/agroai-cli` and links the executable into `~/.local/bin`. It does not require `sudo`.

For a reproducible source pin, set `AGROAI_CLI_REF` to a Git commit SHA before running the installer:

```bash
AGROAI_CLI_REF=<commit-sha> curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

PyPI, npm and Homebrew publication remain separate distribution channels. Do not advertise registry installation until namespace ownership and release credentials are verified.

## Authentication model

The CLI deliberately separates human control-plane credentials from machine API keys.

### Human control plane

Run:

```bash
agroai login
```

The CLI starts a short-lived browser/device authorization flow against the first-party AGRO-AI account system. After the user signs in and approves the device, the CLI receives an organization-bound human session. The session is stored in the operating-system keychain when available, with a `0600` local-file fallback. No API key is used as human identity and no permanent client secret is embedded in the CLI.

Run:

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

TEST and LIVE credentials remain separate. Public self-service creates TEST credentials only. LIVE remains a separately reviewed capability.

## Commands

```bash
agroai --version
agroai login
agroai logout

agroai projects list
agroai projects create --name "My integration" --environment test

agroai keys list
agroai keys create --service-account-id <id> --name primary --scope fields:read
agroai keys rotate <key-id> --overlap-minutes 0
agroai keys revoke <key-id>

agroai doctor
agroai me
agroai usage
agroai fields list [--limit N] [--cursor C] [--all]
agroai fields get <field-id>
agroai fields create --name "North block" --crop almond --area-hectares 12.5
agroai providers list
agroai providers status <provider>
agroai jobs get <job-id>
agroai webhooks list
```

Add `--json` for machine-readable output.

## Terminal-first TEST journey

After public TEST self-service is activated:

```bash
# 1. Install the CLI.
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh

# 2. Sign in with the verified AGRO-AI account in the browser.
agroai login

# 3. Create a TEST project from the terminal.
agroai projects create --name "First AGRO-AI integration" --environment test

# 4. Create a service account in the Developer Console or API, then mint a scoped key.
agroai keys create --service-account-id <service-account-id> --name local-dev --scope fields:read --scope fields:write

# 5. Export the one-time plaintext key and call the data plane.
export AGROAI_API_KEY="agro_test_..."
agroai doctor
agroai fields list --json
```

The TEST path uses deterministic agricultural test data and does not require a salesperson, live provider contract, real farm connection, billing activation, production webhooks or physical execution.

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
- API-key plaintext is returned only by deliberate key creation/rotation responses.
- Use the smallest scopes required for the integration.
- Rotate or revoke a key immediately if it is exposed.
