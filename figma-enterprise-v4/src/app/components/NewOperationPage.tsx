import { useMemo, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight, Check, Database, FileUp, Leaf, MapPin, ShieldCheck } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth, type Workspace } from "../auth/AuthProvider";
import { BG, BORDER, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  professional: "Professional",
  team: "Team",
  network: "Network",
  enterprise: "Enterprise",
  pilot: "Free",
  pro: "Professional",
  waterops: "Professional",
  assurance_audit: "Professional",
  assurance: "Team",
};

function planLimit(entitlements: Record<string, unknown>) {
  const value = Number(entitlements.max_workspaces);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function operationIsUnmetered(plan: string, entitlements: Record<string, unknown>) {
  const profile = String(entitlements.access_profile || "customer");
  return plan === "enterprise" || profile === "internal" || profile === "demo";
}

function Field({ label, detail, children }: { label: string; detail?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] font-semibold" style={{ color: TEXT }}>{label}</span>
      {detail ? <span className="ml-2 text-[11px]" style={{ color: MUTED }}>{detail}</span> : null}
      <div className="mt-2">{children}</div>
    </label>
  );
}

const inputClass = "h-11 w-full rounded-xl px-3 text-[13px] outline-none transition-shadow focus:ring-2 focus:ring-emerald-700/20";

export function NewOperationPage() {
  const navigate = useNavigate();
  const {
    currentOrganization,
    workspaces,
    entitlements,
    createWorkspace,
  } = useAuth();
  const plan = String(currentOrganization?.plan || "free").toLowerCase();
  const planName = PLAN_LABELS[plan] || "Free";
  const organizationWorkspaces = useMemo(
    () => currentOrganization?.id
      ? workspaces.filter((workspace) => !workspace.organization_id || workspace.organization_id === currentOrganization.id)
      : workspaces,
    [currentOrganization?.id, workspaces],
  );
  const limit = planLimit(entitlements);
  const unmetered = operationIsUnmetered(plan, entitlements);
  const atLimit = !unmetered && limit !== null && organizationWorkspaces.length >= limit;
  const role = String(currentOrganization?.role || "owner");
  const canManage = role === "owner" || role === "admin";

  const [name, setName] = useState("");
  const [crop, setCrop] = useState("");
  const [region, setRegion] = useState("");
  const [mode, setMode] = useState<"evaluation" | "live">("evaluation");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [createdWorkspace, setCreatedWorkspace] = useState<Workspace | null>(null);

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files || []));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || atLimit || !canManage || createdWorkspace) return;
    const operationName = name.trim();
    if (operationName.length < 2) {
      setError("Give this operation a name with at least two characters.");
      return;
    }

    setBusy(true);
    setError("");
    setProgress("Creating a clean operation…");
    let created: Workspace | null = null;
    try {
      created = await createWorkspace({
        name: operationName,
        crop: crop.trim() || undefined,
        region: region.trim() || undefined,
        mode,
      });
      setCreatedWorkspace(created);

      if (!files.length) {
        navigate("/");
        return;
      }

      for (let index = 0; index < files.length; index += 1) {
        setProgress(`Uploading ${index + 1} of ${files.length}: ${files[index].name}`);
        await apiClient.evidence.upload(files[index], undefined, created.id);
      }
      navigate("/evidence");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "The operation could not be created.";
      if (created) {
        setError(`The operation was created, but a file upload needs attention: ${message}`);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  const capacityLabel = unmetered || limit === null
    ? `${organizationWorkspaces.length} operations · custom capacity`
    : `${organizationWorkspaces.length} of ${limit} operations used`;

  return (
    <div className="min-h-full" style={{ background: BG }} data-new-operation-page>
      <header className="px-4 py-6 sm:px-8 sm:py-8" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="max-w-[980px]">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "#2D6A4F" }}>Operations</div>
          <h1 className="mt-2 text-[28px] font-semibold tracking-tight sm:text-[34px]" style={{ color: TEXT }}>Create a new operation</h1>
          <p className="mt-3 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>
            Start a separate operating environment with its own files, evidence, field queue, tasks, decisions, conversations, connectors, and reports.
          </p>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1180px] gap-5 px-4 py-5 sm:px-8 sm:py-7 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="rounded-2xl p-5 sm:p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          {atLimit ? (
            <div className="rounded-2xl p-6" style={{ background: "#FFF9E8", border: "1px solid #E8D7A1" }} data-operation-limit-reached>
              <div className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: "#866312" }}>Plan capacity reached</div>
              <h2 className="mt-2 text-[23px] font-semibold" style={{ color: TEXT }}>Your {planName} plan includes {limit} operation{limit === 1 ? "" : "s"}.</h2>
              <p className="mt-3 text-[13px] leading-6" style={{ color: MUTED }}>
                Your existing operation remains available. Upgrade the plan to create another isolated operation without deleting or mixing current data.
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <Link to="/pricing"><PortalButton>Compare plans</PortalButton></Link>
                <Link to="/"><PortalButton variant="secondary">Return to current operation</PortalButton></Link>
              </div>
            </div>
          ) : !canManage ? (
            <div className="rounded-2xl p-6" style={{ background: "#FFF9E8", border: "1px solid #E8D7A1" }}>
              <h2 className="text-[21px] font-semibold" style={{ color: TEXT }}>Owner or admin approval required</h2>
              <p className="mt-2 text-[13px] leading-6" style={{ color: MUTED }}>Creating an operation changes the organization’s commercial capacity. Ask an owner or admin to create it.</p>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-6">
              <div>
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full text-[12px] font-semibold text-white" style={{ background: "#0D5137" }}>1</span>
                  <div>
                    <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>Name the operation</h2>
                    <p className="mt-1 text-[12px]" style={{ color: MUTED }}>You can change this later in Settings.</p>
                  </div>
                </div>
                <div className="mt-4">
                  <Field label="Operation name" detail="Required">
                    <input
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      placeholder="e.g. Ventura Avocado Portfolio"
                      maxLength={120}
                      autoFocus
                      className={inputClass}
                      style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
                      data-operation-name-input
                    />
                  </Field>
                </div>
              </div>

              <div className="h-px" style={{ background: BORDER }} />

              <div>
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full text-[12px] font-semibold text-white" style={{ background: "#0D5137" }}>2</span>
                  <div>
                    <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>Add operating context</h2>
                    <p className="mt-1 text-[12px]" style={{ color: MUTED }}>Optional context helps AGRO-AI organize the new environment.</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Field label="Crop or portfolio type" detail="Optional">
                    <div className="relative"><Leaf className="pointer-events-none absolute left-3 top-3.5 h-4 w-4" style={{ color: MUTED }} /><input value={crop} onChange={(event) => setCrop(event.target.value)} placeholder="Avocados, almonds, mixed crops" className={`${inputClass} pl-10`} style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></div>
                  </Field>
                  <Field label="Region" detail="Optional">
                    <div className="relative"><MapPin className="pointer-events-none absolute left-3 top-3.5 h-4 w-4" style={{ color: MUTED }} /><input value={region} onChange={(event) => setRegion(event.target.value)} placeholder="Ventura County, California" className={`${inputClass} pl-10`} style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></div>
                  </Field>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <button type="button" onClick={() => setMode("evaluation")} className="rounded-xl p-4 text-left" style={{ background: mode === "evaluation" ? "#EEF8E8" : BG, border: `1px solid ${mode === "evaluation" ? "#8DBD76" : BORDER}` }}>
                    <div className="flex items-center justify-between gap-3"><span className="text-[13px] font-semibold" style={{ color: TEXT }}>Evaluation operation</span>{mode === "evaluation" ? <Check className="h-4 w-4" style={{ color: "#207044" }} /> : null}</div>
                    <p className="mt-2 text-[12px] leading-5" style={{ color: MUTED }}>A clean workspace for uploads, evidence review, analysis, tasks, and reports.</p>
                  </button>
                  <button type="button" onClick={() => setMode("live")} className="rounded-xl p-4 text-left" style={{ background: mode === "live" ? "#EEF8E8" : BG, border: `1px solid ${mode === "live" ? "#8DBD76" : BORDER}` }}>
                    <div className="flex items-center justify-between gap-3"><span className="text-[13px] font-semibold" style={{ color: TEXT }}>Live operation</span>{mode === "live" ? <Check className="h-4 w-4" style={{ color: "#207044" }} /> : null}</div>
                    <p className="mt-2 text-[12px] leading-5" style={{ color: MUTED }}>For connected systems and ongoing field operations. Requires plan access to live connectors.</p>
                  </button>
                </div>
              </div>

              <div className="h-px" style={{ background: BORDER }} />

              <div>
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full text-[12px] font-semibold text-white" style={{ background: "#0D5137" }}>3</span>
                  <div>
                    <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>Start with files or start empty</h2>
                    <p className="mt-1 text-[12px]" style={{ color: MUTED }}>Files are stored inside this operation and do not populate another operation.</p>
                  </div>
                </div>
                <label className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-2xl px-5 py-8 text-center" style={{ background: BG, border: `1px dashed #AAB8AE` }}>
                  <FileUp className="h-7 w-7" style={{ color: "#2D6A4F" }} />
                  <span className="mt-3 text-[13px] font-semibold" style={{ color: TEXT }}>{files.length ? `${files.length} file${files.length === 1 ? "" : "s"} selected` : "Choose optional evidence files"}</span>
                  <span className="mt-1 text-[11px]" style={{ color: MUTED }}>CSV, PDF, spreadsheet, JSON, text, or supported geospatial files</span>
                  <input type="file" multiple onChange={chooseFiles} className="sr-only" accept=".csv,.pdf,.xlsx,.xls,.json,.txt,.geojson,.zip" data-operation-file-input />
                </label>
                {files.length ? (
                  <div className="mt-3 space-y-2">{files.map((file) => <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><span className="min-w-0 truncate">{file.name}</span><span className="shrink-0" style={{ color: MUTED }}>{Math.max(1, Math.round(file.size / 1024))} KB</span></div>)}</div>
                ) : null}
              </div>

              {error ? <div className="rounded-xl px-4 py-3 text-[13px] leading-6" style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}>{error}</div> : null}
              {progress ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#EFF8F2", border: "1px solid #B7D9C2", color: "#205C3B" }}>{progress}</div> : null}

              {createdWorkspace && error ? (
                <div className="flex flex-wrap gap-3">
                  <PortalButton type="button" onClick={() => navigate("/evidence")}>Open created operation</PortalButton>
                  <PortalButton type="button" variant="secondary" onClick={() => navigate("/")}>Open Command Center</PortalButton>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <PortalButton type="submit" disabled={busy || !name.trim()} data-create-operation-button>
                    {busy ? "Creating operation…" : <>Create operation <ArrowRight className="ml-2 inline h-4 w-4" /></>}
                  </PortalButton>
                  <Link to="/"><PortalButton type="button" variant="secondary">Cancel</PortalButton></Link>
                </div>
              )}
            </form>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-center gap-3"><Database className="h-5 w-5" style={{ color: "#2D6A4F" }} /><h2 className="text-[15px] font-semibold" style={{ color: TEXT }}>Plan capacity</h2></div>
            <div className="mt-4 text-[24px] font-semibold" style={{ color: TEXT }}>{planName}</div>
            <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{capacityLabel}</div>
            {!unmetered && limit !== null ? <div className="mt-4 h-2 overflow-hidden rounded-full" style={{ background: "#E4E8E2" }}><div className="h-full rounded-full" style={{ background: "#1F7350", width: `${Math.min(100, (organizationWorkspaces.length / limit) * 100)}%` }} /></div> : null}
            <Link to="/pricing" className="mt-4 inline-block text-[12px] font-semibold" style={{ color: "#1F7350" }}>Review plan details</Link>
          </section>

          <section className="rounded-2xl p-5" style={{ background: "#0A2A1F", color: "white" }}>
            <div className="flex items-center gap-3"><ShieldCheck className="h-5 w-5" style={{ color: "#DDEB8F" }} /><h2 className="text-[15px] font-semibold">Clean separation</h2></div>
            <div className="mt-4 space-y-3 text-[12px] leading-5" style={{ color: "rgba(255,255,255,0.68)" }}>
              <p>Each operation receives its own workspace identifier.</p>
              <p>New uploads, tasks, decisions, intelligence history, connectors, and reports are attached to that operation.</p>
              <p>Switch operations from the sidebar at any time.</p>
            </div>
          </section>
        </aside>
      </main>
    </div>
  );
}
