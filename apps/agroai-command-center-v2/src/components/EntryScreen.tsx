import { actions, useCommandStore } from "../state/commandStore";

export function EntryScreen() {
  const message = useCommandStore((s) => s.productionSignInMessage);
  const onboardingOpen = useCommandStore((s) => s.onboardingOpen);

  return (
    <main className="entry-screen">
      <section className="entry-panel" aria-label="Water Command Center entry">
        <p className="eyebrow">Enterprise irrigation intelligence</p>
        <h1>AGRO-AI Water Command Center</h1>
        <p className="entry-subtitle">Turn scattered irrigation data into verified water decisions.</p>
        <div className="entry-actions">
          <button className="btn primary" onClick={() => void actions.openEvaluationWorkspace()}>
            Open evaluation workspace
          </button>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              actions.submitProductionSignIn();
            }}
          >
            <button className="btn" type="submit">
              Sign in for production access
            </button>
          </form>
          <button className="btn ghost" onClick={() => actions.openOnboarding()}>
            Request enterprise onboarding
          </button>
        </div>
        {message && <p className="entry-message">{message}</p>}
      </section>

      {onboardingOpen && (
        <div className="drawer-scrim" onClick={(e) => e.target === e.currentTarget && actions.closeOnboarding()}>
          <aside className="drawer onboarding-drawer" role="dialog" aria-modal="true" aria-label="Enterprise onboarding brief">
            <div className="drawer-head">
              <div>
                <p className="eyebrow">Enterprise onboarding</p>
                <h2>Production workspace requirements</h2>
              </div>
              <button className="btn ghost compact" onClick={() => actions.closeOnboarding()}>
                Close
              </button>
            </div>
            <div className="drawer-body">
              <dl className="brief-def">
                <div>
                  <dt>Identity</dt>
                  <dd>Provision tenant users, roles, and production identity before production access.</dd>
                </div>
                <div>
                  <dt>Sources</dt>
                  <dd>Register controller, weather, soil, flow, field-observation, and partner feed sources server-side.</dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>Move evaluation-session evidence into durable tenant persistence during production onboarding.</dd>
                </div>
                <div>
                  <dt>Calibration</dt>
                  <dd>Replace transparent v0.2 defaults with farm-specific crop, soil, flow, and controller calibration.</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
