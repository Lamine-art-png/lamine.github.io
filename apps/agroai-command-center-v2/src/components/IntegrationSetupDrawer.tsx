export function buildSetupBrief(provider: string): string {
  return [
    "AGRO-AI integration setup brief",
    "",
    `Provider: ${provider}`,
    "Workspace: Alpha Vineyard · Water Command Center",
    "Credential vault requirement: production credentials must be encrypted and stored server-side.",
    "Tenant provisioning requirement: create a tenant-scoped Workbench session and data namespace.",
    "Farm and block mapping requirement: map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities.",
    "Security note: credentials are never stored in browser storage.",
    "Operational next step: provision provider access, select production targets, then enable live source analysis.",
  ].join("\n");
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function download(name: string, content: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function IntegrationSetupDrawer({ provider, onClose }: { provider: string; onClose: () => void }) {
  const brief = buildSetupBrief(provider);
  const rows: [string, string][] = [
    ["Provider", provider],
    ["Workspace", "Alpha Vineyard · Water Command Center"],
    ["Credential vault requirement", "Production credentials encrypted and stored server-side."],
    ["Tenant provisioning requirement", "Tenant-scoped Workbench session and data namespace."],
    ["Farm and block mapping requirement", "Map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities."],
    ["Security note", "Credentials are never stored in browser storage."],
    ["Operational next step", "Provision provider access, select production targets, then enable live source analysis."],
  ];
  return (
    <div className="drawer-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Integration setup brief">
        <div className="drawer-head">
          <div>
            <p className="eyebrow">Integration setup brief</p>
            <h2>{provider}</h2>
          </div>
          <button className="btn ghost compact" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          <dl className="brief-def">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd className="value">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="drawer-actions">
            <button className="btn compact" onClick={() => copy(brief)}>
              Copy brief
            </button>
            <button className="btn compact" onClick={() => download(`${provider.toLowerCase().replace(/\s+/g, "-")}-setup-brief.txt`, brief)}>
              Download brief
            </button>
            <button className="btn ghost compact" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
