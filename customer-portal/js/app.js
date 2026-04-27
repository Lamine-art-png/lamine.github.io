import { createStore } from "./v2/state/store.js";
import { authService } from "./v2/auth/authService.js";
import { can } from "./v2/auth/rbac.js";
import { normalizeRoute } from "./v2/routes/router.js";
import { shellHtml } from "./v2/components/shell.js";
import { addAuditLog } from "./v2/services/auditService.js";
import { integrationSetupService } from "./v2/services/integrationSetupService.js";
import { loginView } from "./v2/views/loginView.js";
import {
  auditLogsView,
  commandCenterView,
  farmsView,
  intelligenceView,
  integrationsView,
  reportsView,
  settingsView,
  verificationView,
} from "./v2/views/appViews.js";

const app = document.getElementById("app");
const state = createStore();
state.session = authService.restore();

function routeView() {
  const route = normalizeRoute(state.app.route);
  if (route === "command_center") return commandCenterView(state);
  if (route === "farms") return farmsView(state);
  if (route === "intelligence") return intelligenceView(state);
  if (route === "verification") return verificationView(state);
  if (route === "reports") return reportsView(state);
  if (route === "integrations") return integrationsView(state);
  if (route === "settings") return settingsView(state);
  if (route === "audit_logs") return auditLogsView(state);
  return commandCenterView(state);
}

function guardedRoute(route) {
  const role = state.session?.user?.role;
  if (route === "integrations" && !can(role, "manage:integrations")) return false;
  if (route === "audit_logs" && !can(role, "view:audit")) return false;
  return true;
}

function render() {
  if (!state.session) {
    app.innerHTML = loginView(state);
    bindEvents();
    return;
  }
  app.innerHTML = shellHtml(state, routeView());
  bindEvents();
}

function clearBanners() {
  state.app.error = "";
  state.app.success = "";
}

function bindForms() {
  const loginForm = app.querySelector("form[data-form='login']");
  if (loginForm) {
    loginForm.addEventListener("submit", (event) => {
      event.preventDefault();
      clearBanners();
      const formData = new FormData(loginForm);
      const result = authService.login({
        email: formData.get("email"),
        password: formData.get("password"),
        remember: formData.get("remember") === "on",
      });
      if (!result.ok) {
        state.authUi.message = result.error;
      } else {
        state.session = result.session;
        state.authUi.message = "";
        addAuditLog(state, "login", state.session.user.name, "Enterprise session established");
      }
      render();
    });
  }

  const forgotForm = app.querySelector("form[data-form='forgot']");
  if (forgotForm) {
    forgotForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(forgotForm);
      const result = authService.requestPasswordReset(formData.get("email"));
      state.authUi.message = result.ok ? result.message : result.error;
      render();
    });
  }

  const resetForm = app.querySelector("form[data-form='reset']");
  if (resetForm) {
    resetForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(resetForm);
      const result = authService.completePasswordReset({ token: formData.get("token"), password: formData.get("password") });
      state.authUi.message = result.ok ? result.message : result.error;
      render();
    });
  }

  const verificationForm = app.querySelector("form[data-form='verification']");
  if (verificationForm) {
    verificationForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(verificationForm);
      const recommendationId = state.app.selectedRecommendationId;
      const recommendation = state.app.recommendations.find((r) => r.id === recommendationId);
      const stage = formData.get("stage");

      recommendation.status = stage;
      state.app.verificationLogs.unshift({
        id: `v_${Math.random().toString(36).slice(2, 8)}`,
        recommendationId,
        zoneId: recommendation.zoneId,
        stage,
        by: state.session.user.name,
        at: new Date().toISOString(),
        changed: formData.get("note"),
        outcome: formData.get("outcome"),
        note: formData.get("note"),
      });
      addAuditLog(state, "verification_submission", state.session.user.name, `Recommendation ${recommendationId} moved to ${stage}`);
      state.app.success = "Verification event recorded.";
      render();
    });
  }
}

function bindEvents() {
  bindForms();

  app.querySelectorAll("[data-action='auth-mode']").forEach((button) => {
    button.addEventListener("click", () => {
      state.authUi.mode = button.dataset.mode;
      state.authUi.message = "";
      render();
    });
  });

  app.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      const route = button.dataset.route;
      if (!guardedRoute(route)) {
        state.app.error = "Your role does not have access to this module.";
        render();
        return;
      }
      clearBanners();
      state.app.route = route;
      render();
    });
  });

  app.querySelectorAll("[data-select='organization']").forEach((select) => {
    select.addEventListener("change", () => {
      state.app.organizationId = select.value;
      const firstFarm = state.app.farms.find((f) => f.organizationId === select.value);
      if (firstFarm) state.app.farmId = firstFarm.id;
      clearBanners();
      render();
    });
  });

  app.querySelectorAll("[data-select='farm']").forEach((select) => {
    select.addEventListener("change", () => {
      state.app.farmId = select.value;
      clearBanners();
      render();
    });
  });

  app.querySelectorAll("[data-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      state.filters[select.dataset.filter] = select.value;
      render();
    });
  });

  app.querySelectorAll("[data-action='set-farm']").forEach((button) => {
    button.addEventListener("click", () => {
      state.app.farmId = button.dataset.farm;
      state.app.route = "command_center";
      render();
    });
  });

  app.querySelectorAll("[data-action='select-recommendation']").forEach((button) => {
    button.addEventListener("click", () => {
      state.app.selectedRecommendationId = button.dataset.rec;
      render();
    });
  });

  app.querySelectorAll("[data-action='provider-select']").forEach((select) => {
    select.addEventListener("change", () => {
      state.app.integrationsSetup = integrationSetupService.setProvider(state.app.integrationsSetup, select.value);
      render();
    });
  });

  app.querySelectorAll("[data-action='provider-state']").forEach((select) => {
    select.value = state.app.integrationsSetup.state;
    select.addEventListener("change", () => {
      state.app.integrationsSetup = integrationSetupService.setState(state.app.integrationsSetup, select.value);
      state.app.success = `Provider state updated: ${select.value}.`;
      addAuditLog(state, "provider_connection", state.session.user.name, `${state.app.integrationsSetup.provider} ${select.value}`);
      render();
    });
  });

  app.querySelectorAll("[data-action='integration-next']").forEach((button) => {
    button.addEventListener("click", () => {
      state.app.integrationsSetup = integrationSetupService.nextStep(state.app.integrationsSetup);
      render();
    });
  });

  app.querySelectorAll("[data-action='integration-prev']").forEach((button) => {
    button.addEventListener("click", () => {
      state.app.integrationsSetup = integrationSetupService.previousStep(state.app.integrationsSetup);
      render();
    });
  });

  app.querySelectorAll("[data-action='launch-demo']").forEach((button) => {
    button.addEventListener("click", () => {
      clearBanners();
      state.app.success = "Demo Organization activated in isolated tenant mode.";
      state.app.organizationId = "org_demo";
      state.app.farmId = "farm_alpha";
      state.app.zoneId = "zone_162803";
      state.app.route = "command_center";
      render();
    });
  });

  app.querySelectorAll("[data-action='logout']").forEach((button) => {
    button.addEventListener("click", () => {
      addAuditLog(state, "logout", state.session.user.name, "Session terminated");
      authService.logout();
      state.session = null;
      state.authUi.mode = "login";
      state.authUi.message = "Session closed.";
      render();
    });
  });
}

window.addEventListener("online", () => {
  state.app.success = "Connectivity restored. Live synchronization resumed.";
  render();
});

window.addEventListener("offline", () => {
  state.app.error = "Connection lost. Working in protected offline mode.";
  render();
});

setInterval(() => {
  if (state.session?.expiresAt && Date.now() > state.session.expiresAt) {
    authService.logout();
    state.session = null;
    state.authUi.mode = "login";
    state.authUi.message = "Session expired. Sign in again to continue.";
    render();
  }
}, 15000);

render();
