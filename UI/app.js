const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const OPERATION_META = {
  governance: ["Govern", "权利准入"],
  profile: ["Profile", "统计画像"],
  evaluation: ["Evaluate", "质量效用"],
  valuation: ["Value", "任务估值"],
  pricing: ["Price", "合同报价"],
  market: ["Market", "市场配置"],
};

const state = {
  scenarios: [],
  scenario: null,
  products: [],
  schemas: { pricing: {}, market: { mechanisms: {} } },
  selected: new Set(),
  activeProductId: null,
  currentBatch: null,
  batches: [],
  view: "assets",
  online: false,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value, currency = "CNY") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function dateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

let toastTimer;
function toast(message) {
  const host = $("#toast");
  host.textContent = message;
  host.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => host.classList.remove("show"), 2600);
}

function setConnection(online, label) {
  state.online = online;
  WorkbenchAPI.online = online;
  const host = $("#apiState");
  host.className = `connection-state ${online ? "online" : "offline"}`;
  $("span", host).textContent = label;
  updateReadiness();
}

function switchView(view) {
  state.view = view;
  $$("[data-view-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTarget === view);
  });
  $$(".workspace-view").forEach((panel) => panel.classList.remove("active"));
  $(`#${view}View`)?.classList.add("active");
  if (view === "runs") refreshRuns();
}

function currentScenarioProducts() {
  return state.scenario?.products || [];
}

function selectedProductIds() {
  return currentScenarioProducts()
    .map((product) => product.product_id)
    .filter((productId) => state.selected.has(productId));
}

function renderScenarioOptions() {
  $("#scenarioSelect").innerHTML = state.scenarios
    .map((scenario) => `<option value="${escapeHtml(scenario.scenario_id)}">${escapeHtml(scenario.name)}</option>`)
    .join("");
}

function applyScenario(scenarioId) {
  const scenario = state.scenarios.find((item) => item.scenario_id === scenarioId) || state.scenarios[0];
  if (!scenario) return;
  state.scenario = scenario;
  state.selected = new Set(scenario.products.map((product) => product.product_id));
  state.activeProductId = scenario.products[0]?.product_id || null;
  $("#scenarioSelect").value = scenario.scenario_id;
  $("#scenarioRailSummary").textContent = scenario.summary;
  $("#scenarioDomain").textContent = scenario.domain;
  $("#scenarioTitle").textContent = scenario.name;
  $("#scenarioDescription").textContent = scenario.summary;
  $("#scenarioDecision").textContent = scenario.decision;
  $("#metricAssets").textContent = scenario.products.length;
  $("#metricStages").textContent = scenario.default_operations.length;
  $("#metricSellers").textContent = new Set(scenario.products.map((product) => product.owner_id)).size;
  $("#metricBudget").textContent = money(scenario.operation_parameters.market?.budget, scenario.currency);
  $("#batchLabel").value = `${scenario.name} · 候选资产比较`;
  $("#advancedParameters").value = JSON.stringify(scenario.operation_parameters, null, 2);
  renderPipeline();
  syncRecipeControls();
  renderAssets();
  updateReadiness();
}

function renderPipeline() {
  const defaults = new Set(state.scenario?.default_operations || []);
  $("#pipelineStages").innerHTML = Object.entries(OPERATION_META)
    .map(([operation, [name, label]], index) => `
      <div class="pipeline-stage">
        <label class="stage-toggle">
          <input type="checkbox" data-operation="${operation}" ${defaults.has(operation) ? "checked" : ""}>
          <span>${String(index + 1).padStart(2, "0")}</span>
          <span><b>${name}</b><small>${label}</small></span>
        </label>
      </div>`)
    .join("");
  $$('[data-operation]').forEach((input) => input.addEventListener("change", updateReadiness));
}

function renderSchemaOptions() {
  const pricing = Object.values(state.schemas.pricing || {});
  const mechanisms = Object.values(state.schemas.market?.mechanisms || {});
  $("#pricingModel").innerHTML = pricing
    .map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label)}</option>`)
    .join("");
  $("#marketMechanism").innerHTML = mechanisms
    .map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label)}</option>`)
    .join("");
}

function syncRecipeControls() {
  const parameters = state.scenario?.operation_parameters || {};
  const pricingModel = parameters.pricing?.model;
  const mechanism = parameters.market?.mechanism;
  if (pricingModel && state.schemas.pricing[pricingModel]) $("#pricingModel").value = pricingModel;
  if (mechanism && state.schemas.market?.mechanisms?.[mechanism]) $("#marketMechanism").value = mechanism;
  $("#marketBudget").value = parameters.market?.budget ?? 0;
}

function visibleProducts() {
  const query = $("#assetSearch").value.trim().toLowerCase();
  const filter = $("#assetFilter").value;
  return currentScenarioProducts().filter((product) => {
    const text = [product.title, product.product_id, product.owner_id, ...(product.tags || [])].join(" ").toLowerCase();
    if (query && !text.includes(query)) return false;
    if (filter === "selected" && !state.selected.has(product.product_id)) return false;
    if (filter === "commercial" && product.rights.commercial_use !== true) return false;
    if (filter === "restricted" && product.rights.commercial_use === true) return false;
    return true;
  });
}

function renderAssets() {
  const products = visibleProducts();
  const tbody = $("tbody", $("#assetTable"));
  tbody.innerHTML = products.length
    ? products.map((product) => {
      const metadata = product.metadata || {};
      const commercial = product.rights?.commercial_use === true;
      return `<tr data-product-row="${escapeHtml(product.product_id)}" class="${state.activeProductId === product.product_id ? "active" : ""}">
        <td class="check-col"><input type="checkbox" data-select-product="${escapeHtml(product.product_id)}" ${state.selected.has(product.product_id) ? "checked" : ""} aria-label="选择 ${escapeHtml(product.title)}"></td>
        <td><div class="asset-name"><span class="asset-symbol">◇</span><span><strong>${escapeHtml(product.title)}</strong><small>${escapeHtml(product.owner_id)} · ${escapeHtml(product.product_id)}</small></span></div></td>
        <td class="rights-cell"><span class="rights-badge ${commercial ? "" : "restricted"}">${commercial ? "商业使用" : "研究限定"}</span><small>${escapeHtml((product.rights?.purposes || []).join(" · "))}</small></td>
        <td><span class="score"><i style="--score:${Number(metadata.quality || 0) * 100}%"></i>${Math.round(Number(metadata.quality || 0) * 100)}</span></td>
        <td><span class="score"><i style="--score:${Number(metadata.freshness || 0) * 100}%"></i>${Math.round(Number(metadata.freshness || 0) * 100)}</span></td>
        <td class="numeric">${money(metadata.asking_price, metadata.currency)}</td>
        <td><button class="row-action" data-inspect-product="${escapeHtml(product.product_id)}" aria-label="查看 ${escapeHtml(product.title)}">›</button></td>
      </tr>`;
    }).join("")
    : '<tr><td colspan="7" class="loading-cell">当前筛选条件下没有资产。</td></tr>';

  $$('[data-select-product]').forEach((checkbox) => {
    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      if (checkbox.checked) state.selected.add(checkbox.dataset.selectProduct);
      else state.selected.delete(checkbox.dataset.selectProduct);
      updateReadiness();
    });
  });
  $$('[data-product-row]').forEach((row) => row.addEventListener("click", (event) => {
    if (event.target.matches('input[type="checkbox"]')) return;
    state.activeProductId = row.dataset.productRow;
    renderAssets();
  }));
  $$('[data-inspect-product]').forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    state.activeProductId = button.dataset.inspectProduct;
    renderAssets();
  }));
  const visibleIds = products.map((product) => product.product_id);
  $("#masterSelect").checked = visibleIds.length > 0 && visibleIds.every((productId) => state.selected.has(productId));
  renderInspector();
}

function renderInspector() {
  const product = currentScenarioProducts().find((item) => item.product_id === state.activeProductId);
  if (!product) return;
  const metadata = product.metadata || {};
  $("#assetInspector").innerHTML = `
    <div class="inspector-head"><small>DATA PRODUCT · v${escapeHtml(product.version)}</small><h3>${escapeHtml(product.title)}</h3><p>${escapeHtml(product.description)}</p></div>
    <div class="inspector-body">
      <section class="inspector-section"><h4>产品信号</h4><div class="detail-grid">
        <div><small>Owner</small><strong>${escapeHtml(product.owner_id)}</strong></div>
        <div><small>记录样例数</small><strong>${product.records.length}</strong></div>
        <div><small>质量信号</small><strong>${Math.round(metadata.quality * 100)} / 100</strong></div>
        <div><small>新鲜度</small><strong>${Math.round(metadata.freshness * 100)} / 100</strong></div>
      </div></section>
      <section class="inspector-section"><h4>许可与用途</h4><div class="tag-list">${(product.rights.purposes || []).map((purpose) => `<span>${escapeHtml(purpose)}</span>`).join("")}<span>${product.rights.commercial_use ? "commercial" : "non-commercial"}</span>${(product.rights.jurisdictions || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></section>
      <section class="inspector-section"><h4>标签</h4><div class="tag-list">${(product.tags || []).map((tag) => `<span>#${escapeHtml(tag)}</span>`).join("")}</div></section>
      <section class="inspector-section"><h4>样例记录</h4><pre class="sample-json">${escapeHtml(JSON.stringify(product.records.slice(0, 2), null, 2))}</pre></section>
    </div>`;
}

function selectedOperations() {
  return $$('[data-operation]:checked').map((input) => input.dataset.operation);
}

function updateReadiness() {
  const count = selectedProductIds().length;
  const operations = selectedOperations();
  const ready = state.online && count > 0 && operations.length > 0;
  $("#selectionSummary").textContent = `${count} 个资产已选择`;
  $("#assetStatus").textContent = `${currentScenarioProducts().length} 个候选 · ${count} 个已选择`;
  $("#runBatch").disabled = !ready;
  $("#runBatchInline").disabled = !ready;
  $("#exportBatch").disabled = !state.currentBatch;
  const status = $("#batchReadiness");
  status.parentElement.classList.toggle("ready", ready);
  status.textContent = !state.online
    ? "本地服务未连接"
    : count === 0
      ? "请选择至少一个数据资产"
      : operations.length === 0
        ? "请至少启用一个处理环节"
        : `${count} 个资产 · ${operations.length} 个环节 · 可以运行`;
}

async function loadScenarioProducts(silent = false) {
  if (!state.online) throw new Error("请先启动 DataValor 本地服务");
  const response = await WorkbenchAPI.post(`/workbench/scenarios/${state.scenario.scenario_id}/load`);
  state.products = (await WorkbenchAPI.get("/products")).products;
  if (!silent) toast(`场景数据已同步：新增 ${response.loaded}，更新 ${response.updated}`);
  return response;
}

function parametersForSelection() {
  let parameters;
  try {
    parameters = JSON.parse($("#advancedParameters").value || "{}");
  } catch (error) {
    throw new Error(`高级参数不是有效 JSON：${error.message}`);
  }
  parameters.pricing = { ...(parameters.pricing || {}), model: $("#pricingModel").value };
  parameters.market = {
    ...(parameters.market || {}),
    mechanism: $("#marketMechanism").value,
    budget: Number($("#marketBudget").value || 0),
  };
  const selectedIds = new Set(selectedProductIds());
  for (const key of ["bids", "asks"]) {
    if (!Array.isArray(parameters.market[key])) continue;
    parameters.market[key] = parameters.market[key]
      .map((order) => ({
        ...order,
        product_ids: (order.product_ids || []).filter((productId) => selectedIds.has(productId)),
      }))
      .filter((order) => order.product_ids.length > 0);
  }
  return parameters;
}

async function runSelectedBatch() {
  const productIds = selectedProductIds();
  const operations = selectedOperations();
  if (!productIds.length || !operations.length) return;
  let parameters;
  try {
    parameters = parametersForSelection();
  } catch (error) {
    toast(error.message);
    return;
  }
  $("#busyOverlay").hidden = false;
  $("#busyMessage").textContent = `${productIds.length} 个资产正在执行 ${operations.length} 个环节…`;
  try {
    await loadScenarioProducts(true);
    const response = await WorkbenchAPI.post("/batches", {
      product_ids: productIds,
      operations,
      parameters,
      label: $("#batchLabel").value,
      scenario_id: state.scenario.scenario_id,
      seed: Number($("#seedInput").value || 0),
      fail_fast: $("#failFast").checked,
    });
    state.currentBatch = response.batch;
    renderResults(response.batch);
    await refreshRuns();
    switchView("results");
    toast(response.batch.status === "succeeded" ? "批次完成，结果已保存" : "批次完成，部分环节需要检查");
  } catch (error) {
    toast(`批次执行失败：${error.message}`);
  } finally {
    $("#busyOverlay").hidden = true;
    updateReadiness();
  }
}

function renderResults(batch) {
  $("#resultEmpty").hidden = true;
  $("#resultContent").hidden = false;
  $("#resultCount").textContent = batch.items.length;
  $("#resultTitle").textContent = batch.label;
  $("#resultMeta").textContent = `${batch.batch_id} · ${dateTime(batch.finished_at)} · seed ${batch.seed}`;
  const cards = [
    ["候选资产", batch.summary.products, `${batch.summary.succeeded_items} 个完整成功`, "#28c5d7"],
    ["估值合计", money(batch.summary.total_value), "按当前任务效用", "#7b6cf6"],
    ["报价合计", money(batch.summary.total_price), "按当前合同模型", "#f1a43a"],
    ["阶段状态", `${batch.summary.succeeded_stages}/${batch.summary.succeeded_stages + batch.summary.failed_stages}`, `${batch.summary.failed_stages} 个失败`, batch.summary.failed_stages ? "#d95b6a" : "#28a879"],
  ];
  $("#resultSummary").innerHTML = cards.map(([label, value, note, accent]) => `<div class="summary-card" style="--accent:${accent}"><small>${label}</small><strong>${value}</strong><em>${note}</em></div>`).join("");

  const maxValue = Math.max(...batch.items.map((item) => Number(item.metrics.value || 0)), 1);
  const maxPrice = Math.max(...batch.items.map((item) => Number(item.metrics.price || 0)), 1);
  $("#resultCompare").innerHTML = batch.items.map((item, index) => `
    <article class="comparison-row ${index === 0 ? "active" : ""}" data-result-item="${escapeHtml(item.product_id)}">
      <div class="comparison-name"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.product_id)} · ${item.stages.length} stages</small></div>
      <div class="metric-bar"><label>任务估值 <b>${money(item.metrics.value, item.metrics.value_currency)}</b></label><i style="--width:${Math.max(2, Number(item.metrics.value || 0) / maxValue * 100)}%;--bar:var(--violet)"></i></div>
      <div class="metric-bar"><label>合同报价 <b>${money(item.metrics.price, item.metrics.price_currency)}</b></label><i style="--width:${Math.max(2, Number(item.metrics.price || 0) / maxPrice * 100)}%;--bar:var(--amber)"></i></div>
      <div class="metric-bar"><label>质量信号 <b>${Math.round(Number(item.metrics.quality_signal || item.metrics.quality_score || 0) * 100)}</b></label><i style="--width:${Number(item.metrics.quality_signal || item.metrics.quality_score || 0) * 100}%;--bar:var(--cyan)"></i></div>
      <span class="item-status ${item.status}">${item.status}</span>
    </article>`).join("");
  $$('[data-result-item]').forEach((row) => row.addEventListener("click", () => {
    $$('[data-result-item]').forEach((item) => item.classList.toggle("active", item === row));
    renderTrace(batch.items.find((item) => item.product_id === row.dataset.resultItem));
  }));
  renderTrace(batch.items[0]);
  renderMarketResult(batch.market_stage);
  updateReadiness();
}

function renderTrace(item) {
  if (!item) {
    $("#traceInspector").innerHTML = '<div class="inspector-empty"><p>没有阶段结果。</p></div>';
    return;
  }
  $("#traceInspector").innerHTML = `
    <div class="trace-head"><small>EXECUTION TRACE</small><h3>${escapeHtml(item.title)}</h3><small>${escapeHtml(item.product_id)} · ${item.status}</small></div>
    <div class="trace-stages">${item.stages.map((stage) => `<div class="trace-stage ${stage.status}"><i></i><b>${escapeHtml(OPERATION_META[stage.operation]?.[1] || stage.operation)}</b><small>${escapeHtml(stage.producer || stage.error?.message || "未执行")} · ${stage.duration_ms} ms</small><button data-stage-json="${escapeHtml(stage.operation)}">查看产物</button></div>`).join("")}</div>
    <pre class="trace-json">选择阶段查看可追溯结果。</pre>`;
  $$('[data-stage-json]', $("#traceInspector")).forEach((button) => button.addEventListener("click", () => {
    const stage = item.stages.find((candidate) => candidate.operation === button.dataset.stageJson);
    $(".trace-json", $("#traceInspector")).textContent = JSON.stringify(stage.result || stage.error, null, 2);
  }));
}

function renderMarketResult(stage) {
  const host = $("#marketResult");
  if (!stage) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  if (stage.status === "failed") {
    host.innerHTML = `<h3>市场配置需要检查</h3><p>${escapeHtml(stage.error?.message)}</p>`;
    return;
  }
  const result = stage.result || {};
  const outcome = result.outcome || {};
  const health = result.market_health?.metrics || {};
  host.innerHTML = `<h3>市场机制结果 · ${escapeHtml(stage.producer)}</h3><div class="market-grid">
    <div><small>分配数量</small><strong>${(outcome.allocations || []).length}</strong></div>
    <div><small>支付数量</small><strong>${(outcome.payments || []).length}</strong></div>
    <div><small>活跃挂牌</small><strong>${health.active_listings ?? "—"}</strong></div>
    <div><small>审计状态</small><strong>${escapeHtml(result.audit?.status || "—")}</strong></div>
  </div>`;
}

async function refreshRuns() {
  if (!state.online) return;
  try {
    state.batches = (await WorkbenchAPI.get("/batches")).batches;
    $("#runCount").textContent = state.batches.length;
    $("#runList").innerHTML = state.batches.length
      ? state.batches.map((batch) => `<article class="run-row"><div><strong>${escapeHtml(batch.label)}</strong><small>${escapeHtml(batch.batch_id)}</small></div><div><strong>${batch.summary.products} assets</strong><small>${batch.operations.length} operations</small></div><div><strong>${escapeHtml(batch.status)}</strong><small>${batch.summary.failed_stages} failed stages</small></div><div><strong>${dateTime(batch.finished_at)}</strong><small>seed ${batch.seed}</small></div><button data-open-batch="${escapeHtml(batch.batch_id)}">打开结果</button></article>`).join("")
      : '<div class="loading-cell">暂无批次。先从工作台运行一组数据资产。</div>';
    $$('[data-open-batch]').forEach((button) => button.addEventListener("click", async () => {
      try {
        const response = await WorkbenchAPI.get(`/batches/${button.dataset.openBatch}`);
        state.currentBatch = response.batch;
        renderResults(response.batch);
        switchView("results");
      } catch (error) {
        toast(`读取批次失败：${error.message}`);
      }
    }));
  } catch (error) {
    $("#runList").innerHTML = `<div class="loading-cell">读取批次失败：${escapeHtml(error.message)}</div>`;
  }
}

function exportBatch() {
  if (!state.currentBatch) return;
  const blob = new Blob([JSON.stringify(state.currentBatch, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.currentBatch.batch_id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function importProductFile(file) {
  if (!file) return;
  try {
    const value = JSON.parse(await file.text());
    const products = Array.isArray(value) ? value : [value];
    for (const product of products) await WorkbenchAPI.post("/products", product);
    state.products = (await WorkbenchAPI.get("/products")).products;
    toast(`已导入 ${products.length} 个产品；可在自定义 API 流程中使用`);
  } catch (error) {
    toast(`导入失败：${error.message}`);
  }
}

function bindEvents() {
  $$("[data-view-target]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewTarget)));
  $("#scenarioSelect").addEventListener("change", (event) => applyScenario(event.target.value));
  $("#assetSearch").addEventListener("input", renderAssets);
  $("#assetFilter").addEventListener("change", renderAssets);
  $("#selectAll").addEventListener("click", () => {
    const products = visibleProducts();
    const allSelected = products.length && products.every((product) => state.selected.has(product.product_id));
    products.forEach((product) => allSelected ? state.selected.delete(product.product_id) : state.selected.add(product.product_id));
    renderAssets();
    updateReadiness();
  });
  $("#masterSelect").addEventListener("change", (event) => {
    visibleProducts().forEach((product) => event.target.checked ? state.selected.add(product.product_id) : state.selected.delete(product.product_id));
    renderAssets();
    updateReadiness();
  });
  $("#loadScenario").addEventListener("click", () => loadScenarioProducts().catch((error) => toast(error.message)));
  $("#runBatch").addEventListener("click", runSelectedBatch);
  $("#runBatchInline").addEventListener("click", runSelectedBatch);
  $("#exportBatch").addEventListener("click", exportBatch);
  $("#resultToAssets").addEventListener("click", () => switchView("assets"));
  $("#refreshRuns").addEventListener("click", refreshRuns);
  $("#reloadWorkspace").addEventListener("click", boot);
  $("#importProduct").addEventListener("click", () => $("#productFile").click());
  $("#productFile").addEventListener("change", (event) => importProductFile(event.target.files[0]));
}

async function boot() {
  setConnection(false, "正在连接本地服务");
  try {
    await WorkbenchAPI.get("/health");
    const [scenarioData, schemaData, productData, batchData] = await Promise.all([
      WorkbenchAPI.get("/workbench/scenarios"),
      WorkbenchAPI.get("/workbench/schemas"),
      WorkbenchAPI.get("/products"),
      WorkbenchAPI.get("/batches"),
    ]);
    state.scenarios = scenarioData.scenarios;
    state.schemas = schemaData;
    state.products = productData.products;
    state.batches = batchData.batches;
    setConnection(true, "本地 API 已连接");
    renderScenarioOptions();
    renderSchemaOptions();
    applyScenario(state.scenario?.scenario_id || state.scenarios[0]?.scenario_id);
    await refreshRuns();
  } catch (error) {
    setConnection(false, "本地 API 未连接");
    $("#scenarioRailSummary").textContent = "请运行 python -m UI.run，然后重新同步工作区。";
    $("#assetStatus").textContent = "服务离线";
    toast(`无法连接工作台：${error.message}`);
  }
}

bindEvents();
boot();
