let latestRuntimePayload = null;
let latestWorkspace = null;
let terminalPresets = {};
let terminalSessions = [];
let activeTerminalId = null;
const terminalViews = new Map();
let removeTerminalDataListener = null;
let removeTerminalExitListener = null;
let terminalsBootstrapped = false;
const magneticBindings = new WeakSet();
const prefersReducedMotion = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : null;
let ambientPointerBound = false;

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatCurrency(value) {
  return `${Number(value || 0).toFixed(2)} EUR`;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function pickLabel(value, fallback = "Aucune entree") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function renderList(elementId, items, formatter, emptyLabel = "Aucune entree") {
  const element = byId(elementId);
  if (!element) {
    return;
  }
  element.innerHTML = "";
  const source = asArray(items);
  if (source.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyLabel;
    element.appendChild(li);
    return;
  }
  source.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = formatter(item || {});
    element.appendChild(li);
  });
}

function renderInfoGrid(elementId, entries) {
  const element = byId(elementId);
  if (!element) {
    return;
  }
  element.innerHTML = "";
  entries.forEach((entry) => {
    const dt = document.createElement("dt");
    dt.textContent = entry.label;
    const dd = document.createElement("dd");
    dd.textContent = pickLabel(entry.value);
    element.appendChild(dt);
    element.appendChild(dd);
  });
}

function renderNormalizedItem(item) {
  const detail = item && item.detail ? `<small>${escapeHtml(pickLabel(item.detail))}</small>` : "";
  const costHint = item && item.cost_hint ? `<small>${escapeHtml(pickLabel(item.cost_hint))}</small>` : "";
  const badge = item && item.badge
    ? `<span class="item-badge" data-age="${escapeHtml(pickLabel(item.age_band, ""))}">${escapeHtml(pickLabel(item.badge))}</span>`
    : "";
  return `
    <div class="item-copy">
      <strong>${escapeHtml(pickLabel(item?.title, "item"))}</strong>
      <span>${escapeHtml(pickLabel(item?.subtitle, "Aucun detail"))}</span>
      ${detail}
      ${costHint}
    </div>
    ${badge}
  `;
}

function renderTextList(elementId, items, emptyLabel = "Aucune entree") {
  const element = byId(elementId);
  if (!element) {
    return;
  }
  element.innerHTML = "";
  const source = asArray(items);
  if (source.length === 0) {
    const li = document.createElement("li");
    li.textContent = emptyLabel;
    element.appendChild(li);
    return;
  }
  source.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = pickLabel(item);
    element.appendChild(li);
  });
}

function renderSummaryStrip(elementId, cards) {
  const element = byId(elementId);
  if (!element) {
    return;
  }
  element.innerHTML = "";
  const source = asArray(cards);
  if (source.length === 0) {
    const article = document.createElement("article");
    article.className = "summary-card";
    article.innerHTML = `
      <div class="summary-card-label">Signal</div>
      <div class="summary-card-value">Waiting</div>
      <div class="summary-card-detail">Aucune carte locale pour l'instant.</div>
    `;
    element.appendChild(article);
    return;
  }
  source.forEach((card) => {
    const article = document.createElement("article");
    article.className = "summary-card";
    article.innerHTML = `
      <div class="summary-card-label">${pickLabel(card.label, "Metric")}</div>
      <div class="summary-card-value">${pickLabel(card.value, "0")}</div>
      <div class="summary-card-detail">${pickLabel(card.detail, "")}</div>
    `;
    element.appendChild(article);
  });
}

function renderStatusStrip(elementId, cards) {
  const element = byId(elementId);
  if (!element) {
    return;
  }
  element.innerHTML = "";
  asArray(cards).forEach((card) => {
    const article = document.createElement("article");
    article.className = "status-cube";
    if (card.status) {
      article.dataset.status = pickLabel(card.status, "warning");
    }
    article.innerHTML = `
      <div class="status-cube-label">${escapeHtml(pickLabel(card.label, "Metric"))}</div>
      <div class="status-cube-value">${escapeHtml(pickLabel(card.value, "0"))}</div>
      <div class="status-cube-detail">${escapeHtml(pickLabel(card.detail, ""))}</div>
    `;
    element.appendChild(article);
  });
}

function normalizeMetricStatus(metric) {
  const rawValue = String(metric?.value || "").toLowerCase();
  const rawStatus = String(metric?.status || "").toLowerCase();
  const candidate = rawStatus || rawValue;
  if (candidate.includes("error") || candidate.includes("fail")) {
    return "error";
  }
  if (candidate.includes("watch") || candidate.includes("warning") || candidate.includes("degrade")) {
    return "warning";
  }
  return "ok";
}

function renderPulseGrid(metrics) {
  const cards = asArray(metrics).map((metric) => ({
    ...metric,
    status: normalizeMetricStatus(metric),
  }));
  renderStatusStrip("pulse-grid", cards);
}

function renderHeroStory(items) {
  const root = byId("home-story");
  if (!root) {
    return;
  }
  root.innerHTML = "";
  const source = asArray(items);
  if (source.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Le recit de session apparaitra ici.";
    root.appendChild(li);
    return;
  }
  source.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = pickLabel(item, "Aucun element");
    root.appendChild(li);
  });
}

function renderSidebarHighlights(items) {
  const root = byId("sidebar-highlight-list");
  if (!root) {
    return;
  }
  root.innerHTML = "";
  const source = asArray(items);
  if (source.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Aucun contexte fondateur epingle pour l'instant.";
    root.appendChild(li);
    return;
  }
  source.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <strong>${escapeHtml(pickLabel(item.label, "Context"))}</strong>
      <span>${escapeHtml(pickLabel(item.value, "Aucune valeur"))}</span>
      <small>${escapeHtml(pickLabel(item.detail, ""))}</small>
    `;
    root.appendChild(li);
  });
}

function renderConversationFeed(elementId, items, emptyLabel = "Aucun echange recent.") {
  const root = byId(elementId);
  if (!root) {
    return;
  }
  root.innerHTML = "";
  const source = asArray(items);
  if (source.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyLabel;
    root.appendChild(li);
    return;
  }
  source.forEach((item) => {
    const li = document.createElement("li");
    li.className = "conversation-entry";
    li.dataset.age = pickLabel(item.age_band, "week");
    li.innerHTML = `
      <div class="conversation-header">
        <strong>${escapeHtml(pickLabel(item.title, "Sujet"))}</strong>
        <span class="item-badge" data-age="${escapeHtml(pickLabel(item.age_band, ""))}">${escapeHtml(pickLabel(item.badge, "thread"))}</span>
      </div>
      <div class="conversation-meta">${escapeHtml(pickLabel(item.subtitle, "Aucun contexte"))}</div>
      <div class="conversation-body">
        <div class="conversation-line">
          <div class="conversation-role">Founder</div>
          <div class="conversation-text">${escapeHtml(pickLabel(item.detail, "Aucun message recent."))}</div>
        </div>
        <div class="conversation-line">
          <div class="conversation-role">Agent</div>
          <div class="conversation-text reply">${escapeHtml(pickLabel(item.reply, item.detail || "Aucune reponse autoritative."))}</div>
        </div>
      </div>
    `;
    root.appendChild(li);
  });
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "Home";
}

function resolveMotionMode() {
  if (latestWorkspace?.motion_mode === "reduced") {
    return "reduced";
  }
  if (latestWorkspace?.motion_mode === "system") {
    return prefersReducedMotion?.matches ? "reduced" : "full";
  }
  return "full";
}

function currentDockPreset() {
  const preset = String(latestWorkspace?.terminal_dock_preset || "focus").toLowerCase();
  return ["compact", "work", "focus"].includes(preset) ? preset : "focus";
}

function syncDockPresetButtons() {
  const preset = currentDockPreset();
  document.querySelectorAll(".dock-preset").forEach((button) => {
    button.classList.toggle("active", button.dataset.preset === preset);
  });
}

function applyWorkspacePreferences({ persist = false } = {}) {
  if (!latestWorkspace) {
    return;
  }
  const terminalPanel = byId("terminal-panel");
  if (terminalPanel) {
    terminalPanel.dataset.dock = currentDockPreset();
  }
  document.body.dataset.motion = resolveMotionMode();
  document.body.dataset.theme = pickLabel(latestWorkspace.theme_variant, "hybrid_luxe");
  syncDockPresetButtons();
  if (persist) {
    persistWorkspace();
  }
}

function bindMagnetic(element) {
  if (!element || magneticBindings.has(element)) {
    return;
  }
  magneticBindings.add(element);
  const reset = () => {
    element.style.transform = "";
  };
  element.addEventListener("pointermove", (event) => {
    if (document.body.dataset.motion === "reduced") {
      return;
    }
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return;
    }
    const offsetX = (event.clientX - rect.left - rect.width / 2) / rect.width;
    const offsetY = (event.clientY - rect.top - rect.height / 2) / rect.height;
    const strength = element.classList.contains("tab") ? 8 : 12;
    element.style.transform = `translate3d(${(offsetX * strength).toFixed(2)}px, ${(offsetY * strength).toFixed(2)}px, 0)`;
  });
  element.addEventListener("pointerleave", reset);
  element.addEventListener("blur", reset);
}

function refreshInteractiveEffects() {
  document.querySelectorAll("[data-magnetic]").forEach(bindMagnetic);
}

function bindAmbientPointer() {
  if (ambientPointerBound) {
    return;
  }
  ambientPointerBound = true;
  document.addEventListener("pointermove", (event) => {
    if (document.body.dataset.motion === "reduced") {
      return;
    }
    document.body.style.setProperty("--pointer-x", `${event.clientX}px`);
    document.body.style.setProperty("--pointer-y", `${event.clientY}px`);
  });
  if (prefersReducedMotion && typeof prefersReducedMotion.addEventListener === "function") {
    prefersReducedMotion.addEventListener("change", () => {
      applyWorkspacePreferences({ persist: false });
    });
  }
}

function setActionNote(message, tone = "neutral") {
  const element = byId("startup-action-note");
  if (!element) {
    return;
  }
  element.textContent = pickLabel(message, "Aucune action recente.");
  element.dataset.tone = tone;
}

function buildActionButton(action, className = "inline-action") {
  const button = document.createElement("button");
  button.className = className;
  button.type = "button";
  button.textContent = pickLabel(action?.label, "Action");
  button.dataset.action = pickLabel(action?.action, "");
  button.addEventListener("click", () => {
    executeStartupAction(button.dataset.action).catch((error) => {
      setActionNote(String(error?.message || error), "error");
    });
  });
  return button;
}

async function persistWorkspace() {
  if (!latestWorkspace) {
    return;
  }
  try {
    latestWorkspace = await window.projectOSDesktop.saveWorkspace(latestWorkspace);
  } catch (error) {
    console.error("Workspace save failed", error);
  }
}

function setView(tabName, options = {}) {
  const resolvedTab = document.querySelector(`.tab[data-tab="${tabName}"]`) ? tabName : "home";
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === resolvedTab);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.dataset.view === resolvedTab);
  });
  if (latestWorkspace) {
    latestWorkspace.last_active_tab = capitalize(resolvedTab);
    if (options.persist !== false) {
      persistWorkspace();
    }
  }
  const workspace = document.querySelector(".workspace");
  if (workspace) {
    workspace.scrollTo({ top: 0, behavior: document.body.dataset.motion === "reduced" ? "auto" : "smooth" });
  }
}

function applyTabHandlers() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.tab));
  });
  byId("refresh-button").addEventListener("click", () => {
    loadStartup().catch(renderFailure);
  });
  document.querySelectorAll(".dock-preset").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!latestWorkspace) {
        return;
      }
      latestWorkspace.terminal_dock_preset = button.dataset.preset || "focus";
      applyWorkspacePreferences();
      await persistWorkspace();
      const activeView = terminalViews.get(activeTerminalId);
      if (activeView) {
        setTimeout(() => activeView.resizeNow(), 0);
      }
    });
  });
  bindAmbientPointer();
  refreshInteractiveEffects();
}

function renderStartupHealth(payload) {
  const startup = payload.startup_health || {};
  const status = pickLabel(startup.overall_status, startup.gateway_status || "startup");
  const chip = byId("startup-chip");
  chip.textContent = status;
  chip.dataset.status = status;

  const cardsRoot = byId("startup-health-list");
  cardsRoot.innerHTML = "";
  asArray(payload.views?.home?.health_cards || startup.cards).forEach((card) => {
    const li = document.createElement("li");
    li.dataset.status = pickLabel(card.status, "warning");

    const header = document.createElement("div");
    header.className = "health-card-header";
    const title = document.createElement("strong");
    title.textContent = pickLabel(card.label, "Check");
    const badge = document.createElement("span");
    badge.className = "health-card-status";
    badge.dataset.status = pickLabel(card.status, "warning");
    badge.textContent = pickLabel(card.status_badge, card.status);
    header.appendChild(title);
    header.appendChild(badge);

    const summary = document.createElement("div");
    summary.className = "health-card-summary";
    summary.textContent = pickLabel(card.summary, "Aucun resume.");

    const detail = document.createElement("div");
    detail.className = "health-card-detail";
    detail.textContent = pickLabel(card.detail, "Aucun detail.");

    li.appendChild(header);
    li.appendChild(summary);
    li.appendChild(detail);

    const actions = asArray(card.actions);
    if (actions.length > 0) {
      const actionsRow = document.createElement("div");
      actionsRow.className = "health-card-actions";
      actions.forEach((action) => {
        actionsRow.appendChild(buildActionButton(action));
      });
      li.appendChild(actionsRow);
    }
    cardsRoot.appendChild(li);
  });

  const actionsRoot = byId("actions-list");
  actionsRoot.innerHTML = "";
  const startupActions = asArray(startup.actions);
  if (startupActions.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Aucune action proposee.";
    actionsRoot.appendChild(li);
  } else {
    startupActions.forEach((action) => {
      const li = document.createElement("li");
      li.appendChild(buildActionButton(action));
      const span = document.createElement("span");
      span.textContent = pickLabel(action.action, "action");
      li.appendChild(span);
      actionsRoot.appendChild(li);
    });
  }
}

function renderHome(payload) {
  const home = payload.views?.home || {};
  byId("hero-title").textContent = pickLabel(home.headline, "Project OS pret pour reprendre la session");
  byId("hero-summary").textContent = pickLabel(home.summary, "Payload local indisponible.");
  renderHeroStory(asArray(home.story));
  renderPulseGrid(asArray(home.metrics));
  byId("current-run-chip").textContent = `${asArray(home.current_session_items).length} runs`;
  byId("recent-runs-chip").textContent = `${asArray(home.recent_run_items).length} entries`;
  byId("discord-chip").textContent = pickLabel(payload.views?.discord?.summary_cards?.[2]?.value, "remote");
  byId("monitor-mode-chip").textContent = pickLabel(payload.views?.terminals?.monitor_mode, "single_screen").replaceAll("_", " ");
  renderList("session-list", asArray(home.current_session_items), renderNormalizedItem, "Aucun run actif dans la session.");
  renderList("runs-list", asArray(home.recent_run_items), renderNormalizedItem, "Aucun run recent.");
  renderList("discord-list", asArray(home.discord_items), renderNormalizedItem, "Aucune activite distante recente.");
  renderInfoGrid("runtime-facts", asArray(home.runtime_facts));
  renderSidebarHighlights(asArray(home.sidebar?.highlights));
  renderList("roadmap-list", asArray(home.sidebar?.roadmaps), renderNormalizedItem, "Aucune roadmap recente.");
  renderList("pinned-topic-list", asArray(home.sidebar?.pinned_topics), renderNormalizedItem, "Aucun sujet important epingle.");
  renderConversationFeed("conversation-strip", asArray(home.conversation_items), "Aucun echange recent pour l'instant.");
  byId("conversation-context-note").textContent = pickLabel(home.conversation_note, "Le rappel des derniers echanges apparaitra ici.");
}

function renderSession(payload) {
  const session = payload.views?.session || {};
  byId("session-summary-text").textContent = pickLabel(session.operator_question, "Ce qui attend vraiment le fondateur.");
  renderSummaryStrip("session-summary-strip", asArray(session.summary_cards));
  renderList("clarifications-list", asArray(session.clarifications), renderNormalizedItem, "Aucune clarification en attente.");
  renderList("contracts-list", asArray(session.contracts), renderNormalizedItem, "Aucun contrat en attente.");
  renderList("approvals-list", asArray(session.approvals), renderNormalizedItem, "Aucune approval en attente.");
  renderList("missions-list", asArray(session.missions), renderNormalizedItem, "Aucune mission active dans le snapshot local.");
}

function renderRuns(payload) {
  const runs = payload.views?.runs || {};
  byId("runs-summary-text").textContent = pickLabel(runs.operator_question || runs.summary, "Quels runs meritent ton attention ?");
  renderSummaryStrip("runs-summary-strip", asArray(runs.summary_cards));
  renderList("runs-detail-list", asArray(runs.items), renderNormalizedItem, "Aucun run disponible.");
}

function renderDiscord(payload) {
  const discord = payload.views?.discord || {};
  byId("discord-summary-text").textContent = pickLabel(discord.operator_question, "Que se passe-t-il sur la surface distante ?");
  renderSummaryStrip("discord-summary-strip", asArray(discord.summary_cards));
  byId("discord-live-proof").textContent = pickLabel(discord.gateway?.summary, "Aucune preuve live recente.");
  renderList("discord-events-list", asArray(discord.events), renderNormalizedItem, "Aucun evenement Discord recent.");
  renderList("discord-deliveries-list", asArray(discord.deliveries), renderNormalizedItem, "Aucune delivery recente.");
}

function renderCosts(payload) {
  const costs = payload.views?.costs || {};
  byId("costs-summary-text").textContent = pickLabel(costs.operator_question, "Qu'est-ce qui coute vraiment ?");
  byId("costs-note").textContent = pickLabel(costs.note, "Les couts affiches ici restent strictement locaux.");
  byId("cost-today").textContent = pickLabel(costs.today, "0.00 EUR");
  byId("cost-month").textContent = pickLabel(costs.month, "0.00 EUR");
  byId("cost-current-run").textContent = pickLabel(costs.current_run, "0.00 EUR");
  renderSummaryStrip("costs-lane-strip", asArray(costs.lane_cards));
  renderInfoGrid("cost-boundary-list", asArray(costs.boundary));
}

function renderConversations(payload) {
  const conversations = payload.views?.conversations || {};
  byId("conversations-summary-text").textContent = pickLabel(conversations.operator_question, "Quelle memoire locale immediate reste utile ?");
  byId("conversations-note").textContent = pickLabel(conversations.note, "Les echanges canoniques apparaitront ici.");
  renderSummaryStrip("conversations-summary-strip", asArray(conversations.summary_cards));
  renderList("conversations-pinned-list", asArray(conversations.pinned_topics), renderNormalizedItem, "Aucun sujet epingle.");
  renderConversationFeed("conversations-week-list", asArray(conversations.weekly_exchanges), "Aucun echange sur les 7 derniers jours.");
  renderConversationFeed("conversations-archive-list", asArray(conversations.archive_exchanges), "Aucun echange archive visible.");
}

function renderTerminals(payload) {
  const terminals = payload.views?.terminals || {};
  byId("terminals-summary-text").textContent = pickLabel(terminals.operator_question, "Ou parle-t-on au lane principal ?");
  renderSummaryStrip("terminals-summary-strip", asArray(terminals.summary_cards));
  renderList("panels-list", asArray(terminals.persistent_panels), renderNormalizedItem, "Aucun panel persistant configure.");
  byId("layout-mode-value").textContent = pickLabel(terminals.layout_mode, "anchored_bottom");
  byId("monitor-mode-value").textContent = pickLabel(terminals.monitor_mode, "single_screen");
  renderTerminalLaunchers();
}

function renderSettings(payload) {
  const workspace = latestWorkspace || {};
  byId("settings-summary-text").textContent = pickLabel(payload.views?.settings?.operator_question, "Etat local exact de la coque desktop.");
  renderSummaryStrip("settings-pref-strip", [
    { label: "Theme", value: pickLabel(workspace.theme_variant, "hybrid_luxe"), detail: "identite visuelle" },
    { label: "Motion", value: resolveMotionMode(), detail: "interaction locale" },
    { label: "Dock", value: currentDockPreset(), detail: "hauteur du terminal" },
    { label: "Last Tab", value: pickLabel(workspace.last_active_tab, "Home"), detail: "retour session" },
  ]);
  byId("workspace-json").textContent = pickLabel(payload.views?.settings?.workspace_state_json, "{}");
}

function renderCodexUsageLegacy(payload) {
  const usage = payload.codex_usage_status || {};
  const summary = pickLabel(usage.summary, "indisponible");
  const remaining = pickLabel(usage.remaining_hint, "");
  const suffix = remaining && remaining !== summary ? ` · ${remaining}` : "";
  const estimated = usage.estimated ? " · estimate" : "";
  byId("codex-usage-strip").textContent = `Codex CLI · ${summary}${suffix}${estimated}`;
}

function renderPayload(payload) {
  latestRuntimePayload = payload;
  latestWorkspace = { ...(payload.workspace_state || {}) };
  applyWorkspacePreferences({ persist: false });
  renderCodexUsage(payload);
  renderStartupHealth(payload);
  renderHome(payload);
  renderSession(payload);
  renderRuns(payload);
  renderDiscord(payload);
  renderCosts(payload);
  renderConversations(payload);
  renderTerminals(payload);
  renderSettings(payload);
  refreshInteractiveEffects();
  const initialTab = String(payload.workspace_state?.last_active_tab || "Home").toLowerCase();
  setView(initialTab, { persist: false });
}

function buildFailurePayloadLegacy(error) {
  const message = String(error?.message || error || "Erreur inconnue");
  return {
    workspace_state: {
      last_active_tab: "Home",
      last_selected_workspace_root: null,
      terminal_layout_mode: "anchored_bottom",
      preferred_monitor_mode: "single_screen",
      persistent_panels: []
    },
    codex_usage_status: {
      status: "warning",
      summary: "Le signal runtime local a echoue avant de pouvoir verifier Codex.",
      usage_ratio: null,
      remaining_hint: null,
      estimated: false
    },
    startup_health: {
      overall_status: "error",
      gateway_status: "error",
      session_restore_status: "warning",
      operator_message: "Le shell est ouvert, mais le payload startup n'a pas pu etre charge. Les actions de reprise restent visibles.",
      actions: [
        { action: "refresh_startup", label: "Relancer le self-check" },
        { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
        { action: "reset_panel_layout", label: "Reset layout" }
      ],
      cards: [
        {
          id: "desktop_payload",
          label: "Desktop payload",
          status: "error",
          status_badge: "ERROR",
          summary: "Le payload runtime local n'a pas pu etre charge.",
          detail: message,
          actions: [
            { action: "refresh_startup", label: "Relancer le self-check" },
            { action: "open_master_terminal", label: "Rouvrir le terminal maitre" }
          ]
        }
      ]
    },
    views: {
      home: {
        headline: "Startup desktop en mode degrade",
        summary: "Le shell reste ouvert avec un contrat de reprise lisible.",
        story: [
          "Le renderer n'a pas recu le payload runtime initial.",
          "Le terminal maitre peut encore etre relance localement.",
          "Le prochain self-check retentera les adapteurs runtime."
        ],
        metrics: [
          { id: "gateway", label: "Gateway", value: "ERROR", detail: "Payload startup indisponible" },
          { id: "session", label: "Current Session", value: "0", detail: "runs actifs" },
          { id: "daily_cost", label: "Daily Cost", value: "0.00 EUR", detail: "source locale indisponible" },
          { id: "restore", label: "Restore", value: "WATCH", detail: "fallback renderer" }
        ],
        health_cards: [
          {
            id: "desktop_payload",
            label: "Desktop payload",
            status: "error",
            status_badge: "ERROR",
            summary: "Le payload runtime local n'a pas pu etre charge.",
            detail: message,
            actions: [
              { action: "refresh_startup", label: "Relancer le self-check" },
              { action: "open_master_terminal", label: "Rouvrir le terminal maitre" }
            ]
          }
        ],
        actions: [
          { action: "refresh_startup", label: "Relancer le self-check" },
          { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
          { action: "reset_panel_layout", label: "Reset layout" }
        ],
        current_session_items: [],
        recent_run_items: [],
        discord_items: [],
        runtime_facts: [
          { label: "Startup failure", value: message },
          { label: "Terminal surface", value: "encore disponible localement" }
        ]
      },
      session: { operator_question: "Le payload runtime est degrade.", summary_cards: [], clarifications: [], contracts: [], approvals: [], missions: [] },
      runs: { operator_question: "Le payload runtime est degrade.", summary_cards: [], items: [] },
      discord: { operator_question: "Le payload runtime est degrade.", summary_cards: [], gateway: { summary: "Aucune preuve live chargee." }, events: [], deliveries: [] },
      costs: { operator_question: "Le payload runtime est degrade.", note: "Aucun cout n'a pu etre charge.", today: "0.00 EUR", month: "0.00 EUR", current_run: "0.00 EUR", boundary: [], lane_cards: [] },
      conversations: { operator_question: "La memoire conversationnelle locale est degradee.", summary_cards: [], note: "Aucun echange n'a pu etre charge.", pinned_topics: [], weekly_exchanges: [], archive_exchanges: [] },
      terminals: { operator_question: "Le lane terminal reste accessible.", summary_cards: [], persistent_panels: [], layout_mode: "anchored_bottom", monitor_mode: "single_screen" },
      settings: { operator_question: "Aucun workspace complet n'a pu etre lu.", workspace_state_json: "{}" }
    }
  };
}

function renderCodexUsage(payload) {
  const usage = payload.codex_usage_status || {};
  const summary = pickLabel(usage.summary, "indisponible");
  const remaining = pickLabel(usage.remaining_hint, "");
  const suffix = remaining && remaining !== summary ? ` | ${remaining}` : "";
  const estimated = usage.estimated ? " | estimate" : "";
  byId("codex-usage-strip").textContent = `Codex CLI | ${summary}${suffix}${estimated}`;
}

function buildFailurePayload(error) {
  const message = String(error?.message || error || "Erreur inconnue");
  return {
    workspace_state: {
      last_active_tab: "Home",
      theme_variant: "hybrid_luxe",
      motion_mode: "full",
      last_selected_workspace_root: null,
      terminal_layout_mode: "anchored_bottom",
      terminal_dock_preset: "focus",
      preferred_monitor_mode: "single_screen",
      persistent_panels: [],
    },
    codex_usage_status: {
      status: "warning",
      summary: "Le signal runtime local a echoue avant de pouvoir verifier Codex.",
      usage_ratio: null,
      remaining_hint: null,
      estimated: false,
    },
    startup_health: {
      overall_status: "error",
      gateway_status: "error",
      session_restore_status: "warning",
      operator_message: "Le shell est ouvert, mais le payload startup n'a pas pu etre charge. Les actions de reprise restent visibles.",
      actions: [
        { action: "refresh_startup", label: "Relancer le self-check" },
        { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
        { action: "reset_panel_layout", label: "Reset layout" },
      ],
      cards: [
        {
          id: "desktop_payload",
          label: "Desktop payload",
          status: "error",
          status_badge: "ERROR",
          summary: "Le payload runtime local n'a pas pu etre charge.",
          detail: message,
          actions: [
            { action: "refresh_startup", label: "Relancer le self-check" },
            { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
          ],
        },
      ],
    },
    views: {
      home: {
        headline: "Startup desktop en mode degrade",
        summary: "Le shell reste ouvert avec un contrat de reprise lisible.",
        story: [
          "Le renderer n'a pas recu le payload runtime initial.",
          "Le terminal maitre peut encore etre relance localement.",
          "Le prochain self-check retentera les adapteurs runtime.",
        ],
        metrics: [
          { id: "gateway", label: "Gateway", value: "ERROR", detail: "Payload startup indisponible" },
          { id: "session", label: "Current Session", value: "0", detail: "runs actifs" },
          { id: "daily_cost", label: "Daily Cost", value: "0.00 EUR", detail: "source locale indisponible" },
          { id: "restore", label: "Restore", value: "WATCH", detail: "fallback renderer" },
        ],
        startup_checks: [],
        health_cards: [
          {
            id: "desktop_payload",
            label: "Desktop payload",
            status: "error",
            status_badge: "ERROR",
            summary: "Le payload runtime local n'a pas pu etre charge.",
            detail: message,
            actions: [
              { action: "refresh_startup", label: "Relancer le self-check" },
              { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
            ],
          },
        ],
        health_strip: [],
        cost_strip: [],
        actions: [
          { action: "refresh_startup", label: "Relancer le self-check" },
          { action: "open_master_terminal", label: "Rouvrir le terminal maitre" },
          { action: "reset_panel_layout", label: "Reset layout" },
        ],
        current_session_items: [],
        recent_run_items: [],
        discord_items: [],
        runtime_facts: [
          { label: "Startup failure", value: message },
          { label: "Terminal surface", value: "encore disponible localement" },
        ],
        conversation_items: [],
        conversation_note: "Le rappel local reviendra ici des que le payload runtime sera lisible.",
        sidebar: {
          highlights: [],
          roadmaps: [],
          pinned_topics: [],
        },
      },
      session: { operator_question: "Le payload runtime est degrade.", summary_cards: [], clarifications: [], contracts: [], approvals: [], missions: [] },
      runs: { operator_question: "Le payload runtime est degrade.", summary_cards: [], items: [] },
      discord: { operator_question: "Le payload runtime est degrade.", summary_cards: [], gateway: { summary: "Aucune preuve live chargee." }, events: [], deliveries: [] },
      costs: { operator_question: "Le payload runtime est degrade.", note: "Aucun cout n'a pu etre charge.", today: "0.00 EUR", month: "0.00 EUR", current_run: "0.00 EUR", boundary: [], lane_cards: [] },
      conversations: { operator_question: "La memoire conversationnelle locale est degradee.", summary_cards: [], note: "Aucun echange n'a pu etre charge.", pinned_topics: [], weekly_exchanges: [], archive_exchanges: [] },
      terminals: { operator_question: "Le lane terminal reste accessible.", summary_cards: [], persistent_panels: [], layout_mode: "anchored_bottom", monitor_mode: "single_screen" },
      settings: { operator_question: "Aucun workspace complet n'a pu etre lu.", workspace_state_json: "{}" },
    },
  };
}

function renderFailure(error) {
  renderPayload(buildFailurePayload(error));
  setActionNote(String(error?.message || error), "error");
}

function renderTerminalLaunchers() {
  const root = byId("terminal-launchers");
  root.innerHTML = "";
  Object.values(terminalPresets).forEach((preset) => {
    if (!preset || !preset.roleId || preset.roleId === "master_codex") {
      return;
    }
    const button = document.createElement("button");
    button.className = "launcher-button";
    button.type = "button";
    button.textContent = preset.title;
    button.addEventListener("click", async () => {
      const meta = await window.projectOSDesktop.terminals.create({ roleId: preset.roleId });
      await refreshTerminalSessions(meta.terminalId);
      setView("terminals");
    });
    root.appendChild(button);
  });
  refreshInteractiveEffects();
}

async function executeStartupAction(action) {
  const normalized = pickLabel(action, "").trim();
  if (!normalized) {
    return;
  }
  setActionNote(`Action en cours: ${normalized}`, "warning");
  if (normalized === "open_master_terminal") {
    const meta = await window.projectOSDesktop.terminals.create({ roleId: "master_codex" });
    await refreshTerminalSessions(meta.terminalId);
    setActionNote("Le terminal maitre est present dans la zone ancree.", "success");
    return;
  }
  const result = await window.projectOSDesktop.runAction(normalized);
  setActionNote(pickLabel(result.summary, "Action terminee."), result.ok ? "success" : "error");
  await loadStartup({ preserveActionNote: true });
}

function createTerminalView(meta) {
  if (terminalViews.has(meta.terminalId)) {
    return terminalViews.get(meta.terminalId);
  }
  const host = document.createElement("div");
  host.className = "terminal-instance";
  host.dataset.terminalId = meta.terminalId;
  byId("terminal-stage").appendChild(host);

  const terminal = new window.Terminal({
    cursorBlink: true,
    fontFamily: "Cascadia Code, Consolas, monospace",
    fontSize: 14,
    lineHeight: 1.22,
    theme: {
      background: "#030910",
      foreground: "#d9e8f4",
      cursor: "#8ddfff",
      cursorAccent: "#030910",
      black: "#08111a",
      blue: "#6ed2ff",
      cyan: "#8ddfff",
      green: "#8ae5bb",
      yellow: "#e3c49c",
      magenta: "#c8b6ff",
      red: "#ff8d97",
      brightBlack: "#294050",
      brightBlue: "#9ae6ff",
      brightGreen: "#b8f2d4",
      brightCyan: "#c8f4ff",
      brightYellow: "#f1d2a9",
      brightMagenta: "#ddceff",
      brightRed: "#ffb0b7",
      brightWhite: "#ffffff",
      white: "#eef6ff"
    }
  });
  const fitAddon = new window.FitAddon.FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(host);
  terminal.onData((data) => {
    if (activeTerminalId === meta.terminalId) {
      window.projectOSDesktop.terminals.write(meta.terminalId, data);
    }
  });
  const resizeNow = () => {
    fitAddon.fit();
    const dims = terminal.cols && terminal.rows ? { cols: terminal.cols, rows: terminal.rows } : { cols: 120, rows: 24 };
    window.projectOSDesktop.terminals.resize(meta.terminalId, dims.cols, dims.rows);
  };
  const observer = new ResizeObserver(() => {
    if (activeTerminalId === meta.terminalId) {
      resizeNow();
    }
  });
  observer.observe(host);
  const view = { meta, host, terminal, fitAddon, observer, resizeNow };
  terminalViews.set(meta.terminalId, view);
  return view;
}

function renderTerminalTabs() {
  const tabsRoot = byId("terminal-tabs");
  tabsRoot.innerHTML = "";
  terminalSessions.forEach((session) => {
    const button = document.createElement("button");
    button.className = `terminal-tab ${session.terminalId === activeTerminalId ? "active" : ""}`;
    button.type = "button";
    button.textContent = session.title;
    button.addEventListener("click", () => activateTerminal(session.terminalId));
    tabsRoot.appendChild(button);
  });
  byId("terminal-empty").style.display = terminalSessions.length === 0 ? "grid" : "none";
  refreshInteractiveEffects();
}

function activateTerminal(terminalId) {
  activeTerminalId = terminalId;
  terminalViews.forEach((view, viewId) => {
    view.host.classList.toggle("active", viewId === terminalId);
  });
  const activeSession = terminalSessions.find((session) => session.terminalId === terminalId);
  byId("terminal-status-pill").textContent = activeSession ? activeSession.title : "Terminal";
  renderTerminalTabs();
  const view = terminalViews.get(terminalId);
  if (view) {
    setTimeout(() => {
      view.resizeNow();
      view.terminal.focus();
    }, 0);
  }
}

async function refreshTerminalSessions(preferredTerminalId = null) {
  terminalSessions = await window.projectOSDesktop.terminals.list();
  terminalSessions.forEach((session) => {
    createTerminalView(session);
  });
  Array.from(terminalViews.keys()).forEach((terminalId) => {
    if (!terminalSessions.find((item) => item.terminalId === terminalId)) {
      const view = terminalViews.get(terminalId);
      if (view) {
        view.observer.disconnect();
        view.terminal.dispose();
        view.host.remove();
      }
      terminalViews.delete(terminalId);
    }
  });
  renderTerminalTabs();
  const targetId =
    preferredTerminalId ||
    activeTerminalId ||
    (terminalSessions.find((session) => session.roleId === "master_codex") || terminalSessions[0] || {}).terminalId;
  if (targetId) {
    activateTerminal(targetId);
  }
}

function bindTerminalEvents() {
  removeTerminalDataListener = window.projectOSDesktop.terminals.onData((payload) => {
    const view = terminalViews.get(payload.terminalId);
    if (view) {
      view.terminal.write(payload.data);
    }
  });
  removeTerminalExitListener = window.projectOSDesktop.terminals.onExit(async (payload) => {
    const view = terminalViews.get(payload.terminalId);
    if (view) {
      view.terminal.writeln(`\r\n[terminal exited code=${payload.exitCode}]`);
    }
    await refreshTerminalSessions(activeTerminalId === payload.terminalId ? null : activeTerminalId);
  });
}

async function bootstrapTerminals() {
  if (terminalsBootstrapped) {
    return;
  }
  terminalPresets = await window.projectOSDesktop.terminals.presets();
  bindTerminalEvents();
  await refreshTerminalSessions();
  terminalsBootstrapped = true;
}

async function loadStartup(options = {}) {
  try {
    await bootstrapTerminals();
  } catch (error) {
    console.error("Terminal bootstrap failed", error);
    setActionNote(`Bootstrap terminal degrade: ${String(error?.message || error)}`, "warning");
  }
  const payload = await window.projectOSDesktop.runtimePayload();
  renderPayload(payload);
  if (!options.preserveActionNote) {
    setActionNote(payload.startup_health?.operator_message || "Le self-check du matin s'affichera ici.", payload.startup_health?.overall_status === "ok" ? "success" : payload.startup_health?.overall_status || "neutral");
  }
}

applyTabHandlers();
loadStartup().catch(renderFailure);

window.addEventListener("beforeunload", () => {
  if (removeTerminalDataListener) {
    removeTerminalDataListener();
  }
  if (removeTerminalExitListener) {
    removeTerminalExitListener();
  }
});
