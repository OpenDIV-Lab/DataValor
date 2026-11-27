const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const MODULES = {
  home: { title: "首页", description: "查看 Data → Value → Market 各环节的注册规模和运行状态", view: "home" },
  products: { title: "数据产品", description: "登记可估值的数据资产、许可条件和样例记录", view: "products" },
  governance: { title: "治理与权利", description: "核验使用目的、权利约束和敏感字段", view: "module", color: "#2878d0", upstream: [] },
  profile: { title: "数据画像", description: "形成字段、记录量和数据分布画像", view: "module", color: "#168f8a", upstream: ["governance"] },
  evaluation: { title: "质量评估", description: "按数据模态选择 DataValor 质量指标并保留指标语义", view: "module", color: "#2c9a62", upstream: ["governance", "profile"] },
  valuation: { title: "数据估值", description: "选择任务、质量、风险或市场导向的估值方法", view: "module", color: "#7456c8", upstream: ["profile", "evaluation"] },
  pricing: { title: "数据定价", description: "对多个注册产品批量生成合同报价", view: "pricing", color: "#c47a25", upstream: ["evaluation", "valuation"] },
  market: { title: "市场配置", description: "组织多参与者、多产品订单并运行市场机制", view: "market", color: "#c65058", upstream: ["valuation", "pricing"] },
  resources: { title: "运行与产物", description: "查看批次、运行记录和可复用环节产物", view: "resources" },
  components: { title: "方法组件", description: "浏览系统中已经注册的算法、模型和机制实现", view: "components" },
};

const OPERATION_SCHEMAS = {
  governance: [
    { key: "operation", label: "计划用途", type: "select", options: ["analytics", "forecasting", "model_training", "evaluation", "clinical_research", "predictive_maintenance", "investment_research", "risk_monitoring", "energy_trading"], default: "analytics" },
    { key: "jurisdiction", label: "适用地域", type: "select", options: ["CN", "EU", "US", "Global"], default: "CN" },
    { key: "strict_rights", label: "严格执行许可约束", type: "boolean", default: true },
  ],
  profile: [
    { key: "fields", label: "指定画像字段", type: "list", default: [] },
    { key: "sample_size", label: "抽样记录数（留空表示全部）", type: "number", default: "" },
    { key: "include_examples", label: "在画像中保留样例", type: "boolean", default: false },
  ],
};

const OPERATION_LABELS = {
  governance: "治理报告", profile: "画像报告", evaluation: "质量报告",
  valuation: "估值结果", pricing: "报价结果", market: "市场结果",
};

const state = {
  activeModule: "home",
  online: false,
  scenarios: [],
  scenario: null,
  schemas: { evaluation: { modalities: {} }, valuation: { methods: {} }, pricing: {}, market: { mechanisms: {} } },
  products: [],
  participants: [],
  artifacts: [],
  runs: [],
  batches: [],
  components: [],
  dashboard: null,
  moduleSelections: {},
  moduleParameters: {},
  pricingProducts: new Set(),
  selectedMarketParticipants: new Set(),
  selectedMarketProducts: new Set(),
  marketParticipants: [],
  marketOrders: [],
  marketAgentPlan: null,
  expandedAssets: new Set(),
  currentBatch: null,
  currentResult: null,
  editingProductId: null,
  editingParticipantId: null,
  productPreview: null,
};

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function deepCopy(value) { return JSON.parse(JSON.stringify(value ?? {})); }
function asNumber(value, fallback = 0) { const number = Number(value); return Number.isFinite(number) ? number : fallback; }
function listValue(value) { return Array.isArray(value) ? value : String(value || "").split(",").map((item) => item.trim()).filter(Boolean); }
function money(value, currency = "CNY") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
}
function compactNumber(value) { return new Intl.NumberFormat("zh-CN", { notation: Number(value) >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(Number(value || 0)); }
function dateTime(value) { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }

let toastTimer;
function toast(message) {
  const host = $("#toast");
  host.textContent = message;
  host.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => host.classList.remove("show"), 2800);
}

function setBusy(active, message = "正在保存运行结果和产物…") {
  $("#busyMessage").textContent = message;
  $("#busyOverlay").hidden = !active;
}

function setConnection(online, label) {
  state.online = online;
  WorkbenchAPI.online = online;
  const host = $("#apiState");
  host.className = `connection-state ${WorkbenchAPI.mode === "offline" ? "standalone" : online ? "online" : "offline"}`;
  $("span", host).textContent = label;
}

function selectedSet(operation) {
  if (!state.moduleSelections[operation]) state.moduleSelections[operation] = new Set();
  return state.moduleSelections[operation];
}

function selectedProductIds() {
  if (state.activeModule === "pricing") return [...state.pricingProducts];
  if (state.activeModule === "market") return [...state.selectedMarketProducts];
  return [...selectedSet(state.activeModule)];
}

function artifactId(item) { return item.artifact_id || item.id; }
function productById(productId) { return state.products.find((item) => item.product_id === productId); }

function assetRelatedContent(productId) {
  return {
    product: productById(productId),
    artifacts: state.artifacts.filter((item) => item.product_id === productId || (item.product_ids || []).includes(productId)),
    runs: state.runs.filter((item) => item.product_id === productId || (item.product_ids || []).includes(productId)),
  };
}

function assetHistorySeries(productId) {
  const related = assetRelatedContent(productId);
  const series = { quality: [], value: [], price: [] };
  [...related.artifacts].sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || ""))).forEach((artifact) => {
    const payload = artifact.payload || {};
    if (artifact.kind === "evaluation") {
      const values = (payload.metrics || []).filter((item) => Number.isFinite(Number(item.value))).map((item) => item.direction === "lower_is_better" ? 1 - asNumber(item.value) : asNumber(item.value));
      if (values.length) series.quality.push({ at: artifact.created_at, value: values.reduce((sum, value) => sum + value, 0) / values.length, artifact_id: artifactId(artifact) });
    }
    if (artifact.kind === "valuation" && payload.estimates?.[0]?.value !== undefined) series.value.push({ at: artifact.created_at, value: asNumber(payload.estimates[0].value), currency: payload.estimates[0].currency || "CNY", artifact_id: artifactId(artifact) });
    if (artifact.kind === "pricing" && payload.price?.amount !== undefined) series.price.push({ at: artifact.created_at, value: asNumber(payload.price.amount), currency: payload.price.currency || "CNY", artifact_id: artifactId(artifact) });
  });
  if (!series.quality.length && related.product?.metadata?.quality !== undefined) series.quality.push({ at: null, value: asNumber(related.product.metadata.quality), source: "注册信号" });
  if (!series.price.length && related.product?.metadata?.asking_price !== undefined) series.price.push({ at: null, value: asNumber(related.product.metadata.asking_price), currency: related.product.metadata.currency || "CNY", source: "参考报价" });
  return series;
}

function sparkline(points, color) {
  const values = points.map((item) => asNumber(item.value));
  if (!values.length) return '<span class="history-empty">暂无记录</span>';
  const minimum = Math.min(...values); const maximum = Math.max(...values); const range = maximum - minimum || 1;
  const coordinates = values.map((value, index) => `${values.length === 1 ? 64 : 4 + index * (120 / (values.length - 1))},${30 - ((value - minimum) / range) * 24}`).join(" ");
  return `<svg class="history-sparkline" viewBox="0 0 128 36" role="img" aria-label="${values.length} 个历史点"><polyline points="${coordinates}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></polyline>${values.map((value, index) => `<circle cx="${values.length === 1 ? 64 : 4 + index * (120 / (values.length - 1))}" cy="${30 - ((value - minimum) / range) * 24}" r="2.7" fill="${color}"></circle>`).join("")}</svg>`;
}

function renderAssetHistory(productId) {
  const series = assetHistorySeries(productId);
  const definitions = [
    ["quality", "综合质量", "#2c9a62", (value) => value.toFixed(3)],
    ["value", "资产估值", "#7456c8", (value, point) => money(value, point.currency)],
    ["price", "市场报价", "#c47a25", (value, point) => money(value, point.currency)],
  ];
  return `<section class="asset-history"><div class="asset-history-heading"><strong>属性变化</strong><small>由已注册质量、估值与定价产物按时间生成</small></div><div class="asset-history-grid">${definitions.map(([key, label, color, formatter]) => {
    const points = series[key]; const latest = points.at(-1); const previous = points.at(-2); const delta = latest && previous ? latest.value - previous.value : null;
    const deltaLabel = delta === null ? `${points.length} 个观测` : `${delta >= 0 ? "+" : ""}${key === "quality" ? delta.toFixed(3) : money(delta, latest.currency)}`;
    return `<div class="history-card"><span><small>${label}</small><strong>${latest ? formatter(latest.value, latest) : "—"}</strong><em class="${delta === null ? "neutral" : delta >= 0 ? "up" : "down"}">${deltaLabel}</em></span>${sparkline(points, color)}<small>${latest?.at ? dateTime(latest.at) : latest?.source || "尚无环节产物"}</small></div>`;
  }).join("")}</div></section>`;
}

function renderContentPreview(kind, content) {
  if (kind === "data") {
    const records = content.records || [];
    return `<details class="content-preview"><summary><span>原始数据与样例</span><b>${records.length || content.data?.record_count || 0} 条记录</b></summary><div class="preview-body"><dl><dt>URI</dt><dd>${escapeHtml(content.data?.uri || "—")}</dd><dt>格式</dt><dd>${escapeHtml(content.data?.format || "—")}</dd><dt>用途</dt><dd>${escapeHtml((content.rights?.purposes || []).join("、") || "—")}</dd></dl><pre>${escapeHtml(JSON.stringify(records.slice(0, 5), null, 2))}</pre></div></details>`;
  }
  if (kind === "artifact") {
    return `<details class="content-preview"><summary><span>${escapeHtml(OPERATION_LABELS[content.kind] || content.kind)} · ${escapeHtml(content.producer || "已注册产物")}</span><b>${dateTime(content.created_at)}</b></summary><div class="preview-body"><p>产物 ID：${escapeHtml(artifactId(content))}</p><pre>${escapeHtml(JSON.stringify(content.payload, null, 2))}</pre></div></details>`;
  }
  return `<details class="content-preview"><summary><span>运行记录 · ${escapeHtml(OPERATION_LABELS[content.operation] || content.operation)}</span><b>${escapeHtml(content.status)} · ${content.duration_ms ?? "—"} ms</b></summary><div class="preview-body"><dl><dt>Run ID</dt><dd>${escapeHtml(content.run_id)}</dd><dt>实现</dt><dd>${escapeHtml(content.producer || "—")}</dd><dt>产物</dt><dd>${escapeHtml(content.artifact_id || "—")}</dd></dl><pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre></div></details>`;
}

function renderAssetDossiers(products, selected, prefix) {
  if (!products.length) return '<div class="empty-inline">没有已注册资产。请先在“数据产品”中登记。</div>';
  return products.map((product) => {
    const related = assetRelatedContent(product.product_id);
    const assetKey = `${prefix}:${product.product_id}`; const expanded = state.expandedAssets.has(assetKey);
    return `<article class="asset-dossier ${selected.has(product.product_id) ? "selected" : ""} ${expanded ? "expanded" : "collapsed"}" data-asset-key="${escapeHtml(assetKey)}">
      <div class="asset-dossier-head"><label><input type="checkbox" data-${prefix}-product="${escapeHtml(product.product_id)}" ${selected.has(product.product_id) ? "checked" : ""}><span class="selection-icon">◇</span><span><strong>${escapeHtml(product.title || product.product_id)}</strong><small>${escapeHtml(product.owner_id)} · ${compactNumber(product.data?.record_count || product.records?.length)} 条记录</small></span><em>${related.artifacts.length} 个产物 · ${related.runs.length} 次运行</em></label><button type="button" data-toggle-asset-content="${escapeHtml(assetKey)}" aria-expanded="${expanded}">${expanded ? "收起内容" : "展开内容"}</button></div>
      <div class="asset-content-stack" ${expanded ? "" : "hidden"}>${renderAssetHistory(product.product_id)}${renderContentPreview("data", product)}${related.artifacts.map((item) => renderContentPreview("artifact", item)).join("")}${related.runs.map((item) => renderContentPreview("run", item)).join("")}</div>
    </article>`;
  }).join("");
}

function renderScenarioOptions() {
  $("#scenarioSelect").innerHTML = state.scenarios.map((scenario) => `<option value="${escapeHtml(scenario.scenario_id)}">${escapeHtml(scenario.name)}</option>`).join("");
}

function applyScenario(scenarioId) {
  state.scenario = state.scenarios.find((item) => item.scenario_id === scenarioId) || state.scenarios[0] || null;
  if (!state.scenario) return;
  $("#scenarioSelect").value = state.scenario.scenario_id;
  $("#scenarioRailSummary").textContent = state.scenario.summary;
  const defaults = state.scenario.operation_parameters || {};
  for (const operation of ["governance", "profile", "evaluation", "valuation"]) {
    state.moduleParameters[operation] = deepCopy(defaults[operation] || {});
    const ids = state.scenario.products.map((item) => item.product_id).filter((id) => productById(id));
    state.moduleSelections[operation] = new Set(ids);
  }
  state.moduleParameters.pricing = deepCopy(defaults.pricing || {});
  state.moduleParameters.market = deepCopy(defaults.market || {});
  state.pricingProducts = new Set(state.scenario.products.map((item) => item.product_id).filter((id) => productById(id)));
  hydrateMarketState(defaults.market || {});
  renderActiveView();
}

async function loadScenarioRegistry(showToast = true) {
  if (!state.scenario) return;
  const response = await WorkbenchAPI.post(`/workbench/scenarios/${state.scenario.scenario_id}/load`);
  await refreshRegistry();
  applyScenario(state.scenario.scenario_id);
  if (showToast) toast(`已登记 ${response.product_ids.length} 个产品和 ${response.participants_registered} 个参与者`);
}

function updateHeader(module) {
  const meta = MODULES[module];
  $("#pageTitle").textContent = meta.title;
  $("#pageDescription").textContent = meta.description;
  const executable = ["governance", "profile", "evaluation", "valuation", "pricing", "market"].includes(module);
  $("#runBatch").hidden = !executable;
  $("#runBatch").disabled = executable && !state.online;
  $("#runBatch").title = executable && !state.online ? "算法执行需要启动 DataValor Python 服务" : "";
  $("#runBatch").textContent = module === "pricing" ? "批量生成报价" : module === "market" ? "运行市场机制" : "运行当前环节";
  $("#exportBatch").disabled = !state.currentResult;
}

function openModule(module) {
  if (!MODULES[module]) return;
  state.activeModule = module;
  $$('[data-module-target]').forEach((button) => button.classList.toggle("active", button.dataset.moduleTarget === module));
  $$(".workspace-view").forEach((view) => view.classList.remove("active"));
  $(`#${MODULES[module].view}View`)?.classList.add("active");
  updateHeader(module);
  renderActiveView();
}

function renderActiveView() {
  const module = state.activeModule;
  if (module === "home") renderHome();
  else if (module === "products") renderProductsView();
  else if (["governance", "profile", "evaluation", "valuation"].includes(module)) renderModuleWorkspace(module);
  else if (module === "pricing") renderPricingWorkspace();
  else if (module === "market") renderMarketWorkspace();
  else if (module === "resources") renderResourcesView();
  else if (module === "components") renderComponentsView();
  updateHeader(module);
}

function moduleStat(name) { return state.dashboard?.modules?.[name] || {}; }

function renderHome() {
  const summary = state.dashboard?.summary || {};
  $("#homeHeadlineStats").innerHTML = [
    ["已注册产品", summary.products || 0], ["总记录量", compactNumber(summary.total_records)],
    ["市场参与者", summary.participants || 0], ["环节产物", summary.artifacts || 0],
  ].map(([label, value]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join("");

  const nodes = [
    ["products", "数据产品", `${moduleStat("products").registered || 0} 个产品`, `${compactNumber(moduleStat("products").total_records)} 条记录`],
    ["governance", "治理与权利", `${moduleStat("governance").registered || 0} 份报告`, "用途与许可核验"],
    ["profile", "数据画像", `${moduleStat("profile").registered || 0} 份画像`, "结构与分布证据"],
    ["evaluation", "质量评估", `${moduleStat("evaluation").registered || 0} 份报告`, "质量与任务适配"],
    ["valuation", "数据估值", `${moduleStat("valuation").registered || 0} 个结果`, `累计 ${money(moduleStat("valuation").total_value)}`],
    ["pricing", "数据定价", `${moduleStat("pricing").registered || 0} 份报价`, `累计 ${money(moduleStat("pricing").total_price)}`],
    ["market", "市场配置", `${moduleStat("market").participants || 0} 个参与者`, `${moduleStat("market").allocations || 0} 次分配`],
  ];
  $("#pipelineStages").innerHTML = nodes.map(([key, title, primary, secondary], index) => `
    <button class="map-node node-${key}" data-module-target="${key}">
      <span>${String(index + 1).padStart(2, "0")}</span><strong>${title}</strong><b>${primary}</b><small>${secondary}</small>
    </button>${index < nodes.length - 1 ? '<i class="map-link">→</i>' : ""}`).join("");
  renderCaseBrief();
  const recent = state.dashboard?.recent_runs || [];
  $("#homeRecentRuns").innerHTML = recent.length ? recent.map((run) => `<button data-module-target="resources"><span><strong>${escapeHtml(OPERATION_LABELS[run.operation] || run.operation)}</strong><small>${escapeHtml((run.product_ids || [run.product_id]).filter(Boolean).join("、"))}</small></span><span><b>${escapeHtml(run.status)}</b><small>${dateTime(run.finished_at)}</small></span></button>`).join("") : '<div class="empty-inline">还没有运行记录。</div>';
  $("#homeRegistrySummary").innerHTML = `
    <div><span class="registry-dot product"></span><p><strong>${summary.products || 0} 个数据产品</strong><small>${compactNumber(summary.total_records)} 条注册记录</small></p></div>
    <div><span class="registry-dot participant"></span><p><strong>${summary.participants || 0} 个市场参与者</strong><small>买方、卖方及市场角色</small></p></div>
    <div><span class="registry-dot artifact"></span><p><strong>${summary.artifacts || 0} 个环节产物</strong><small>可作为下游输入依据</small></p></div>
    <div><span class="registry-dot run"></span><p><strong>${summary.runs || 0} 次可追溯运行</strong><small>${summary.batches || 0} 个执行批次</small></p></div>`;
  updateNavigationCounts();
}

function renderCaseBrief() {
  const scenario = state.scenario;
  if (!scenario) {
    $("#caseBrief").innerHTML = '<div class="empty-inline">请选择一个业务场景。</div>';
    return;
  }
  const context = scenario.business_context || {};
  const participants = scenario.participants || scenario.offline_participants || [];
  const buyers = participants.filter((item) => item.role === "buyer");
  const sellers = participants.filter((item) => item.role === "seller");
  const sourceGrounded = scenario.evidence_level === "source_grounded_sample";
  $("#caseEvidence").className = `status-pill ${sourceGrounded ? "ready" : "neutral"}`;
  $("#caseEvidence").textContent = sourceGrounded ? "来源可核验样本" : "合成工作流";
  const dimensions = (context.metric_dimensions || []).map((item) => `<li><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.meaning)}</span></li>`).join("");
  const steps = (context.process_steps || []).map((step, index) => `<li><b>${index + 1}</b><span>${escapeHtml(step)}</span></li>`).join("");
  const sources = (scenario.sources || []).map((source) => `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer"><strong>${escapeHtml(source.dataset)}</strong><small>${escapeHtml(source.publisher)} · ${escapeHtml(source.license)}</small></a>`).join("");
  $("#caseBrief").innerHTML = `
    <div class="case-decision">
      <p class="case-domain">${escapeHtml(scenario.domain || "数据市场应用")}</p>
      <h3>${escapeHtml(scenario.name)}</h3>
      <p>${escapeHtml(scenario.decision || scenario.summary)}</p>
      <dl><div><dt>需求方</dt><dd>${escapeHtml(scenario.buyer || buyers.map((item) => item.name).join("、") || "—")}</dd></div><div><dt>资产</dt><dd>${scenario.products?.length || 0} 个数据产品</dd></div><div><dt>市场</dt><dd>${buyers.length} 个买方 · ${sellers.length} 个卖方</dd></div><div><dt>决策节奏</dt><dd>${escapeHtml(context.cadence || "按任务配置")}</dd></div></dl>
      <button type="button" data-module-target="governance">从治理与权利开始</button>
    </div>
    <div class="case-detail"><h4>真实需求</h4><p>${escapeHtml(context.demand || scenario.summary)}</p><h4>采购决策指标</h4><p>${escapeHtml(context.decision_metric || "按场景配置的质量、效用与市场指标")}</p><ul class="case-metrics">${dimensions || "<li><span>载入场景后按各环节配置指标。</span></li>"}</ul></div>
    <div class="case-process"><h4>业务过程</h4><ol>${steps || "<li><b>1</b><span>载入资产并按环节执行。</span></li>"}</ol></div>
    <div class="case-sources"><h4>数据与依据</h4>${sources || `<p>${escapeHtml(scenario.data_notice || "场景数据用于工作流验证。")}</p>`}<p class="assumption-note">${escapeHtml(scenario.assumptions?.note || scenario.data_notice || "")}</p></div>`;
}

function updateNavigationCounts() {
  const values = {
    Products: state.products.length, Governance: moduleStat("governance").registered || 0,
    Profile: moduleStat("profile").registered || 0, Evaluation: moduleStat("evaluation").registered || 0,
    Valuation: moduleStat("valuation").registered || 0, Pricing: moduleStat("pricing").registered || 0,
    Market: state.participants.length, Resources: state.artifacts.length, Components: state.components.length,
  };
  Object.entries(values).forEach(([key, value]) => { const node = $(`#nav${key}Count`); if (node) node.textContent = value; });
}

function normalizeFieldValue(field, value) {
  if (value !== undefined && value !== null) return value;
  return deepCopy(field.default);
}

function optionParts(option) {
  if (typeof option === "object") return { value: option.value ?? option.name, label: option.label ?? option.value ?? option.name };
  return { value: option, label: option };
}

function fieldMarkup(field, value, scope) {
  value = normalizeFieldValue(field, value);
  const attrs = `data-config-scope="${scope}" data-config-key="${field.key}" data-field-type="${field.type}"${field.capability ? ` data-capability="${field.capability}"` : ""}`;
  if (field.type === "boolean") return `<label class="check-field"><input type="checkbox" ${attrs} ${value ? "checked" : ""}>${escapeHtml(field.label)}</label>`;
  if (field.type === "select") return `<label class="${field.wide ? "wide-field" : ""}">${escapeHtml(field.label)}<select ${attrs}>${(field.options || []).map((option) => { const item = optionParts(option); return `<option value="${escapeHtml(item.value)}" ${String(item.value) === String(value) ? "selected" : ""}>${escapeHtml(item.label)}</option>`; }).join("")}</select>${field.hint ? `<small class="field-hint">${escapeHtml(field.hint)}</small>` : ""}</label>`;
  if (field.type === "checkbox_group") return `<fieldset class="wide-field config-choice-group" data-config-scope="${scope}" data-config-group="${field.key}"><legend>${escapeHtml(field.label)}</legend><p>${escapeHtml(field.hint || "可同时选择多个指标")}</p><div>${(field.options || []).map((option) => { const item = optionParts(option); const checked = (value || []).includes(item.value); return `<label class="metric-choice ${checked ? "selected" : ""}"><input type="checkbox" value="${escapeHtml(item.value)}" ${checked ? "checked" : ""}><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(option.description || item.value)}</small><em>${escapeHtml(option.direction || "")}</em></span></label>`; }).join("")}</div></fieldset>`;
  if (field.type === "json") return `<label class="wide-field">${escapeHtml(field.label)}<textarea rows="4" ${attrs} spellcheck="false">${escapeHtml(JSON.stringify(value, null, 2))}</textarea></label>`;
  if (["list", "number_list"].includes(field.type)) return `<label class="wide-field">${escapeHtml(field.label)}<input ${attrs} value="${escapeHtml((value || []).join(", "))}" placeholder="以逗号分隔"></label>`;
  return `<label>${escapeHtml(field.label)}<input type="${field.type === "number" ? "number" : "text"}" ${attrs} value="${escapeHtml(value)}" ${field.min !== undefined ? `min="${field.min}"` : ""} ${field.max !== undefined ? `max="${field.max}"` : ""} step="${field.step || "any"}"></label>`;
}

function controlValue(control) {
  const type = control.dataset.fieldType;
  if (type === "boolean") return control.checked;
  if (type === "number") return control.value === "" ? null : asNumber(control.value);
  if (["list", "number_list"].includes(type)) return listValue(control.value).map((item) => type === "number_list" ? asNumber(item) : item);
  if (type === "json") {
    try { return JSON.parse(control.value || "{}"); } catch (error) { throw new Error(`${control.closest("label")?.firstChild?.textContent || "JSON 参数"}格式错误：${error.message}`); }
  }
  return control.value;
}

function operationFields(operation, parameters) {
  if (operation === "evaluation") {
    const evaluation = state.schemas.evaluation || { modalities: {} };
    const modality = parameters.modality || evaluation.default_modality || Object.keys(evaluation.modalities || {})[0] || "tabular";
    const schema = evaluation.modalities?.[modality] || { fields: [], metrics: [] };
    parameters.modality = modality;
    if (!Array.isArray(parameters.metrics)) parameters.metrics = schema.metrics.filter((item) => item.default).map((item) => item.name);
    return [
      { key: "modality", capability: "evaluation.modality", label: "数据模态", type: "select", wide: true, default: modality, options: Object.entries(evaluation.modalities || {}).map(([value, item]) => ({ value, label: item.label })), hint: schema.description },
      { key: "metrics", label: "质量指标", type: "checkbox_group", default: parameters.metrics, options: schema.metrics, hint: `输入约定：${schema.expected_fields || "记录字段"}` },
      ...(schema.fields || []),
    ];
  }
  if (operation === "valuation") {
    const valuation = state.schemas.valuation || { methods: {} };
    const method = parameters.method || valuation.default_method || Object.keys(valuation.methods || {})[0] || "valuation.weighted_user_task";
    const schema = valuation.methods?.[method] || { fields: [] };
    parameters.method = method;
    return [
      { key: "method", capability: "valuation.method", label: "估值方法", type: "select", wide: true, default: method, options: Object.entries(valuation.methods || {}).map(([value, item]) => ({ value, label: item.label })), hint: `${schema.description || ""} · ${schema.implementation || ""}` },
      ...(schema.fields || []),
    ];
  }
  return OPERATION_SCHEMAS[operation] || [];
}

function renderModuleWorkspace(operation) {
  const selectedProducts = selectedSet(operation);
  const meta = MODULES[operation];
  $("#moduleProductRows").innerHTML = renderAssetDossiers(state.products, selectedProducts, "module");
  $("#moduleConfigTitle").textContent = `${meta.title}配置`;
  $("#moduleConfigHint").textContent = meta.description;
  const parameters = state.moduleParameters[operation] || (state.moduleParameters[operation] = {});
  $("#moduleConfigFields").innerHTML = operationFields(operation, parameters).map((field) => fieldMarkup(field, parameters[field.key], operation)).join("");
  $$('[data-module-product]').forEach((input) => input.addEventListener("change", () => { input.checked ? selectedProducts.add(input.dataset.moduleProduct) : selectedProducts.delete(input.dataset.moduleProduct); input.closest(".asset-dossier")?.classList.toggle("selected", input.checked); updateModuleRunSummary(operation); }));
  bindConfigInputs($("#moduleConfigFields"));
  updateModuleRunSummary(operation);
}

function bindConfigInputs(root) {
  $$('[data-config-key]', root).forEach((control) => control.addEventListener("change", () => {
    try {
      const scope = control.dataset.configScope;
      state.moduleParameters[scope] ||= {};
      const key = control.dataset.configKey; const value = controlValue(control);
      if (scope === "evaluation" && key === "modality") state.moduleParameters[scope] = { modality: value };
      else if (scope === "valuation" && key === "method") state.moduleParameters[scope] = { method: value, base_value: state.moduleParameters[scope].base_value, currency: state.moduleParameters[scope].currency };
      else state.moduleParameters[scope][key] = value;
      if ((scope === "evaluation" && key === "modality") || (scope === "valuation" && key === "method")) renderModuleWorkspace(scope);
    } catch (error) { toast(error.message); }
  }));
  $$('[data-config-group]', root).forEach((group) => {
    $$('input[type="checkbox"]', group).forEach((control) => control.addEventListener("change", () => {
      const scope = group.dataset.configScope; const key = group.dataset.configGroup;
      state.moduleParameters[scope] ||= {};
      state.moduleParameters[scope][key] = $$('input:checked', group).map((input) => input.value);
      control.closest(".metric-choice")?.classList.toggle("selected", control.checked);
    }));
  });
}

function collectConfigInputs(operation) {
  $$('[data-config-key]', $("#moduleConfigFields")).forEach((control) => { state.moduleParameters[operation][control.dataset.configKey] = controlValue(control); });
  $$('[data-config-group]', $("#moduleConfigFields")).forEach((group) => { state.moduleParameters[operation][group.dataset.configGroup] = $$('input:checked', group).map((input) => input.value); });
}

function updateModuleRunSummary(operation) {
  const products = selectedSet(operation).size;
  const contents = [...selectedSet(operation)].reduce((total, productId) => total + assetRelatedContent(productId).artifacts.length + assetRelatedContent(productId).runs.length, 0);
  $("#moduleRunSummary").textContent = products ? `${products} 个资产 · 自动携带 ${contents} 项相关内容 · 将生成 ${products} 个${OPERATION_LABELS[operation]}` : "请选择至少一个资产";
  $("#moduleRun").disabled = !state.online || !products;
  $("#selectionSummary").textContent = `${products} 个资产 · ${contents} 项关联内容`;
}

async function runModuleOperation() {
  const operation = state.activeModule;
  const productIds = [...selectedSet(operation)];
  if (!productIds.length) return;
  try {
    collectConfigInputs(operation);
  } catch (error) { return toast(error.message); }
  setBusy(true, `正在为 ${productIds.length} 个产品执行${MODULES[operation].title}…`);
  try {
    const response = await WorkbenchAPI.post("/batches", {
      product_ids: productIds, operations: [operation], parameters: { [operation]: state.moduleParameters[operation] },
      label: `${MODULES[operation].title} · ${state.scenario?.name || "自定义批次"}`,
      scenario_id: state.scenario?.scenario_id, seed: asNumber($("#seedInput").value), fail_fast: $("#failFast").checked,
      include_related_content: true,
    });
    state.currentBatch = response.batch; state.currentResult = response.batch;
    await refreshRegistry(false);
    renderModuleWorkspace(operation);
    renderModuleResult(response.batch, operation);
    toast(`执行完成：已注册 ${response.batch.summary.succeeded_stages} 个产物`);
  } catch (error) { toast(`执行失败：${error.message}`); }
  finally { setBusy(false); }
}

function resultCards(cards) {
  return cards.map(([label, value, note]) => `<div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value ?? "—")}</strong><span>${escapeHtml(note || "")}</span></div>`).join("");
}

function tableResult(headers, rows) {
  if (!rows.length) return '<div class="empty-inline">该结果没有明细行。</div>';
  return `<div class="table-wrap"><table><thead><tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((item) => `<td>${escapeHtml(item ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function renderGovernanceResult(result) {
  const findings = result.security?.findings || [];
  const reasons = result.reasons || result.violations || [];
  return {
    cards: [["权利判断", result.decision || "—", "许可策略输出"], ["敏感字段", findings.length, `${result.security?.scanned_fields?.length || 0} 个字段已扫描`], ["约束 / 原因", reasons.length, "影响准入判断"], ["元数据字段", Object.keys(result.metadata?.attributes || result.metadata || {}).length, "已提取元数据"]],
    html: `<section class="result-section"><h3>准入判断依据</h3>${tableResult(["类型", "字段 / 规则", "说明"], [...findings.map((item) => ["敏感字段", item.field_name, item.kind || item.message]), ...reasons.map((item) => ["许可约束", item.code || "rule", item.message || item])])}</section>${renderContentPreview("artifact", { kind: "governance", producer: "完整治理报告", payload: result })}`,
  };
}

function renderProfileResult(result) {
  const fields = result.fields || [];
  return {
    cards: [["记录数", result.record_count || 0, "实际画像记录"], ["字段数", result.field_count ?? fields.length, "已识别字段"], ["样本数", result.properties?.sample_size || result.record_count || 0, result.properties?.sampled ? "抽样画像" : "全量画像"], ["实现", result.diagnostics?.backend || "basic.data_profiler", "画像执行实现"]],
    html: `<section class="result-section"><h3>字段画像</h3>${tableResult(["字段", "推断类型", "非空", "缺失", "唯一值", "分布示例"], fields.map((item) => [item.name, item.inferred_type || item.data_type || item.type, (item.count ?? 0) - (item.missing_count ?? 0), item.missing_count ?? 0, item.distinct_count ?? item.unique_count, Object.entries(item.distribution || {}).slice(0, 2).map(([key, value]) => `${key}: ${value}`).join("；")]))}</section>${renderContentPreview("artifact", { kind: "profile", producer: "完整画像报告", payload: result })}`,
  };
}

function renderEvaluationResult(result) {
  const metrics = result.metrics || [];
  const modality = result.diagnostics?.modality || "tabular";
  const schema = state.schemas.evaluation?.modalities?.[modality] || {};
  const definitions = Object.fromEntries((schema.metrics || []).map((item) => [item.name, item]));
  const normalized = metrics.map((item) => {
    const value = asNumber(item.value, NaN); if (!Number.isFinite(value) || value < 0 || value > 1) return null;
    if (item.direction === "higher_is_better") return value;
    if (item.direction === "lower_is_better") return 1 - value;
    return null;
  }).filter((value) => value !== null);
  const quality = normalized.length ? normalized.reduce((sum, value) => sum + value, 0) / normalized.length : null;
  const failures = result.diagnostics?.failures || [];
  const directionLabel = { higher_is_better: "越高越好", lower_is_better: "越低越好", target_is_best: "接近目标最好", descriptive: "描述性" };
  return {
    cards: [["数据模态", schema.label || modality, schema.expected_fields || "按记录评估"], ["方向归一质量", quality === null ? "—" : quality.toFixed(3), normalized.length ? `${normalized.length} 个 [0,1] 可比指标` : "无可聚合指标"], ["完成指标", metrics.length, failures.length ? `${failures.length} 个指标失败` : "全部完成"], ["执行状态", result.summary?.status || result.status || "succeeded", "DataValor CompositeEvaluator"]],
    html: `<section class="result-section"><h3>质量指标及解释</h3>${tableResult(["指标", "质量维度", "数值", "方向", "含义 / 统计"], metrics.map((item) => { const definition = definitions[item.name] || {}; const statistics = Object.entries(item.statistics || {}).slice(0, 3).map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`).join("；"); return [definition.label || item.name || item.metric, item.dimension, item.value, directionLabel[item.direction] || item.direction, `${definition.description || "DataValor 指标"}${statistics ? `；${statistics}` : ""}`]; }))}</section>${failures.length ? `<section class="result-section"><h3>未完成指标</h3>${tableResult(["指标", "错误类型", "原因"], failures.map((item) => [item.metric, item.error_type, item.message]))}</section>` : ""}${renderContentPreview("artifact", { kind: "evaluation", producer: "完整质量报告", payload: result })}`,
  };
}

function renderValuationResult(result) {
  const estimates = result.estimates || [];
  const method = result.method || result.valuator || "valuation.weighted_user_task";
  const schema = state.schemas.valuation?.methods?.[method] || {};
  const values = estimates.map((item) => asNumber(item.value, NaN)).filter(Number.isFinite);
  const range = values.length ? `${money(Math.min(...values), estimates[0]?.currency)} – ${money(Math.max(...values), estimates[0]?.currency)}` : "—";
  return {
    cards: [["估值方法", schema.label || method, schema.description || "实际执行实现"], ["价值范围", range, estimates.length > 1 ? "多目标或多情景范围" : "当前资产估计"], ["估值对象", estimates.length, result.mode || "task_specific"], ["实现", method, schema.implementation || "datavalor.data_value"]],
    html: `<section class="result-section"><h3>估值明细与分解</h3>${tableResult(["目标 / 情景", "价值", "币种", "价值分解", "方法说明"], estimates.map((item) => [item.target_id || item.product_id, item.value, item.currency, Object.entries(item.components || {}).map(([key, value]) => `${key}=${value}`).join("；"), Object.entries(item.explanation || {}).map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`).join("；")]))}</section>${renderContentPreview("artifact", { kind: "valuation", producer: schema.label || method, payload: result })}`,
  };
}

function structuredOperationResult(operation, result) {
  return { governance: renderGovernanceResult, profile: renderProfileResult, evaluation: renderEvaluationResult, valuation: renderValuationResult }[operation](result || {});
}

function renderModuleResult(batch, operation) {
  $("#moduleResult").dataset.view = "execution trace";
  $("#moduleResultStatus").textContent = batch.status === "succeeded" ? "执行成功" : "需要检查";
  $("#moduleResultStatus").className = `status-pill ${batch.status}`;
  $("#resultCompare").innerHTML = batch.items.map((item, index) => {
    const stage = item.stages.find((candidate) => candidate.operation === operation);
    return `<button class="result-row ${index === 0 ? "active" : ""}" data-module-result="${escapeHtml(item.product_id)}"><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(stage?.producer || stage?.error?.message || "未执行")}</small></span><span><b>${escapeHtml(stage?.status || item.status)}</b><small>${stage?.duration_ms || 0} ms</small></span></button>`;
  }).join("");
  const show = (productId) => {
    const item = batch.items.find((candidate) => candidate.product_id === productId);
    const stage = item?.stages.find((candidate) => candidate.operation === operation);
    const structured = structuredOperationResult(operation, stage?.result || {});
    $("#moduleResultSummary").innerHTML = resultCards(structured.cards);
    $("#moduleResultDetails").innerHTML = structured.html;
    $("#moduleResult").textContent = JSON.stringify(item, null, 2);
  };
  $$('[data-module-result]').forEach((button) => button.addEventListener("click", () => { $$('[data-module-result]').forEach((node) => node.classList.toggle("active", node === button)); show(button.dataset.moduleResult); }));
  if (batch.items[0]) show(batch.items[0].product_id);
  $("#exportBatch").disabled = false;
}

function renderPricingOptions() {
  const options = Object.values(state.schemas.pricing || {});
  $("#pricingModel").innerHTML = options.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label)} · ${escapeHtml(item.name)}</option>`).join("");
  const configured = state.moduleParameters.pricing?.model;
  if (configured && state.schemas.pricing[configured]) $("#pricingModel").value = configured;
  else if (options[0]) state.moduleParameters.pricing = { model: options[0].name };
}

function renderPricingFields() {
  const modelName = $("#pricingModel").value || state.moduleParameters.pricing?.model;
  const schema = state.schemas.pricing?.[modelName];
  if (!schema) { $("#pricingConfigFields").innerHTML = '<div class="empty-inline">没有可用定价模型。</div>'; return; }
  const parameters = state.moduleParameters.pricing || (state.moduleParameters.pricing = {});
  parameters.model = modelName;
  $("#pricingConfigFields").innerHTML = schema.fields.map((field) => fieldMarkup(field, parameters[field.key], "pricing")).join("");
  bindConfigInputs($("#pricingConfigFields"));
}

function renderPricingWorkspace() {
  renderPricingOptions();
  renderPricingFields();
  $("#pricingProductRows").innerHTML = renderAssetDossiers(state.products, state.pricingProducts, "pricing");
  $$('[data-pricing-product]').forEach((input) => input.addEventListener("change", () => { input.checked ? state.pricingProducts.add(input.dataset.pricingProduct) : state.pricingProducts.delete(input.dataset.pricingProduct); input.closest(".asset-dossier")?.classList.toggle("selected", input.checked); updatePricingSummary(); }));
  updatePricingSummary();
}

function updatePricingSummary() {
  const contents = [...state.pricingProducts].reduce((total, productId) => total + assetRelatedContent(productId).artifacts.length + assetRelatedContent(productId).runs.length, 0);
  $("#pricingRunSummary").textContent = state.pricingProducts.size ? `${state.pricingProducts.size} 个资产 · ${contents} 项关联内容 · ${$("#pricingModel").value}` : "请选择至少一个资产";
  $("#pricingRun").disabled = !state.online || !state.pricingProducts.size;
  $("#selectionSummary").textContent = `${state.pricingProducts.size} 个定价对象`;
}

async function runPricingBatch() {
  if (!state.pricingProducts.size) return;
  try { $$('[data-config-key]', $("#pricingConfigFields")).forEach((control) => { state.moduleParameters.pricing[control.dataset.configKey] = controlValue(control); }); }
  catch (error) { return toast(error.message); }
  setBusy(true, `正在为 ${state.pricingProducts.size} 个产品生成报价…`);
  try {
    const response = await WorkbenchAPI.post("/batches", {
      product_ids: [...state.pricingProducts], operations: ["pricing"], parameters: { pricing: state.moduleParameters.pricing },
      label: `批量定价 · ${state.scenario?.name || "自定义"}`, scenario_id: state.scenario?.scenario_id,
      seed: asNumber($("#seedInput").value), fail_fast: $("#failFast").checked, include_related_content: true,
    });
    state.currentBatch = response.batch; state.currentResult = response.batch;
    await refreshRegistry(false); renderPricingWorkspace(); renderPricingResult(response.batch); toast("报价已生成并注册");
  } catch (error) { toast(`定价失败：${error.message}`); } finally { setBusy(false); }
}

function renderPricingResult(batch) {
  $("#pricingResult").innerHTML = batch.items.map((item) => {
    const stage = item.stages.find((candidate) => candidate.operation === "pricing");
    const result = stage?.result || {};
    return `<article class="pricing-result-card"><div class="pricing-result-row"><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.product_id)} · ${escapeHtml(stage?.producer || "—")}</small></div><div><small>参考报价</small><strong>${money(item.metrics.asking_price, item.metrics.asking_price_currency)}</strong></div><div><small>模型报价</small><strong>${money(item.metrics.price, item.metrics.price_currency)}</strong></div><div><small>与参考价差额</small><strong>${money(asNumber(item.metrics.price) - asNumber(item.metrics.asking_price), item.metrics.price_currency)}</strong></div><span class="item-status ${item.status}">${escapeHtml(item.status)}</span></div><details class="pricing-breakdown"><summary>展开报价构成、参数和执行轨迹</summary><div class="result-split"><div><h3>报价构成</h3><pre>${escapeHtml(JSON.stringify({ price: result.price, components: result.components, constraints: result.applied_constraints }, null, 2))}</pre></div><div><h3>参数与轨迹</h3><pre>${escapeHtml(JSON.stringify({ normalized_parameters: result.normalized_parameters, trace: result.trace }, null, 2))}</pre></div></div></details></article>`;
  }).join("");
  $("#exportBatch").disabled = false;
}

function hydrateMarketState(parameters) {
  const participantIds = new Set();
  state.marketOrders = [];
  (parameters.bids || []).forEach((bid, index) => {
    participantIds.add(bid.buyer_id);
    state.marketOrders.push({ order_id: bid.bid_id || `bid-${index + 1}`, side: "bid", participant_id: bid.buyer_id, product_ids: [...(bid.product_ids || [])], amount: asNumber(bid.amount), quantity: asNumber(bid.quantity, 1), currency: bid.currency || "CNY", bundle_mode: bid.constraints?.bundle_mode || "single" });
  });
  (parameters.asks || []).forEach((ask, index) => {
    participantIds.add(ask.seller_id);
    state.marketOrders.push({ order_id: ask.ask_id || `ask-${index + 1}`, side: "ask", participant_id: ask.seller_id, product_ids: [...(ask.product_ids || [])], amount: asNumber(ask.reserve), quantity: asNumber(ask.quantity, 1), currency: ask.currency || "CNY", bundle_mode: ask.constraints?.bundle_mode || "single" });
  });
  state.selectedMarketParticipants = new Set([...participantIds].filter((id) => state.participants.some((item) => item.participant_id === id)));
  const ids = state.scenario?.products?.map((item) => item.product_id).filter((id) => productById(id)) || [];
  state.selectedMarketProducts = new Set(ids);
  state.marketParticipants = state.participants;
  state.marketAgentPlan = null;
}

function renderMarketWorkspace() {
  renderMarketOptions();
  renderMarketParticipants();
  renderMarketProducts();
  renderMarketOrders();
  renderMarketSummary();
  renderAgentPlan(state.marketAgentPlan);
}

function renderMarketOptions() {
  const mechanisms = Object.values(state.schemas.market?.mechanisms || {});
  $("#marketMechanism").innerHTML = mechanisms.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label)}</option>`).join("");
  const configured = state.moduleParameters.market?.mechanism;
  if (configured && state.schemas.market.mechanisms[configured]) $("#marketMechanism").value = configured;
  $("#marketBudget").value = state.moduleParameters.market?.budget ?? 0;
}

function renderMarketParticipants() {
  const selectedMarketParticipants = state.selectedMarketParticipants;
  const renderRole = (role) => {
    const participants = state.participants.filter((item) => item.role === role);
    if (!participants.length) return `<div class="empty-inline">暂无${role === "buyer" ? "买家" : "卖家"}，请先注册。</div>`;
    return participants.map((participant) => { const agent = participant.agent_config || {}; return `<article class="participant-card ${selectedMarketParticipants.has(participant.participant_id) ? "selected" : ""}"><label><input type="checkbox" data-market-participant="${escapeHtml(participant.participant_id)}" ${selectedMarketParticipants.has(participant.participant_id) ? "checked" : ""}><span class="participant-avatar ${escapeHtml(participant.role)}">${role === "buyer" ? "买" : "卖"}</span><span><strong>${escapeHtml(participant.name || participant.participant_id)}</strong><small>${escapeHtml(participant.participant_id)} · ${participant.delegation_mode === "platform_managed" ? "平台托管" : "自主决策"}</small></span><em>${money(participant.budget, participant.currency)}</em></label><div class="strategy-line"><span class="agent-state ${agent.enabled ? "enabled" : "manual"}">${agent.enabled ? "代理开启" : "人工"}</span><span>${escapeHtml(agent.model || participant.strategy || "manual")} · 理性 ${asNumber(agent.rationality, 1).toFixed(2)} · ${escapeHtml(agent.style || "balanced")}</span><button data-edit-participant="${escapeHtml(participant.participant_id)}">配置</button></div></article>`; }).join("");
  };
  $("#marketBuyerRows").innerHTML = renderRole("buyer");
  $("#marketSellerRows").innerHTML = renderRole("seller");
  $$('[data-market-participant]').forEach((input) => input.addEventListener("change", () => { input.checked ? selectedMarketParticipants.add(input.dataset.marketParticipant) : selectedMarketParticipants.delete(input.dataset.marketParticipant); renderMarketParticipants(); renderMarketOrders(); renderMarketSummary(); }));
  $$('[data-edit-participant]').forEach((button) => button.addEventListener("click", () => openParticipantDialog(state.participants.find((item) => item.participant_id === button.dataset.editParticipant))));
  $("#marketBuyerCount").textContent = `${state.participants.filter((item) => item.role === "buyer" && selectedMarketParticipants.has(item.participant_id)).length} 已选择`;
  $("#marketSellerCount").textContent = `${state.participants.filter((item) => item.role === "seller" && selectedMarketParticipants.has(item.participant_id)).length} 已选择`;
}

function renderMarketProducts() {
  const selectedMarketProducts = state.selectedMarketProducts;
  $("#marketProductRows").innerHTML = renderAssetDossiers(state.products, selectedMarketProducts, "market");
  $$('[data-market-product]').forEach((input) => input.addEventListener("change", () => { input.checked ? selectedMarketProducts.add(input.dataset.marketProduct) : selectedMarketProducts.delete(input.dataset.marketProduct); state.marketOrders.forEach((order) => { order.product_ids = order.product_ids.filter((id) => selectedMarketProducts.has(id)); }); renderMarketProducts(); renderMarketOrders(); renderMarketSummary(); }));
  $("#marketProductCount").textContent = `${selectedMarketProducts.size} 已选择`;
}

function marketParticipantOptions(side, current) {
  const role = side === "bid" ? "buyer" : "seller";
  return state.participants.filter((item) => state.selectedMarketParticipants.has(item.participant_id) && item.role === role).map((item) => `<option value="${escapeHtml(item.participant_id)}" ${item.participant_id === current ? "selected" : ""}>${escapeHtml(item.name || item.participant_id)}</option>`).join("");
}

function renderMarketOrders() {
  $("#marketOrderRows").innerHTML = state.marketOrders.length ? state.marketOrders.map((order, index) => `<tr data-order-index="${index}">
    <td><span class="order-side ${order.side}">${order.side === "bid" ? "出价" : "要价"}</span>${order.agent_generated ? '<small class="agent-order-label">代理</small>' : ""}</td>
    <td><select data-order-field="participant_id">${marketParticipantOptions(order.side, order.participant_id)}</select></td>
    <td><details class="product-picker"><summary>${order.product_ids.length ? `${order.product_ids.length} 个产品` : "选择产品"}</summary><div>${[...state.selectedMarketProducts].map((productId) => `<label><input type="checkbox" data-order-product="${escapeHtml(productId)}" ${order.product_ids.includes(productId) ? "checked" : ""}>${escapeHtml(productById(productId)?.title || productId)}</label>`).join("") || "请先选择市场产品"}</div></details></td>
    <td><input type="number" min="0" step="100" data-order-field="amount" value="${escapeHtml(order.amount)}"></td>
    <td><input type="number" min="0" step="1" data-order-field="quantity" value="${escapeHtml(order.quantity)}"></td>
    <td><select data-order-field="bundle_mode"><option value="single" ${order.bundle_mode === "single" ? "selected" : ""}>单产品</option><option value="and" ${order.bundle_mode === "and" ? "selected" : ""}>AND 联合</option><option value="xor" ${order.bundle_mode === "xor" ? "selected" : ""}>XOR 替代</option></select></td>
    <td><button data-remove-order="${index}" class="icon-button" title="删除订单">×</button></td>
  </tr>`).join("") : '<tr><td colspan="7" class="loading-cell">尚无订单。添加出价或要价后即可编辑。</td></tr>';
  $$('[data-order-index]').forEach((row) => {
    const order = state.marketOrders[Number(row.dataset.orderIndex)];
    $$('[data-order-field]', row).forEach((control) => control.addEventListener("change", () => { order[control.dataset.orderField] = ["amount", "quantity"].includes(control.dataset.orderField) ? asNumber(control.value) : control.value; renderMarketSummary(); }));
    $$('[data-order-product]', row).forEach((input) => input.addEventListener("change", () => { input.checked ? order.product_ids.push(input.dataset.orderProduct) : order.product_ids = order.product_ids.filter((id) => id !== input.dataset.orderProduct); order.product_ids = [...new Set(order.product_ids)]; renderMarketOrders(); renderMarketSummary(); }));
  });
  $$('[data-remove-order]').forEach((button) => button.addEventListener("click", () => { state.marketOrders.splice(Number(button.dataset.removeOrder), 1); renderMarketOrders(); renderMarketSummary(); }));
}

function addMarketOrder(side) {
  const role = side === "bid" ? "buyer" : "seller";
  const participant = state.participants.find((item) => state.selectedMarketParticipants.has(item.participant_id) && item.role === role);
  const products = [...state.selectedMarketProducts];
  if (!participant) return toast(`请先选择至少一个${role === "buyer" ? "买方" : "卖方"}`);
  if (!products.length) return toast("请先选择至少一个数据产品");
  const product = productById(products[0]);
  state.marketOrders.push({ order_id: `${side}-${Date.now()}`, side, participant_id: participant.participant_id, product_ids: [products[0]], amount: side === "bid" ? asNumber(participant.budget) : asNumber(product?.metadata?.asking_price), quantity: 1, currency: participant.currency || "CNY", bundle_mode: "single" });
  renderMarketOrders(); renderMarketSummary();
}

function validateMarketConfiguration() {
  const errors = [];
  if (!state.selectedMarketParticipants.size) errors.push("未选择参与者");
  if (!state.selectedMarketProducts.size) errors.push("未选择数据产品");
  if (!state.marketOrders.length) errors.push("订单簿为空");
  state.marketOrders.forEach((order, index) => {
    if (!order.participant_id) errors.push(`第 ${index + 1} 条订单未选择参与者`);
    if (!order.product_ids.length) errors.push(`第 ${index + 1} 条订单未选择产品`);
    if (order.amount < 0 || order.quantity <= 0) errors.push(`第 ${index + 1} 条订单金额或数量无效`);
  });
  const singleProduct = new Set(state.marketOrders.flatMap((order) => order.product_ids));
  const mechanism = $("#marketMechanism").value;
  if (["first_price_auction", "second_price_auction", "vcg", "mcafee_double_auction", "multi_unit_uniform_price"].includes(mechanism) && singleProduct.size > 1) errors.push("当前机制只接受同一单产品订单；多产品请使用组合匹配、多属性匹配或采购机制");
  return errors;
}

function buildMarketParameters() {
  const parameters = deepCopy(state.moduleParameters.market || {});
  parameters.mechanism = $("#marketMechanism").value;
  parameters.budget = asNumber($("#marketBudget").value);
  parameters.bids = state.marketOrders.filter((order) => order.side === "bid").map((order) => {
    const participant = state.participants.find((item) => item.participant_id === order.participant_id) || {};
    return { bid_id: order.order_id, buyer_id: order.participant_id, participant_id: order.participant_id, product_ids: order.product_ids, amount: order.amount, quantity: order.quantity, currency: order.currency, budget: asNumber(participant.budget), constraints: { bundle_mode: order.bundle_mode }, metadata: { delegation_mode: participant.delegation_mode, strategy: participant.strategy, strategy_parameters: participant.strategy_parameters || {}, agent_config: participant.agent_config || {}, agent_generated: Boolean(order.agent_generated), agent_explanation: order.explanation || {} } };
  });
  parameters.asks = state.marketOrders.filter((order) => order.side === "ask").map((order) => {
    const participant = state.participants.find((item) => item.participant_id === order.participant_id) || {};
    return { ask_id: order.order_id, seller_id: order.participant_id, participant_id: order.participant_id, product_ids: order.product_ids, reserve: order.amount, quantity: order.quantity, currency: order.currency, constraints: { bundle_mode: order.bundle_mode }, metadata: { delegation_mode: participant.delegation_mode, strategy: participant.strategy, strategy_parameters: participant.strategy_parameters || {}, agent_config: participant.agent_config || {}, agent_generated: Boolean(order.agent_generated), agent_explanation: order.explanation || {} } };
  });
  if (parameters.mechanism === "multi_unit_uniform_price") parameters.supply = Object.fromEntries([...state.selectedMarketProducts].map((id) => [id, state.marketOrders.filter((order) => order.side === "ask" && order.product_ids.includes(id)).reduce((sum, order) => sum + order.quantity, 0)]));
  return parameters;
}

function renderMarketSummary() {
  const buyers = state.participants.filter((item) => state.selectedMarketParticipants.has(item.participant_id) && item.role === "buyer").length;
  const sellers = state.participants.filter((item) => state.selectedMarketParticipants.has(item.participant_id) && item.role === "seller").length;
  const bids = state.marketOrders.filter((item) => item.side === "bid").length;
  const asks = state.marketOrders.length - bids;
  $("#marketSummary").innerHTML = [["买方", buyers], ["卖方", sellers], ["产品", state.selectedMarketProducts.size], ["出价", bids], ["要价", asks]].map(([label, value]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join("");
  const errors = validateMarketConfiguration();
  $("#marketCompatibility").className = `compatibility-note ${errors.length ? "warning" : "ready"}`;
  $("#marketCompatibility").textContent = errors.length ? errors[0] : "当前参与者、产品和订单与所选机制兼容。";
  $("#marketRunSummary").textContent = errors.length ? errors[0] : `${buyers + sellers} 个参与者 · ${state.selectedMarketProducts.size} 个产品 · ${state.marketOrders.length} 条订单`;
  $("#marketRun").disabled = !state.online || errors.length > 0;
  $("#generateAgentOrders").disabled = !state.online || !state.selectedMarketParticipants.size || !state.selectedMarketProducts.size;
  $("#selectionSummary").textContent = `${buyers + sellers} 个参与者 · ${state.selectedMarketProducts.size} 个产品`;
}

function renderAgentPlan(plan) {
  const host = $("#marketAgentPlan");
  const details = $("#marketAgentDetails");
  if (!plan) {
    host.className = "agent-plan";
    host.querySelector("div").innerHTML = "<strong>参与者代理</strong><small>选择启用代理的买卖方后，可根据其理性程度、偏好、策略与当前资产信号自动形成订单。</small>";
    details.hidden = true; $("#marketAgentOrderDetails").innerHTML = "";
    return;
  }
  const skipped = plan.diagnostics?.skipped || [];
  host.className = `agent-plan ${plan.orders.length ? "ready" : "warning"}`;
  host.querySelector("div").innerHTML = `<strong>代理计划：${plan.orders.length} 条订单</strong><small>${plan.orders.filter((item) => item.side === "bid").length} 条买方出价 · ${plan.orders.filter((item) => item.side === "ask").length} 条卖方要价${skipped.length ? ` · ${skipped.length} 个参与者未生成（${skipped.map((item) => item.reason).join("、")}）` : ""}</small>`;
  details.hidden = !plan.orders.length;
  $("#marketAgentOrderDetails").innerHTML = plan.orders.map((order) => `<article><div><span class="order-side ${order.side}">${order.side === "bid" ? "买方" : "卖方"}</span><strong>${escapeHtml(order.participant_id)}</strong><small>${escapeHtml(order.product_ids.join("、"))}</small></div><div><strong>${money(order.amount, order.currency)}</strong><small>${escapeHtml(order.explanation?.model || "—")} · ${escapeHtml(order.explanation?.style || "—")} · 理性 ${asNumber(order.explanation?.rationality, 1).toFixed(2)}</small></div><div><strong>决策锚点 ${money(order.explanation?.reference_price, order.currency)}</strong><small>${escapeHtml(order.explanation?.price_basis || order.explanation?.reason || "当前资产信号")}${order.explanation?.preference_score !== undefined ? ` · 偏好得分 ${order.explanation.preference_score}` : ""}</small></div></article>`).join("");
}

async function generateAgentOrders() {
  if (!state.selectedMarketParticipants.size || !state.selectedMarketProducts.size) return toast("请先选择参与者和资产");
  setBusy(true, "参与者代理正在读取偏好、预算与资产历史信号…");
  try {
    const response = await WorkbenchAPI.post("/market/agent-orders", {
      participant_ids: [...state.selectedMarketParticipants],
      product_ids: [...state.selectedMarketProducts],
      mechanism: $("#marketMechanism").value,
    });
    state.marketAgentPlan = response;
    state.marketOrders = response.orders.map((order) => ({ ...order, product_ids: [...order.product_ids] }));
    renderMarketOrders(); renderMarketSummary(); renderAgentPlan(response);
    toast(response.orders.length ? `代理已生成 ${response.orders.length} 条可编辑订单` : "当前代理配置未生成订单，请检查启用状态和适用机制");
  } catch (error) { toast(`代理生成失败：${error.message}`); }
  finally { setBusy(false); }
}

async function runMarketBatch() {
  const errors = validateMarketConfiguration();
  if (errors.length) return toast(errors[0]);
  const parameters = buildMarketParameters();
  setBusy(true, `正在用 ${$("#marketMechanism option:checked").textContent} 清算订单…`);
  try {
    const response = await WorkbenchAPI.post("/batches", {
      product_ids: [...state.selectedMarketProducts], operations: ["market"], parameters: { market: parameters },
      label: `市场配置 · ${state.scenario?.name || "自定义"}`, scenario_id: state.scenario?.scenario_id,
      seed: asNumber($("#seedInput").value), fail_fast: true,
      include_related_content: true,
    });
    state.currentBatch = response.batch; state.currentResult = response.batch;
    await refreshRegistry(false); renderMarketWorkspace(); renderMarketResult(response.batch.market_stage);
    toast(response.batch.market_stage?.status === "succeeded" ? "市场清算完成，结果已注册" : "市场执行完成，请检查错误信息");
  } catch (error) { toast(`市场执行失败：${error.message}`); } finally { setBusy(false); }
}

function renderMarketResult(stage) {
  if (!stage) { $("#marketResult").innerHTML = '<div class="empty-inline">尚未运行市场机制。</div>'; return; }
  if (stage.status === "failed") { $("#marketResult").innerHTML = `<div class="result-error"><strong>执行失败</strong><p>${escapeHtml(stage.error?.message)}</p></div>`; return; }
  const result = stage.result || {}; const outcome = result.outcome || {};
  const allocations = outcome.allocations || []; const payments = outcome.payments || [];
  const bundleMatches = result.bundle_selection?.matches || [];
  const attributeMatches = result.multi_attribute_matches || [];
  const configuredMatches = allocations.length + bundleMatches.length + attributeMatches.length;
  const matchRows = [
    ...allocations.map((item) => ["分配", item.buyer_id, (item.product_ids || []).join("、"), item.quantity, item.reported_value?.amount ?? "—", item.metadata?.unit_price || "—"]),
    ...bundleMatches.map((item) => [item.mode || "组合", item.buyer_id, (item.product_ids || []).join("、"), 1, item.reported_value?.amount ?? "—", `盈余 ${item.surplus?.amount ?? "—"}`]),
    ...attributeMatches.map((item) => ["多属性", item.buyer_id, item.product_id, item.quantity, "—", `得分 ${item.score ?? "—"}`]),
  ];
  const paymentRows = payments.map((item) => [item.payer_id, item.payee_id, (item.product_ids || []).join("、"), item.amount?.amount ?? item.amount, item.amount?.currency || "—", item.reason]);
  const propertyRows = Object.entries(result.properties || {}).map(([name, value]) => [name, value === true ? "满足" : value === false ? "不满足" : "不适用"]);
  $("#marketResult").innerHTML = `<div class="market-result-summary">
    <div><small>机制</small><strong>${escapeHtml(stage.producer)}</strong></div><div><small>配置 / 匹配</small><strong>${configuredMatches}</strong></div><div><small>支付</small><strong>${payments.length}</strong></div><div><small>审计</small><strong>${escapeHtml(result.audit?.status || "—")}</strong></div><div><small>异常</small><strong>${(result.anomalies || []).length}</strong></div>
  </div><div class="market-result-tables"><section><h3>成交与配置</h3>${tableResult(["类型", "买方", "产品", "数量", "申报价值", "清算信息"], matchRows)}</section><section><h3>支付与卖方收入</h3>${tableResult(["付款方", "收款方", "产品", "金额", "币种", "原因"], paymentRows)}</section><section><h3>机制性质</h3>${tableResult(["性质", "判定"], propertyRows)}</section></div><details class="raw-result"><summary>展开市场健康、异常、订单簿及完整执行轨迹</summary><div class="result-split"><div><h3>市场诊断</h3><pre>${escapeHtml(JSON.stringify({ audit: result.audit, market_health: result.market_health, anomalies: result.anomalies, gaps: result.gaps }, null, 2))}</pre></div><div><h3>完整结果</h3><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></div></div></details>`;
  $("#exportBatch").disabled = false;
}

function openParticipantDialog(participantOrRole = "buyer") {
  const participant = typeof participantOrRole === "object" ? participantOrRole : null;
  const role = participant?.role || participantOrRole;
  state.editingParticipantId = participant?.participant_id || null;
  $("#participantForm").reset();
  $("#editParticipantId").value = participant?.participant_id || ""; $("#editParticipantId").disabled = Boolean(participant);
  $("#editParticipantName").value = participant?.name || ""; $("#editParticipantRole").value = role;
  $("#editParticipantBudget").value = participant?.budget ?? 0; $("#editParticipantReputation").value = participant?.reputation ?? 0.9;
  $("#editParticipantCurrency").value = participant?.currency || "CNY"; $("#editParticipantDescription").value = participant?.description || "";
  $("#editParticipantDelegation").value = participant?.delegation_mode || "self_managed";
  $("#editParticipantStrategy").value = participant?.strategy || (role === "seller" ? "fixed_reserve" : "manual");
  $("#editParticipantStrategyParameters").value = JSON.stringify(participant?.strategy_parameters || {}, null, 2);
  const agent = participant?.agent_config || {};
  $("#editAgentEnabled").checked = Boolean(agent.enabled);
  $("#editAgentRationality").value = agent.rationality ?? 1;
  $("#editAgentStyle").value = agent.style || "balanced";
  $("#editAgentModel").value = agent.model || (role === "seller" ? "reserve_optimizer" : "utility_maximizer");
  $("#editAgentMechanisms").value = (agent.preferred_mechanisms || []).join(", ");
  $("#editAgentPreferences").value = JSON.stringify(agent.preferences || { quality: 0.45, freshness: 0.25, price: 0.3 }, null, 2);
  $("#participantDialog").showModal();
}

function closeParticipantDialog() {
  const dialog = $("#participantDialog");
  if (dialog.open) dialog.close("cancel");
  $("#participantForm").reset();
  state.editingParticipantId = null;
}

async function saveParticipant(event) {
  event.preventDefault();
  let strategyParameters; let agentPreferences;
  try { strategyParameters = JSON.parse($("#editParticipantStrategyParameters").value || "{}"); agentPreferences = JSON.parse($("#editAgentPreferences").value || "{}"); }
  catch (error) { return toast(`策略或偏好参数不是有效 JSON：${error.message}`); }
  const participantId = state.editingParticipantId || $("#editParticipantId").value.trim();
  const existing = state.participants.find((item) => item.participant_id === participantId);
  const payload = { participant_id: participantId, name: $("#editParticipantName").value.trim(), role: $("#editParticipantRole").value, budget: asNumber($("#editParticipantBudget").value), reputation: asNumber($("#editParticipantReputation").value, 0.9), currency: $("#editParticipantCurrency").value.trim() || "CNY", description: $("#editParticipantDescription").value.trim(), product_ids: existing?.product_ids || [], scenario_ids: existing?.scenario_ids || (state.scenario ? [state.scenario.scenario_id] : []), delegation_mode: $("#editParticipantDelegation").value, strategy: $("#editParticipantStrategy").value, strategy_parameters: strategyParameters, agent_config: { enabled: $("#editAgentEnabled").checked, rationality: asNumber($("#editAgentRationality").value, 1), style: $("#editAgentStyle").value, model: $("#editAgentModel").value, preferred_mechanisms: listValue($("#editAgentMechanisms").value), preferences: agentPreferences } };
  try { if (state.editingParticipantId) await WorkbenchAPI.put(`/participants/${participantId}`, payload); else await WorkbenchAPI.post("/participants", payload); $("#participantDialog").close(); await refreshRegistry(); state.selectedMarketParticipants.add(payload.participant_id); renderMarketWorkspace(); toast(state.editingParticipantId ? "参与者策略已更新" : "参与者已注册"); state.editingParticipantId = null; }
  catch (error) { toast(`保存参与者失败：${error.message}`); }
}

function renderProductsView() {
  const query = $("#productSearch").value.trim().toLowerCase();
  const products = state.products.filter((product) => [product.product_id, product.title, product.owner_id, ...(product.tags || [])].join(" ").toLowerCase().includes(query));
  $("#productCount").textContent = `${state.products.length} 个注册产品`;
  $("#productCatalogRows").innerHTML = products.length ? products.map((product) => `<tr data-edit-product="${escapeHtml(product.product_id)}"><td><strong>${escapeHtml(product.title || product.product_id)}</strong><small>${escapeHtml(product.product_id)} · v${escapeHtml(product.version)}</small></td><td>${escapeHtml(product.owner_id)}</td><td>${compactNumber(product.data?.record_count || product.records?.length)}</td><td>${money(product.metadata?.asking_price, product.metadata?.currency)}</td><td><span class="item-status">已注册</span></td></tr>`).join("") : '<tr><td colspan="5" class="loading-cell">没有匹配的数据产品。</td></tr>';
  $$('[data-edit-product]').forEach((row) => row.addEventListener("click", () => editProduct(row.dataset.editProduct)));
}

function renderProductRelatedContent(productId) {
  const host = $("#productRelatedContent");
  const related = assetRelatedContent(productId);
  if (!related.product) { host.innerHTML = '<div class="empty-inline">保存或选择资产后显示关联内容。</div>'; return; }
  host.innerHTML = `${renderAssetHistory(productId)}${renderContentPreview("data", related.product)}${related.artifacts.map((item) => renderContentPreview("artifact", item)).join("")}${related.runs.map((item) => renderContentPreview("run", item)).join("")}`;
}

function resetProductEditor() {
  state.editingProductId = null; state.productPreview = null; $("#productForm").reset(); $("#editProductVersion").value = "1"; $("#editProductQuality").value = "0.9"; $("#editProductFreshness").value = "0.9"; $("#editProductCommercial").checked = true; $("#productEditorTitle").textContent = "新建数据产品"; $("#editProductId").disabled = false; $("#inputPreview").textContent = "尚未解析输入。"; renderProductRelatedContent("");
}

function editProduct(productId) {
  const product = productById(productId); if (!product) return;
  state.editingProductId = productId; state.productPreview = { records: product.records || [] };
  $("#productEditorTitle").textContent = `编辑：${product.title || product.product_id}`; $("#editProductId").value = product.product_id; $("#editProductId").disabled = true;
  $("#editProductTitle").value = product.title || ""; $("#editProductOwner").value = product.owner_id || ""; $("#editProductVersion").value = product.version || "1"; $("#editProductDescription").value = product.description || "";
  $("#editProductPurposes").value = (product.rights?.purposes || []).join(", "); $("#editProductCommercial").checked = product.rights?.commercial_use === true;
  $("#editProductQuality").value = product.metadata?.quality ?? 0.9; $("#editProductFreshness").value = product.metadata?.freshness ?? 0.9; $("#editProductPrice").value = product.metadata?.asking_price ?? 0; $("#editProductTags").value = (product.tags || []).join(", ");
  $("#productInputType").value = "json"; $("#productInputContent").value = JSON.stringify(product.records || [], null, 2); renderInputPreview(state.productPreview); renderProductRelatedContent(productId);
}

async function previewProductInput() {
  let content = $("#productInputContent").value; const inputType = $("#productInputType").value;
  if (inputType === "key_value") { try { content = JSON.parse(content || "{}"); } catch (error) { return toast(`键值输入不是有效 JSON：${error.message}`); } }
  try { const response = await WorkbenchAPI.post("/inputs/preview", { input_type: inputType, content, options: {} }); state.productPreview = response.preview; renderInputPreview(response.preview); }
  catch (error) { toast(`解析失败：${error.message}`); }
}

function renderInputPreview(preview) {
  const errors = preview.errors || [];
  $("#inputPreview").innerHTML = `<div><strong>${preview.records?.length || 0} 条记录</strong><span>${Object.keys(preview.schema || {}).length} 个字段</span><span class="${errors.length ? "error-text" : "success-text"}">${errors.length ? `${errors.length} 个问题` : "解析通过"}</span></div><pre>${escapeHtml(JSON.stringify((preview.records || []).slice(0, 3), null, 2))}</pre>`;
}

async function saveProduct(event) {
  event.preventDefault(); if (!state.productPreview) await previewProductInput(); if (!state.productPreview || (state.productPreview.errors || []).length) return toast("请先修正数据内容并完成预览");
  const productId = state.editingProductId || $("#editProductId").value.trim();
  const payload = { product_id: productId, title: $("#editProductTitle").value.trim(), owner_id: $("#editProductOwner").value.trim(), version: $("#editProductVersion").value.trim() || "1", description: $("#editProductDescription").value.trim(), data: { uri: `workspace://${productId}`, format: "records", record_count: state.productPreview.records.length, media_type: "application/json" }, rights: { purposes: listValue($("#editProductPurposes").value), commercial_use: $("#editProductCommercial").checked, redistribution: false, exclusivity: false }, tags: listValue($("#editProductTags").value), metadata: { quality: asNumber($("#editProductQuality").value), freshness: asNumber($("#editProductFreshness").value), asking_price: asNumber($("#editProductPrice").value), currency: "CNY" }, records: state.productPreview.records };
  try { if (state.editingProductId) await WorkbenchAPI.put(`/products/${productId}`, payload); else await WorkbenchAPI.post("/products", payload); await refreshRegistry(); renderProductsView(); editProduct(productId); toast("数据产品已注册"); }
  catch (error) { toast(`保存失败：${error.message}`); }
}

async function importProductFile(file) {
  if (!file) return; try { const parsed = JSON.parse(await file.text()); const products = Array.isArray(parsed) ? parsed : [parsed]; for (const product of products) await WorkbenchAPI.post("/products", product); await refreshRegistry(); toast(`已导入 ${products.length} 个数据产品`); if (state.activeModule !== "products") openModule("products"); }
  catch (error) { toast(`导入失败：${error.message}`); }
}

function renderResourcesView() {
  const summary = state.dashboard?.summary || {};
  $("#dashboardSummary").innerHTML = [["数据产品", summary.products], ["参与者", summary.participants], ["批次", summary.batches], ["运行", summary.runs], ["产物", summary.artifacts]].map(([label, value]) => `<div class="summary-card"><small>${label}</small><strong>${value || 0}</strong></div>`).join("");
  $("#runList").innerHTML = state.batches.length ? [...state.batches].reverse().map(renderBatchPreview).join("") : '<div class="empty-inline">暂无运行批次。</div>';
  $("#runRecordList").innerHTML = state.runs.length ? [...state.runs].reverse().map((run) => `<details class="resource-preview"><summary><span><strong>${escapeHtml(OPERATION_LABELS[run.operation] || run.operation)} · ${escapeHtml(run.product_id || (run.product_ids || []).join("、"))}</strong><small>${escapeHtml(run.run_id)}</small></span><span><b>${escapeHtml(run.status)}</b><small>${escapeHtml(run.producer || "—")} · ${run.duration_ms ?? "—"} ms</small></span></summary><div class="resource-preview-body"><pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre></div></details>`).join("") : '<div class="empty-inline">暂无逐项运行记录。</div>';
  $("#artifactList").innerHTML = state.artifacts.length ? [...state.artifacts].reverse().map(renderArtifactPreview).join("") : '<div class="empty-inline">暂无注册产物。</div>';
  $$('[data-download-batch]').forEach((button) => button.addEventListener("click", () => { const batch = state.batches.find((item) => item.batch_id === button.dataset.downloadBatch); if (batch) downloadJson(`${batch.batch_id}.json`, batch); }));
  $$('[data-download-artifact]').forEach((button) => button.addEventListener("click", () => { const artifact = state.artifacts.find((item) => artifactId(item) === button.dataset.downloadArtifact); if (artifact) downloadJson(`${artifactId(artifact)}.json`, artifact); }));
}

function renderBatchPreview(batch) {
  return `<details class="resource-preview"><summary><span><strong>${escapeHtml(batch.label)}</strong><small>${escapeHtml(batch.batch_id)}</small></span><span><b>${batch.product_ids?.length || 0} 个资产 · ${escapeHtml(batch.status)}</b><small>${(batch.operations || []).map((item) => OPERATION_LABELS[item] || item).join("、")} · ${dateTime(batch.finished_at)}</small></span></summary><div class="resource-preview-body"><div class="lineage-strip"><span>关联产物 ${batch.input_artifact_ids?.length || 0}</span><span>关联运行 ${batch.input_run_ids?.length || 0}</span><span>${batch.summary?.succeeded_stages || 0} 成功 / ${batch.summary?.failed_stages || 0} 失败</span><button data-download-batch="${escapeHtml(batch.batch_id)}">下载 JSON</button></div><pre>${escapeHtml(JSON.stringify(batch, null, 2))}</pre></div></details>`;
}

function renderArtifactPreview(artifact) {
  return `<details class="resource-preview artifact-preview"><summary><span><strong>${escapeHtml(OPERATION_LABELS[artifact.kind] || artifact.kind)} · ${escapeHtml(artifact.product_id || "多产品")}</strong><small>${escapeHtml(artifactId(artifact))}</small></span><span><b>${escapeHtml(artifact.producer || "—")}</b><small>${dateTime(artifact.created_at)}</small></span></summary><div class="resource-preview-body"><div class="lineage-strip"><span>批次 ${escapeHtml(artifact.batch_id || "—")}</span><button data-download-artifact="${escapeHtml(artifactId(artifact))}">下载 JSON</button></div><pre>${escapeHtml(JSON.stringify(artifact.payload, null, 2))}</pre></div></details>`;
}

function renderComponentsView() {
  const query = $("#componentSearch").value.trim().toLowerCase(); const module = $("#componentModule").value;
  const components = state.components.filter((item) => (module === "all" || item.module === module) && [item.name, item.module, item.kind, ...(item.capabilities || [])].join(" ").toLowerCase().includes(query));
  $("#componentCount").textContent = `${state.components.length} 个已注册实现`;
  $("#componentRows").innerHTML = components.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.registry)}</small></td><td>${escapeHtml(item.module)}</td><td>${escapeHtml(item.kind)}</td><td><div class="tag-list">${(item.capabilities || []).slice(0, 4).map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div></td><td>${escapeHtml(item.version)}</td></tr>`).join("") || '<tr><td colspan="5" class="loading-cell">没有匹配的方法组件。</td></tr>';
}

function downloadJson(filename, value) { const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = filename; link.click(); URL.revokeObjectURL(link.href); }
function exportBatch() { if (state.currentResult) downloadJson(`${state.currentBatch?.batch_id || "datavalor-result"}.json`, state.currentResult); }

async function refreshRegistry(render = true) {
  const [products, participants, artifacts, runs, batches, dashboard] = await Promise.all([
    WorkbenchAPI.get("/products"), WorkbenchAPI.get("/participants"), WorkbenchAPI.get("/artifacts"), WorkbenchAPI.get("/runs"), WorkbenchAPI.get("/batches"), WorkbenchAPI.get("/dashboard"),
  ]);
  state.products = products.products; state.participants = participants.participants; state.marketParticipants = state.participants;
  state.artifacts = artifacts.artifacts; state.runs = runs.runs; state.batches = batches.batches; state.dashboard = dashboard;
  state.moduleSelections && Object.values(state.moduleSelections).forEach((selection) => { for (const id of [...selection]) if (!productById(id)) selection.delete(id); });
  updateNavigationCounts(); if (render) renderActiveView();
}

async function loadAccountIdentity() {
  if (WorkbenchAPI.mode === "offline") return;
  try {
    const data = await WorkbenchAPI.get("/auth/me");
    const account = data.account;
    $("#accountIdentity").textContent = `${account.username} · ${account.role === "admin" ? "管理员" : "独立工作区"}`;
    $("#accountIdentity").hidden = false;
    $("#logoutAccount").hidden = false;
    $("#adminAccounts").hidden = account.role !== "admin";
  } catch (_error) {
    $("#accountIdentity").hidden = true;
    $("#adminAccounts").hidden = true;
    $("#logoutAccount").hidden = true;
  }
}

async function logoutAccount() {
  await fetch("/api/auth/logout", {method: "POST", headers: {"Content-Type": "application/json"}}).catch(() => null);
  window.location.assign("/login");
}

function bindEvents() {
  document.addEventListener("click", (event) => { const target = event.target.closest("[data-module-target]"); if (target) openModule(target.dataset.moduleTarget); });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-toggle-asset-content]"); if (!button) return;
    const key = button.dataset.toggleAssetContent; const expanded = !state.expandedAssets.has(key);
    if (expanded) state.expandedAssets.add(key); else state.expandedAssets.delete(key);
    const dossier = button.closest(".asset-dossier"); dossier?.classList.toggle("expanded", expanded); dossier?.classList.toggle("collapsed", !expanded);
    const content = dossier?.querySelector(".asset-content-stack"); if (content) content.hidden = !expanded;
    button.textContent = expanded ? "收起内容" : "展开内容"; button.setAttribute("aria-expanded", String(expanded));
  });
  $("#scenarioSelect").addEventListener("change", (event) => applyScenario(event.target.value));
  $("#loadScenario").addEventListener("click", () => loadScenarioRegistry().catch((error) => toast(error.message)));
  $("#reloadWorkspace").addEventListener("click", () => boot());
  $("#runBatch").addEventListener("click", () => { if (["governance", "profile", "evaluation", "valuation"].includes(state.activeModule)) runModuleOperation(); else if (state.activeModule === "pricing") runPricingBatch(); else if (state.activeModule === "market") runMarketBatch(); });
  $("#moduleRun").addEventListener("click", runModuleOperation); $("#pricingRun").addEventListener("click", runPricingBatch); $("#marketRun").addEventListener("click", runMarketBatch);
  $("#selectAllModuleProducts").addEventListener("click", () => { const selected = selectedSet(state.activeModule); if (selected.size === state.products.length) selected.clear(); else state.products.forEach((item) => selected.add(item.product_id)); renderModuleWorkspace(state.activeModule); });
  $("#selectAllPricingProducts").addEventListener("click", () => { if (state.pricingProducts.size === state.products.length) state.pricingProducts.clear(); else state.products.forEach((item) => state.pricingProducts.add(item.product_id)); renderPricingWorkspace(); });
  $("#pricingModel").addEventListener("change", () => { state.moduleParameters.pricing = { model: $("#pricingModel").value }; renderPricingFields(); updatePricingSummary(); });
  $("#marketMechanism").addEventListener("change", () => { state.marketAgentPlan = null; renderAgentPlan(null); renderMarketSummary(); }); $("#marketBudget").addEventListener("input", renderMarketSummary);
  $("#generateAgentOrders").addEventListener("click", generateAgentOrders);
  $("#addBid").addEventListener("click", () => addMarketOrder("bid")); $("#addAsk").addEventListener("click", () => addMarketOrder("ask"));
  $("#newParticipant").addEventListener("click", () => openParticipantDialog("buyer")); $("#addBuyer").addEventListener("click", () => openParticipantDialog("buyer")); $("#addSeller").addEventListener("click", () => openParticipantDialog("seller"));
  $("#participantForm").addEventListener("submit", saveParticipant); $("#refreshMarketRegistry").addEventListener("click", () => refreshRegistry());
  $("#cancelParticipant").addEventListener("click", closeParticipantDialog); $("#closeParticipantDialog").addEventListener("click", closeParticipantDialog);
  $("#participantDialog").addEventListener("cancel", () => { state.editingParticipantId = null; $("#participantForm").reset(); });
  $("#editParticipantRole").addEventListener("change", () => { $("#editAgentModel").value = $("#editParticipantRole").value === "seller" ? "reserve_optimizer" : "utility_maximizer"; });
  $("#newProduct").addEventListener("click", resetProductEditor); $("#refreshProducts").addEventListener("click", () => refreshRegistry()); $("#productSearch").addEventListener("input", renderProductsView);
  $("#previewProductInput").addEventListener("click", previewProductInput); $("#productForm").addEventListener("submit", saveProduct);
  $("#importProduct").addEventListener("click", () => $("#productFile").click()); $("#productFile").addEventListener("change", (event) => importProductFile(event.target.files[0]));
  $("#exportBatch").addEventListener("click", exportBatch); $("#refreshResources").addEventListener("click", () => refreshRegistry());
  $("#componentSearch").addEventListener("input", renderComponentsView); $("#componentModule").addEventListener("change", renderComponentsView); $("#refreshComponents").addEventListener("click", renderComponentsView);
  $("#logoutAccount").addEventListener("click", logoutAccount);
}

async function boot() {
  const standalone = WorkbenchAPI.mode === "offline";
  setConnection(false, standalone ? "离线工作区" : "正在连接本地服务");
  try {
    await WorkbenchAPI.get("/health");
    await loadAccountIdentity();
    const [scenarioData, schemaData, componentData] = await Promise.all([WorkbenchAPI.get("/workbench/scenarios"), WorkbenchAPI.get("/workbench/schemas"), WorkbenchAPI.get("/components")]);
    state.scenarios = scenarioData.scenarios; state.schemas = schemaData; state.components = componentData.components;
    renderScenarioOptions(); await refreshRegistry(false);
    setConnection(true, standalone ? "离线执行引擎 · 浏览器本地保存" : "本地 API 已连接");
    applyScenario(state.scenario?.scenario_id || state.scenarios[0]?.scenario_id);
    if ((!state.products.length || !state.participants.length) && state.scenario) await loadScenarioRegistry(false);
    const modules = [...new Set(state.components.map((item) => item.module))];
    $("#componentModule").innerHTML = '<option value="all">全部模块</option>' + modules.map((module) => `<option value="${escapeHtml(module)}">${escapeHtml(module)}</option>`).join("");
    renderActiveView();
  } catch (error) {
    setConnection(false, standalone ? "离线工作区初始化失败" : "本地 API 未连接");
    $("#scenarioRailSummary").textContent = standalone ? "浏览器无法初始化离线工作区。" : "本地服务不可用，请检查 datavalor-local 服务。";
    toast(`${standalone ? "无法初始化离线工作区" : "无法连接工作台"}：${error.message}`);
  }
}

bindEvents();
boot();
