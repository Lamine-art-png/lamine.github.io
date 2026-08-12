# AGRO-AI Platform API — CLI

`agroai` is a first-class command-line interface built directly on the official
Python SDK (`agroai_platform.client`). It is not a wrapper around `curl`.

## Status

- **Implemented and tested** (offline contract tests in `sdk/python/tests/test_cli.py`).
- **Not yet published** to PyPI/Homebrew. Do not advertise `pipx install agroai`
  or `brew install agroai` until the package is actually released (see
  `docs/platform-api-production-readiness.md` release gates). Until then, run it
  from a checkout:

  ```bash
  cd sdk/python
  pip install -e .        # registers the `agroai` entry point
  # or, without installing:
  PYTHONPATH=. python -m agroai_platform.cli --help
  ```

## Authentication model

The CLI deliberately separates the two credential types the platform uses:

| Action type | Credential | How |
|-------------|-----------|-----|
| Data-plane (`me`, `fields`, `usage`, `providers`, `jobs`) | machine API key | `AGROAI_API_KEY=agro_test_…` (or `--api-key`) |
| Human control-plane (create projects/keys) | human session | **Developer Console** — a browser/device sign-in flow for the CLI is a tracked follow-up |

`agroai login` does **not** fake a human session using a machine key. It reports
how to obtain access and exits non-zero. This preserves the security boundary in
§6/§29 of the engineering brief.

## Configuration

| Variable / flag | Default | Meaning |
|-----------------|---------|---------|
| `AGROAI_API_KEY` / `--api-key` | (required for data ops) | `agro_test_` or `agro_live_` key |
| `AGROAI_BASE_URL` / `--base-url` | `https://api.agroai-pilot.com` | API base |
| `--timeout` | `20.0` | request timeout (seconds) |
| `--json` | off | machine-readable JSON output |

The CLI never prints the full API key. `doctor` shows only a short prefix and
the derived environment (`test`/`live`).

## Commands

```bash
agroai --version
agroai doctor                     # config + connectivity diagnostics
agroai me                         # authenticated principal
agroai usage                      # usage summary
agroai fields list [--limit N] [--cursor C] [--all]
agroai fields get <field-id>
agroai providers list
agroai providers status <provider>
agroai jobs get <job-id>
```

Add `--json` to any command for automation.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | generic error |
| 2 | usage error (argparse) |
| 3 | authentication/authorization error (401/403) |
| 4 | rate limited (429) |
| 5 | not found (404) |
| 6 | configuration or connectivity error (e.g. `AGROAI_API_KEY` unset) |

## Terminal-first quickstart

```bash
export AGROAI_API_KEY="agro_test_..."   # from the Developer Console (test project)
agroai doctor                            # verify connectivity
agroai fields list --json                # deterministic synthetic sandbox data
```

This path requires no salesperson, provider contract, or production farm
connection (§20). Live keys (`agro_live_`) are gated separately (§4/§14).
