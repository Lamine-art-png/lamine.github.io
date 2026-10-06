# AGRO-AI agent security rules

These rules apply to every coding agent, AI assistant, automation, and human-assisted
agent working in this repository. Security takes priority over convenience and
visual-proof workflows.

## Never publish private work artifacts

- Never create a public GitHub repository, public gist, public release asset,
  paste, image host, or adjacent repository to make a screenshot or recording
  visible to a reviewer.
- Never use `gitshot` or any equivalent tool that uploads screenshots,
  recordings, logs, traces, browser state, or generated artifacts to a public
  location.
- Never upload screenshots or screen recordings that may contain customer data,
  billing data, credentials, API keys, internal dashboards, unreleased product
  surfaces, infrastructure identifiers, or authenticated browser state.
- If visual proof is requested, keep the artifact local. Report the local path
  and a text summary. Only publish it when a human explicitly names an approved
  private destination.

## Secrets and credentials

- Never commit, print, echo, log, screenshot, paste, or expose plaintext secrets.
- Read credentials only from approved secret stores or environment variables.
- Never copy a production secret into a test, fixture, example, notebook,
  workflow output, PR body, issue, or documentation.
- If a credential appears in source control, logs, screenshots, chat, or any
  public location, treat it as compromised immediately: revoke/rotate it first,
  then remove the exposed material.
- Run `python agroai_api/scripts/scan_repository_secrets.py` before committing
  any change that touches authentication, billing, providers, deployment,
  infrastructure, workflows, or configuration.

## Repository and GitHub behavior

- Do not change repository visibility, create repositories, create gists, publish
  release assets, or enable public hosting as a workaround.
- Do not force-push, rewrite history, or delete security evidence unless a human
  explicitly authorizes the exact remediation.
- Do not add `.env`, Terraform state, generated task definitions, notebooks
  with outputs, browser profiles, cookie stores, or credential-bearing exports.
- Do not place sensitive values in GitHub Actions command lines or outputs.
  Reference GitHub secrets through environment variables and keep shell tracing
  disabled around secret-bearing commands.

## Customer and production data

- Use synthetic or sanitized data for tests and screenshots.
- Customer records, tenant identifiers, private agronomic data, billing data,
  connector payloads, tokens, transcripts, and private media must remain in
  approved production systems and private evidence stores.
- Logs and diagnostics must redact authorization headers, cookies, tokens,
  passwords, webhook secrets, provider credentials, and customer payloads.

When a requested task conflicts with these rules, stop the risky step and choose
the private, least-privilege alternative.
