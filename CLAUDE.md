# Claude Code security boundary

Before doing any work in this repository, read and obey `AGENTS.md`.

The following rules are non-negotiable:

- Never create a public repository, gist, release asset, image host, or other
  public location to make a private screenshot or recording reviewable.
- Never use `gitshot` or equivalent screenshot-upload tooling.
- Keep visual verification artifacts local unless a human explicitly names an
  approved private destination.
- Never print, echo, log, commit, screenshot, or paste credentials or customer
  data.
- Treat any credential that reaches Git history, logs, screenshots, chat, or a
  public location as compromised and require rotation/revocation.
- Do not bypass repository secret scanning or leak-guard checks.
- Do not change repository visibility or publish new GitHub resources as a
  workaround for missing tooling.

If a task asks for proof, provide text evidence, test output with secrets
redacted, or a local artifact path. Security outranks convenience.
