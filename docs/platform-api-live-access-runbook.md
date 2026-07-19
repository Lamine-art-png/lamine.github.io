# Platform API live-access runbook

Live access is always manually reviewed. Automatic approval remains disabled.

Review organization verification, active enrollment, intended production use,
users/volume/peak rate, data categories, providers, geography, security and
incident contacts, compliance, CIDR strategy, webhooks, retention, billing plan,
and target date. Record conditions and expiry.

Approval only adds `live` to an eligible enrollment. Project creation still
requires the live-project flag, eligible subscription/contract, explicit live
environment, active approval, Platform API readiness, provider truth, and all
security dependencies. Suspension invalidates live key authentication on the
next request. No provider write or physical action is granted.
