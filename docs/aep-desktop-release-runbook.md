# AGRO-AI Enterprise Portal Desktop Release Runbook

Status: pre-release engineering track. Public distribution is fail-closed until every release gate below is satisfied.

## Product contract

The desktop application is the AGRO-AI Enterprise Portal in a native desktop shell. It is not a fork of AEP and it does not create a second customer data model.

- Product name: `AGRO-AI Enterprise Portal`
- Application identifier: `com.agroai.enterprise`
- Supported public desktop targets: macOS and Windows
- Deep-link scheme: `agroai://open/<approved-route>`
- Production API: `https://api.agroai-pilot.com`
- Shared frontend: `figma-enterprise-v4`
- Native shell: Tauri 2

The desktop shell must preserve the same account, organization, operation, entitlement, evidence, decision, report, and audit boundaries as the web product.

## Security boundary

The native shell has a deliberately small capability set.

1. Native HTTP is scoped only to `https://api.agroai-pilot.com/**`.
2. No default filesystem capability is granted.
3. Deep links are accepted only for the configured `agroai` scheme and the frontend only routes `agroai://open/...` to an explicit AEP route allowlist.
4. External URLs opened by the native command are limited to `https`, `http`, and `mailto`.
5. External top-level navigation is refused inside the privileged desktop webview and is handed to the operating-system browser instead.
6. The desktop frontend runs under the Tauri CSP and the Windows production webview uses HTTPS scheme semantics.
7. The web PWA remains independent. Desktop builds do not widen backend browser CORS to a desktop-local origin.

## Build outputs

Internal CI produces unsigned candidate installers for QA only:

- macOS Apple Silicon bundle
- macOS Intel bundle
- Windows x64 NSIS/MSI bundle

Unsigned candidates must never be linked from the AGRO-AI website, sent to customers, or described as production releases.

## macOS production signing

A public macOS direct-download release requires an Apple Developer Program identity and notarization. Provision the protected GitHub release environment with the Apple signing/notarization credentials used by Tauri. At minimum the release operator must have:

- Developer ID Application certificate material
- certificate password
- signing identity
- Apple team ID
- notarization credentials through an Apple ID app-specific password or approved App Store Connect API credentials

Release evidence must prove:

- the `.app` is signed with the AGRO-AI Developer ID identity
- the DMG contains the signed app
- Apple notarization succeeds
- the notarization ticket is stapled where applicable
- Gatekeeper accepts the downloaded artifact on a clean supported Mac
- both Apple Silicon and Intel targets launch, sign in, reconnect, and uninstall cleanly

## Windows production signing

A public Windows release requires an organization code-signing identity. Prefer an EV/managed signing path or Microsoft Trusted Signing when available. If a PFX-based certificate is used, its secret material must live only in the protected GitHub release environment.

Release evidence must prove:

- the application executable is signed
- the NSIS installer is signed
- the MSI is signed when distributed
- Windows verifies the publisher identity
- the installer, upgrade, repair, and uninstall paths work on a clean Windows 11 machine
- WebView2 bootstrap behavior is verified

## Authentication hardening gate

The web AEP keeps its existing browser `localStorage` authentication path. The desktop runtime now intercepts only the `agroai_access_token` storage key and routes that credential to OS-protected storage through the native Rust process:

- macOS: Keychain-backed credential storage
- Windows: Windows Credential Manager-backed storage

The desktop credential is hydrated before `AuthProvider` is imported so the existing AEP authentication contract can be reused without persisting the access token in desktop webview `localStorage`.

This implementation is still a release gate until native builds and clean-machine tests prove all of the following on both operating systems:

- first login writes the credential successfully
- relaunch restores the active session from the OS credential store
- logout removes the stored credential
- expired or revoked sessions are cleared correctly
- password/security changes invalidate the desktop session as expected
- no plaintext access token is left in desktop webview local storage, installer output, crash logs, or CI artifacts
- an immediate app exit after login/logout cannot leave the credential in the wrong state

Do not describe the credential path as production-qualified until these tests pass.

## Connector authorization gate

OAuth provider pages must never load inside the privileged desktop webview. The native navigation guard opens provider authorization in the system browser.

The current backend OAuth completion returns to the normal web AEP. Before general desktop availability, qualify a clean return experience for desktop users. Acceptable implementations include an authenticated desktop deep-link return or a bounded desktop connection-status polling flow. The user must not need to guess whether authorization completed.

## Update gate

Do not enable automatic desktop updates until the updater signing key and endpoint are provisioned. Updater signing is separate from Apple/Windows application signing.

Before enabling auto-update:

- create and protect the Tauri updater signing private key
- embed only the updater public key in the application
- publish signed updater metadata over HTTPS
- test same-version refusal, forward update, interrupted update, restart, and rollback/recovery behavior
- ensure a compromised web deployment cannot replace the native binary

## Release qualification

Every public release must pass all of these checks:

1. Desktop enterprise static contract passes.
2. Shared AEP production build passes.
3. Native macOS Apple Silicon build passes.
4. Native macOS Intel build passes.
5. Native Windows x64 build passes.
6. Apple signing and notarization pass.
7. Windows code signing passes.
8. OS-protected desktop credential storage passes.
9. Login, logout, email verification, password/session invalidation, and account restrictions pass.
10. Operation switching and tenant boundaries pass.
11. Field Intelligence capture, media, sync, and recovery pass.
12. Reports, downloads, evidence uploads, and connector flows pass.
13. `agroai://open/...` deep links cannot navigate outside the approved route set.
14. OAuth/provider authorization leaves the privileged desktop webview and has a verified desktop completion path.
15. Offline start, network loss, network recovery, API failure, and stale frontend recovery pass.
16. Installer upgrade and uninstall preserve or remove local app data according to the documented policy.
17. No secrets, signing material, customer data, or access tokens are present in build artifacts or CI logs.

## Distribution surface

After the signed release pipeline is qualified, expose a first-party download surface at the AGRO-AI domain with two primary choices:

- Download for macOS
- Download for Windows

The page must detect the visitor platform only as a convenience. It must still offer both installers explicitly. Each download must show the application version and minimum OS requirement.

The existing PWA may remain available, but marketing and support copy must distinguish the installable web app from the signed AGRO-AI desktop application.

## Release order

1. Merge the reviewed desktop foundation.
2. Produce internal macOS and Windows candidates.
3. Qualify OS-protected desktop credential storage.
4. Complete the desktop OAuth return experience.
5. Provision Apple and Windows signing identities.
6. Add the protected signed-release workflow.
7. Qualify installers on clean machines.
8. Add updater signing and staged update delivery.
9. Publish the AGRO-AI download page.
10. Release to a small customer cohort.
11. Move to general desktop availability only after telemetry and support checks are clean.
