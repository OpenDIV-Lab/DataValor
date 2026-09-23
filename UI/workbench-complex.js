/* Complex, repository-backed workbenches layered onto the existing UI. */
const COMPLEX_INPUT_TYPES = {
  json: ['JSON 数组', '[{"id":1,"value":10}]'],
  jsonl: ['JSON Lines', '{"id":1}\n{"id":2}'],
  csv: ['CSV', 'id,value\n1,10\n2,20'],
  tsv: ['TSV', 'id\tvalue\n1\t10'],
  key_value: ['键值参数', '{"threshold":"0.8","enabled":"true"}'],
  uri: ['URI / HTTP / 对象存储', 'https://example.test/data.csv'],
  catalog: ['已登记数据产品', 'catalog://product-id'],
  artifact: ['历史产物', 'artifact://artifact-id'],
  upstream: ['上游工作流输出', 'upstream://node-id/output']
};

function escapeAttribute(value) {
  return escapeText(String(value)).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function complexField(field, prefix = 'complex') {
  const id = `${prefix}-${field.key}`;
  const value = field.default ?? '';
  if (field.type === 'select') return `<label>${field.label}<select id="${id}" data-complex-field="${field.key}">${field.options.map(x => `<option>${x}</option>`).join('')}</select></label>`;
  if (field.type === 'json') return `<label class="span-2">${field.label}<textarea id="${id}" data-complex-field="${field.key}" data-value-type="json">${escapeText(JSON.stringify(value, null, 2))}</textarea></label>`;
  if (field.type === 'number_list') return `<label class="span-2">${field.label}<input id="${id}" data-complex-field="${field.key}" data-value-type="number_list" value="${value.join(', ')}"></label>`;
  if (field.type === 'product_number_map') return `<label class="span-2">${field.label}<textarea id="${id}" data-complex-field="${field.key}" data-value-type="json">${escapeText(JSON.stringify(value))}</textarea></label>`;
  return `<label>${field.label}<input id="${id}" data-complex-field="${field.key}" type="${field.type === 'number' ? 'number' : 'text'}" step="any" value="${escapeText(String(value))}"></label>`;
}

function readComplexFields(host) {
  const values = {};
  host.querySelectorAll('[data-complex-field]').forEach(input => {
    let value = input.value;
    if (input.dataset.valueType === 'json') value = JSON.parse(value || '{}');
    else if (input.dataset.valueType === 'number_list') value = value.split(',').map(x => Number(x.trim())).filter(Number.isFinite);
    else if (input.type === 'number') value = Number(value);
    values[input.dataset.complexField] = value;
  });
  return values;
}

productEditor = function () {
  const modes = Object.entries(COMPLEX_INPUT_TYPES);
  document.querySelector('#resourceView').innerHTML = `<div class="complex-editor">
    <div class="resource-head"><div><h2>创建数据产品</h2><p>输入、解析、Schema 与产品属性在本模块内完成</p></div><button onclick="renderServerResource('products')">返回目录</button></div>
    <div class="module-tabs"><button class="active" data-input-tab="source">1 输入来源</button><button data-input-tab="parse">2 解析与 Schema</button><button data-input-tab="product">3 产品属性</button><button data-input-tab="preview">4 预览与保存</button></div>
    <section class="module-tab active" data-input-panel="source"><div class="input-mode-grid">${modes.map(([key, item]) => `<button data-input-mode="${key}" class="${key === 'json' ? 'active' : ''}"><b>${item[0]}</b><small>${key}</small></button>`).join('')}</div><div class="drop-zone" id="complexDrop">拖放文本文件到这里，或 <label>选择文件<input id="complexFile" type="file" hidden></label></div><label class="wide-field">输入内容<textarea id="complexContent">${escapeText(COMPLEX_INPUT_TYPES.json[1])}</textarea></label></section>
    <section class="module-tab" data-input-panel="parse"><div class="workbench-form"><label>编码<select id="complexEncoding"><option>utf-8</option><option>gb18030</option><option>latin-1</option></select></label><label>分隔符<input id="complexDelimiter" value=","></label><label>采样行数<input id="complexSample" type="number" value="1000"></label><label>批次大小<input id="complexBatch" type="number" value="500"></label><label class="span-2">Schema 覆盖 JSON<textarea id="complexSchema">{}</textarea></label></div><button id="complexPreview">解析并预览</button></section>
    <section class="module-tab" data-input-panel="product"><div class="workbench-form"><label>产品 ID<input id="pId" value="product-${Date.now().toString().slice(-6)}"></label><label>标题<input id="pTitle" value="新数据产品"></label><label>Owner<input id="pOwner" value="local-owner"></label><label>版本<input id="pVersion" value="1"></label><label>允许用途<input id="pPurpose" value="analytics,valuation"></label><label>标签<input id="pTags" value="market-ready"></label><label>商业使用<select id="pCommercial"><option value="true">允许</option><option value="false">禁止</option><option value="null">未声明</option></select></label><label>再分发<select id="pRedistribution"><option value="false">禁止</option><option value="true">允许</option><option value="null">未声明</option></select></label><label>独占性<select id="pExclusivity"><option>non_exclusive</option><option>exclusive</option><option>none</option></select></label><label>地域<input id="pJurisdictions" value="CN"></label><label class="span-2">描述<textarea id="pDescription">可用于复杂定价与市场撮合的数据产品</textarea></label></div></section>
    <section class="module-tab" data-input-panel="preview"><div class="preview-grid"><div><h3>标准化记录</h3><pre class="result-view" id="complexRecords">尚未解析</pre></div><div><h3>推断 Schema 与错误</h3><pre class="result-view" id="complexMeta">尚未解析</pre></div></div><div class="action-row"><button id="complexPreviewAgain">重新解析</button><button class="primary" id="saveComplexProduct">保存数据产品</button></div></section>
  </div>`;
  let inputType = 'json', preview = null;
  const selectTab = name => { document.querySelectorAll('[data-input-tab]').forEach(x => x.classList.toggle('active', x.dataset.inputTab === name)); document.querySelectorAll('[data-input-panel]').forEach(x => x.classList.toggle('active', x.dataset.inputPanel === name)); };
  document.querySelectorAll('[data-input-tab]').forEach(x => x.onclick = () => selectTab(x.dataset.inputTab));
  document.querySelectorAll('[data-input-mode]').forEach(x => x.onclick = () => { inputType = x.dataset.inputMode; document.querySelectorAll('[data-input-mode]').forEach(y => y.classList.toggle('active', y === x)); document.querySelector('#complexContent').value = COMPLEX_INPUT_TYPES[inputType][1]; });
  const loadFile = file => { const ext = file.name.split('.').pop().toLowerCase(); if (file.size > 2 * 1024 * 1024 || !['json', 'jsonl', 'csv', 'tsv', 'txt'].includes(ext)) { inputType = 'uri'; document.querySelector('[data-input-mode="uri"]')?.click(); document.querySelector('#complexContent').value = `file:///${encodeURIComponent(file.name)}`; toast('大型或二进制文件已保存为文件描述，不在浏览器读取'); return; } const reader = new FileReader(); reader.onload = () => { document.querySelector('#complexContent').value = String(reader.result); if (['json', 'jsonl', 'csv', 'tsv'].includes(ext)) { inputType = ext; document.querySelector(`[data-input-mode="${ext}"]`)?.click(); document.querySelector('#complexContent').value = String(reader.result); } }; reader.readAsText(file, document.querySelector('#complexEncoding').value); };
  document.querySelector('#complexFile').onchange = e => e.target.files[0] && loadFile(e.target.files[0]);
  const drop = document.querySelector('#complexDrop'); drop.ondragover = e => { e.preventDefault(); drop.classList.add('dragging'); }; drop.ondragleave = () => drop.classList.remove('dragging'); drop.ondrop = e => { e.preventDefault(); drop.classList.remove('dragging'); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); };
  async function previewInput() {
    const raw = document.querySelector('#complexContent').value;
    if (inputType === 'upstream') { const upstreamId = raw.replace(/^upstream:\/\//, '').split('/')[0]; if (!state.instances.some(node => node.id === upstreamId)) throw Error(`上游节点不存在：${upstreamId}`); }
    let content = raw;
    if (inputType === 'key_value') content = JSON.parse(raw);
    const data = await WorkbenchAPI.post('/inputs/preview', { input_type: inputType, content, options: { delimiter: document.querySelector('#complexDelimiter').value, encoding: document.querySelector('#complexEncoding').value, sample_size: +document.querySelector('#complexSample').value, batch_size: +document.querySelector('#complexBatch').value, schema: JSON.parse(document.querySelector('#complexSchema').value || '{}') } });
    preview = data.preview;
    document.querySelector('#complexRecords').textContent = JSON.stringify(preview.records, null, 2);
    document.querySelector('#complexMeta').textContent = JSON.stringify({ schema: preview.schema, errors: preview.errors, stats: preview.stats }, null, 2);
    selectTab('preview');
  }
  document.querySelector('#complexPreview').onclick = () => previewInput().catch(e => { document.querySelector('#complexMeta').textContent = `解析错误：${e.message}`; selectTab('preview'); });
  document.querySelector('#complexPreviewAgain').onclick = () => previewInput().catch(e => toast(e.message));
  document.querySelector('#saveComplexProduct').onclick = async () => {
    if (!preview) return toast('请先解析或验证输入');
    if (preview.errors?.length) return toast('存在输入错误，请修正后保存');
    const reference = ['uri', 'catalog', 'artifact', 'upstream'].includes(inputType) ? document.querySelector('#complexContent').value.trim() : `memory://${document.querySelector('#pId').value}`;
    const tri = id => document.querySelector(id).value === 'null' ? null : document.querySelector(id).value === 'true';
    await WorkbenchAPI.post('/products', { product_id: document.querySelector('#pId').value, title: document.querySelector('#pTitle').value, owner_id: document.querySelector('#pOwner').value, version: document.querySelector('#pVersion').value, description: document.querySelector('#pDescription').value, data: { uri: reference, format: inputType, record_count: preview.records.length, metadata: { inferred_schema: preview.schema } }, rights: { purposes: document.querySelector('#pPurpose').value.split(',').map(x => x.trim()).filter(Boolean), commercial_use: tri('#pCommercial'), redistribution: tri('#pRedistribution'), exclusivity: document.querySelector('#pExclusivity').value, jurisdictions: document.querySelector('#pJurisdictions').value.split(',').map(x => x.trim()).filter(Boolean) }, tags: document.querySelector('#pTags').value.split(',').map(x => x.trim()).filter(Boolean), metadata: { input_config: { type: inputType, encoding: document.querySelector('#complexEncoding').value, delimiter: document.querySelector('#complexDelimiter').value, sample_size: +document.querySelector('#complexSample').value, batch_size: +document.querySelector('#complexBatch').value, schema: preview.schema } }, records: preview.records });
    toast('数据产品已保存'); renderServerResource('products');
  };
};

renderMarketWorkbench = async function () {
  const [{ products }, schemas] = await Promise.all([WorkbenchAPI.get('/products'), WorkbenchAPI.get('/workbench/schemas')]);
  if (!products.length) { document.querySelector('#resourceView').innerHTML = `<div class="alert-box"><b>需要数据产品</b><p>先创建至少一个数据产品，随后才能配置多产品市场。</p><button onclick="openWorkbenchPage('products')">创建数据产品</button></div>`; return; }
  const tabs = ['场景', '产品与输入', '参与方与订单', '定价合同', '市场机制', '执行过程', '结果与诊断'];
  const pricing = schemas.pricing, market = schemas.market;
  document.querySelector('#resourceView').innerHTML = `<div class="complex-market"><div class="module-tabs market-tabs">${tabs.map((x, i) => `<button class="${i === 0 ? 'active' : ''}" data-market-tab="${i}">${i + 1} ${x}</button>`).join('')}</div>
    <section class="module-tab active" data-market-panel="0"><h2>市场场景</h2><p>预设只填入可编辑配置，不隐藏订单和机制参数。</p><div class="scenario-grid">${Object.entries(market.scenarios).map(([key, label]) => `<button data-scenario="${key}"><b>${label}</b><small>${key}</small></button>`).join('')}</div><div class="workbench-form"><label>场景名称<input id="scenarioName" value="多产品数据交易"></label><label>币种<select id="marketCurrency"><option>CNY</option><option>USD</option><option>EUR</option></select></label><label>结算周期<select id="settlementPeriod"><option>single</option><option>monthly</option><option>quarterly</option></select></label><label>用途<input id="marketPurpose" value="analytics"></label></div></section>
    <section class="module-tab" data-market-panel="1"><h2>产品与数据输入</h2><div class="market-product-grid">${products.map((p, i) => `<label class="market-product"><input type="checkbox" data-market-product="${escapeAttribute(p.product_id)}" ${i < 2 ? 'checked' : ''}><b>${escapeText(p.title)}</b><code>${escapeText(p.product_id)}</code><span>${escapeText(p.data.format)} · ${p.records.length} 记录</span><small>用途 ${escapeText(p.rights.purposes.join(', ') || '未声明')} · 商业使用 ${escapeText(p.rights.commercial_use ?? '未声明')}</small></label>`).join('')}</div><button onclick="openWorkbenchPage('products')">管理与添加输入</button></section>
    <section class="module-tab" data-market-panel="2"><h2>参与方与订单</h2><div class="order-toolbar"><button data-add-order="bid">＋ Bid</button><button data-add-order="ask">＋ Ask</button><select id="orderImportType"><option value="json">JSON</option><option value="csv">CSV</option><option value="jsonl">JSONL</option></select><button id="toggleOrderImport">批量导入</button></div><div id="orderImport" hidden><textarea id="orderImportContent">[{"role":"bid","actor":"buyer-c","product_ids":["${products[0].product_id}"],"amount":90000,"quantity":1}]</textarea><button id="importOrders">解析并加入订单</button></div><div id="complexOrders"></div></section>
    <section class="module-tab" data-market-panel="3"><h2>定价合同</h2><div class="workbench-form"><label class="span-2">报价模型<select id="complexPricingModel">${Object.values(pricing).map(x => `<option value="${x.name}">${x.label} · ${x.name}</option>`).join('')}</select></label></div><div class="workbench-form dynamic-fields" id="pricingFields"></div><button id="runComplexQuote">生成选中产品报价</button><pre class="result-view compact" id="complexQuoteResult">等待报价</pre></section>
    <section class="module-tab" data-market-panel="4"><h2>市场机制</h2><div class="workbench-form"><label class="span-2">机制<select id="complexMechanism">${Object.values(market.mechanisms).map(x => `<option value="${x.name}">${x.label} · ${x.name}</option>`).join('')}</select></label><label>组合预算<input id="complexBudget" type="number" value="200000"></label><label>采购方 ID<input id="complexBuyer" value="platform-buyer"></label></div><div class="workbench-form dynamic-fields" id="mechanismFields"></div><h3>分析方法</h3><div class="method-chips"><span>供需缺口</span><span>需求分群</span><span>供给分群</span><span>市场健康</span><span>异常信号</span><span>性质检查</span><span>收入对账</span></div><button class="primary" id="runComplexMarket">校验并执行市场</button></section>
    <section class="module-tab" data-market-panel="5"><h2>执行过程</h2><div id="complexTrace" class="trace-list"><div class="no-data">运行报价或市场后显示输入标准化、校验、计算、清算和诊断过程。</div></div></section>
    <section class="module-tab" data-market-panel="6"><h2>结果与诊断</h2><div class="result-tabs">${['outcome', 'bundle_selection', 'multi_attribute_matches', 'properties', 'audit', 'gaps', 'demand_segments', 'supply_segments', 'market_health', 'anomalies', 'order_book'].map((x, i) => `<button data-result-view="${x}" class="${i === 0 ? 'active' : ''}">${x}</button>`).join('')}</div><pre class="result-view" id="complexMarketResult">等待执行</pre><button id="downloadMarketResult">下载完整结果</button></section></div>`;
  let orders = [], marketResult = null, quoteResults = [];
  const switchTab = index => { document.querySelectorAll('[data-market-tab]').forEach(x => x.classList.toggle('active', x.dataset.marketTab === String(index))); document.querySelectorAll('[data-market-panel]').forEach(x => x.classList.toggle('active', x.dataset.marketPanel === String(index))); };
  document.querySelectorAll('[data-market-tab]').forEach(x => x.onclick = () => switchTab(x.dataset.marketTab));
  const selectedProducts = () => [...document.querySelectorAll('[data-market-product]:checked')].map(x => x.dataset.marketProduct);
  function renderDynamic(kind) { const select = document.querySelector(kind === 'pricing' ? '#complexPricingModel' : '#complexMechanism'), host = document.querySelector(kind === 'pricing' ? '#pricingFields' : '#mechanismFields'), schema = kind === 'pricing' ? pricing[select.value] : market.mechanisms[select.value]; host.innerHTML = schema.fields.map(x => complexField(x, kind)).join('') || '<p class="no-data span-2">该机制直接使用订单簿，无额外参数。</p>'; }
  document.querySelector('#complexPricingModel').onchange = () => renderDynamic('pricing'); document.querySelector('#complexMechanism').onchange = () => renderDynamic('mechanism'); renderDynamic('pricing'); renderDynamic('mechanism');
  function addOrder(role, values = {}) { orders.push({ role, actor: values.actor || `${role === 'bid' ? 'buyer' : 'seller'}-${orders.length + 1}`, product_ids: values.product_ids || [products[0].product_id], amount: Number(values.amount ?? (role === 'bid' ? 120000 : 70000)), quantity: Number(values.quantity ?? 1), budget: Number(values.budget ?? 150000), task_id: values.task_id || '', bundle_mode: values.bundle_mode || 'and', quality: Number(values.quality ?? 0.9) }); renderOrders(); }
  function renderOrders() { document.querySelector('#complexOrders').innerHTML = orders.map((o, i) => `<article class="complex-order ${o.role}"><header><b>${o.role === 'bid' ? 'Bid 买方订单' : 'Ask 卖方订单'}</b><button data-remove-order="${i}">×</button></header><div class="order-fields"><label>参与方<input data-order="${i}:actor" value="${escapeAttribute(o.actor)}"></label><label>产品（可多选）<select data-order-products="${i}" multiple>${products.map(p => `<option value="${escapeAttribute(p.product_id)}" ${o.product_ids.includes(p.product_id) ? 'selected' : ''}>${escapeText(p.product_id)}</option>`).join('')}</select></label><label>${o.role === 'bid' ? '出价' : '保留价'}<input data-order="${i}:amount" type="number" value="${o.amount}"></label><label>数量<input data-order="${i}:quantity" type="number" value="${o.quantity}"></label>${o.role === 'bid' ? `<label>预算<input data-order="${i}:budget" type="number" value="${o.budget}"></label><label>Bundle 模式<select data-order="${i}:bundle_mode"><option ${o.bundle_mode === 'and' ? 'selected' : ''}>and</option><option ${o.bundle_mode === 'xor' ? 'selected' : ''}>xor</option></select></label><label>任务 ID<input data-order="${i}:task_id" value="${escapeAttribute(o.task_id)}"></label>` : `<label>质量<input data-order="${i}:quality" type="number" step=".05" value="${o.quality}"></label>`}</div></article>`).join(''); document.querySelectorAll('[data-remove-order]').forEach(x => x.onclick = () => { orders.splice(+x.dataset.removeOrder, 1); renderOrders(); }); document.querySelectorAll('[data-order]').forEach(x => x.oninput = () => { const [i, key] = x.dataset.order.split(':'); orders[i][key] = x.type === 'number' ? Number(x.value) : x.value; }); document.querySelectorAll('[data-order-products]').forEach(x => x.onchange = () => { orders[+x.dataset.orderProducts].product_ids = [...x.selectedOptions].map(o => o.value); }); }
  addOrder('bid', { actor: '零售分析方', amount: 125000, budget: 150000 }); addOrder('bid', { actor: '供应链方', amount: 108000, budget: 120000 }); addOrder('ask', { actor: '数据提供方A', amount: 65000, quality: .92 }); addOrder('ask', { actor: '数据提供方B', product_ids: [products[Math.min(1, products.length - 1)].product_id], amount: 78000, quality: .85 });
  document.querySelectorAll('[data-add-order]').forEach(x => x.onclick = () => addOrder(x.dataset.addOrder));
  document.querySelector('#toggleOrderImport').onclick = () => document.querySelector('#orderImport').hidden = !document.querySelector('#orderImport').hidden;
  document.querySelector('#importOrders').onclick = async () => { try { const kind = document.querySelector('#orderImportType').value, raw = document.querySelector('#orderImportContent').value, content = kind === 'json' ? raw : raw, data = await WorkbenchAPI.post('/inputs/preview', { input_type: kind, content, options: {} }); if (data.preview.errors.length) throw Error(data.preview.errors.map(x => `${x.location}: ${x.message}`).join('; ')); data.preview.records.forEach(row => addOrder(String(row.role || 'bid').toLowerCase(), { ...row, product_ids: Array.isArray(row.product_ids) ? row.product_ids : String(row.product_ids || products[0].product_id).split('|') })); toast(`已导入 ${data.preview.records.length} 条订单`); } catch (e) { toast(`订单导入失败：${e.message}`); } };
  document.querySelectorAll('[data-scenario]').forEach(x => x.onclick = () => { const maps = { single_auction: 'second_price_auction', double_market: 'mcafee_double_auction', procurement: 'quality_aware_procurement', multi_unit: 'multi_unit_uniform_price', bundle: 'bundle_matching', multi_attribute: 'multi_attribute_matching' }; document.querySelector('#complexMechanism').value = maps[x.dataset.scenario]; renderDynamic('mechanism'); switchTab(4); });
  function renderTrace(trace) { document.querySelector('#complexTrace').innerHTML = (trace || []).map((step, i) => `<article><b>${i + 1}</b><div><strong>${step.step}</strong><small>${step.status}</small><pre>${escapeText(JSON.stringify(step, null, 2))}</pre></div></article>`).join('') || '<div class="no-data">没有执行步骤</div>'; }
  function renderFailureTrace(step, error, tabIndex) { renderTrace([{ step, status: 'failed', error: error.message, occurred_at: new Date().toISOString() }]); switchTab(tabIndex); toast(`${step}失败：${error.message}`); }
  document.querySelector('#runComplexQuote').onclick = async () => { try { const productIds = selectedProducts(); if (!productIds.length) throw Error('至少选择一个产品'); const model = document.querySelector('#complexPricingModel').value, parameters = { model, ...readComplexFields(document.querySelector('#pricingFields')) }; quoteResults = []; for (const product_id of productIds) quoteResults.push((await WorkbenchAPI.post('/operations/pricing', { product_id, parameters })).result); document.querySelector('#complexQuoteResult').textContent = JSON.stringify(quoteResults.map(quote => ({ price: quote.price, components: quote.components, normalized_parameters: quote.normalized_parameters, trace: quote.trace })), null, 2); renderTrace(quoteResults.flatMap(x => x.trace || [])); switchTab(5); } catch (e) { renderFailureTrace('pricing', e, 5); } };
  document.querySelector('#runComplexMarket').onclick = async () => { try { const product_ids = selectedProducts(); if (!product_ids.length) throw Error('至少选择一个产品'); if (!orders.length) throw Error('至少添加一个订单'); const bids = orders.filter(x => x.role === 'bid').map(x => ({ buyer_id: x.actor, product_ids: x.product_ids, amount: x.amount, quantity: x.quantity, budget: x.budget, task_id: x.task_id || null, currency: document.querySelector('#marketCurrency').value, constraints: { bundle_mode: x.bundle_mode } })); const asks = orders.filter(x => x.role === 'ask').map(x => ({ seller_id: x.actor, product_ids: x.product_ids, reserve: x.amount, quantity: x.quantity, currency: document.querySelector('#marketCurrency').value, metadata: { quality: x.quality } })); const mechanism = document.querySelector('#complexMechanism').value, extra = document.querySelector('#mechanismFields').querySelector('[data-complex-field]') ? readComplexFields(document.querySelector('#mechanismFields')) : {}; const supply = Object.fromEntries(product_ids.map(id => [id, asks.filter(x => x.product_ids.includes(id)).reduce((sum, x) => sum + x.quantity, 0)])); const response = await WorkbenchAPI.post('/operations/market', { product_ids, parameters: { mechanism, scenario_name: document.querySelector('#scenarioName').value, currency: document.querySelector('#marketCurrency').value, purpose: document.querySelector('#marketPurpose').value, settlement_period: document.querySelector('#settlementPeriod').value, budget: +document.querySelector('#complexBudget').value, buyer_id: document.querySelector('#complexBuyer').value, supply, bids, asks, quotes: quoteResults.map(x => ({ product_id: x.product_id, price: x.price })), ...extra } }); marketResult = response.result; renderTrace(marketResult.trace); document.querySelector('#complexMarketResult').textContent = JSON.stringify(marketResult.outcome, null, 2); switchTab(5); toast('市场计算完成'); } catch (e) { renderFailureTrace('market', e, 5); } };
  document.querySelectorAll('[data-result-view]').forEach(x => x.onclick = () => { document.querySelectorAll('[data-result-view]').forEach(y => y.classList.toggle('active', y === x)); document.querySelector('#complexMarketResult').textContent = marketResult ? JSON.stringify(marketResult[x.dataset.resultView], null, 2) : '等待执行'; });
  document.querySelector('#downloadMarketResult').onclick = () => marketResult ? downloadJSON(`market-${Date.now()}.json`, marketResult) : toast('暂无市场结果');
};

const complexBaseDetail = detail;
detail = function () {
  complexBaseDetail();
  const node = state.instances.find(x => x.id === state.selected);
  if (!node || !['price', 'market'].includes(node.type) || state.selectedNodes.length > 1) return;
  const panel = document.querySelector('#detail');
  const section = document.createElement('div');
  section.className = 'section node-complex-tabs';
  section.innerHTML = `<div class="section-title"><b>模块工作区</b><span>配置与执行过程</span></div><label class="field">API 产品 ID（多个以逗号分隔）<input id="nodeProductIds" value="${escapeAttribute((node.config.productIds || []).join(', '))}" placeholder="retail-demand, weather-stream"></label><div class="mini-tabs">${['输入', '方法', '参数', '参与方/订单', '执行 Trace', '输出', '错误与诊断'].map((x, i) => `<button data-node-complex-tab="${i}" class="${i === 0 ? 'active' : ''}">${x}</button>`).join('')}</div><div class="node-complex-content"><pre>${escapeText(JSON.stringify({ inputs: resolveInputs(node), method: node.components.filter(x => x.enabled).map(x => x.current), parameters: node.config, participants: node.parties, trace: node.output?.trace || [], output: node.output, errors: errors(node) }, null, 2))}</pre></div>`;
  panel.querySelector('.detail-actions')?.before(section);
  section.querySelector('#nodeProductIds').onchange = event => { node.config.productIds = event.target.value.split(',').map(x => x.trim()).filter(Boolean); save(); };
  section.querySelectorAll('[data-node-complex-tab]').forEach(button => button.onclick = () => { const views = [resolveInputs(node), node.components.filter(x => x.enabled), node.config, node.parties, node.output?.trace || [], node.output, errors(node)]; section.querySelectorAll('[data-node-complex-tab]').forEach(x => x.classList.toggle('active', x === button)); section.querySelector('pre').textContent = JSON.stringify(views[+button.dataset.nodeComplexTab], null, 2); });
};

const complexOfflineExecuteModule = executeModule;
executeModule = function (node, inputs) {
  const result = complexOfflineExecuteModule(node, inputs);
  if (['price', 'market'].includes(node.type)) {
    result.execution_mode = 'offline';
    result.trace = [{ step: 'offline_semantic_executor', status: 'succeeded', warning: '未连接 API；结果为明确标记的浏览器语义演示' }];
  }
  return result;
};

const complexBaseRunNode = runNode;
runNode = async function (node) {
  if (!['price', 'market'].includes(node.type) || !WorkbenchAPI.online) return complexBaseRunNode(node);
  const validation = errors(node);
  if (validation.length) return toast('请先修复输入错误');
  const inputs = resolveInputs(node);
  const fromInputs = inputs.flatMap(input => {
    const content = input.content || {};
    const ids = [content.product_id, content.id].filter(Boolean);
    const uri = content.uri || content.data?.uri || content.config?.uri;
    if (typeof uri === 'string' && uri.startsWith('catalog://')) ids.push(uri.slice('catalog://'.length));
    return ids;
  });
  const productIds = [...new Set([...(node.config.productIds || []), ...fromInputs])];
  if (!productIds.length) {
    node.status = 'failed';
    node.output = { execution_mode: 'online', trace: [{ step: 'resolve_products', status: 'failed', error: '请在模块工作区填写 API 产品 ID，或连接 catalog 产品输入' }] };
    save(); nodes(); detail(); return toast('缺少可执行的数据产品 ID');
  }
  node.status = 'running'; nodes(); detail();
  const started = new Date(), runId = `run-${state.seq++}`;
  try {
    let operation, payload;
    if (node.type === 'price') {
      operation = 'pricing';
      const selected = node.components.find(x => x.key === 'pricing')?.current;
      const schemas = await WorkbenchAPI.get('/workbench/schemas');
      const model = schemas.pricing[selected] ? selected : 'pricing.quality_freshness';
      payload = { product_id: productIds[0], parameters: { model, base_price: 100000, quality: 0.9, freshness: 0.85, floor: Number(node.config.floor || 0) * 100000, ceiling: Number(node.config.ceiling || 1.2) * 100000 } };
    } else {
      operation = 'market';
      const selected = node.components.find(x => x.key === 'mechanism')?.current;
      const mechanismMap = { 'MultiAttributeMarketMatcher': 'multi_attribute_matching', 'BundleDemandMatcher': 'bundle_matching' };
      const mechanism = mechanismMap[selected] || selected || (node.config.matchingMode === 'bundle' ? 'bundle_matching' : 'multi_attribute_matching');
      const bids = (node.parties || []).filter(x => x.role === 'buyer').map(x => ({ buyer_id: x.id, product_ids: productIds, amount: x.bid, budget: x.budget, quantity: x.quantity || 1, constraints: { bundle_mode: node.config.matchingMode === 'bundle' ? 'and' : 'xor' } }));
      const asks = (node.parties || []).filter(x => x.role === 'seller').map((x, index) => ({ seller_id: x.id, product_ids: [productIds[index % productIds.length]], reserve: x.ask ?? x.reserve, quantity: x.quantity || 1, metadata: { quality: .9 } }));
      payload = { product_ids: productIds, parameters: { mechanism, budget: Math.max(0, ...bids.map(x => Number(x.budget || 0))), bids, asks, supply: Object.fromEntries(productIds.map(id => [id, asks.filter(x => x.product_ids.includes(id)).reduce((sum, x) => sum + x.quantity, 0)])) } };
    }
    const response = await WorkbenchAPI.post(`/operations/${operation}`, payload);
    node.output = { ...response.result, execution_mode: 'online', api_run_id: response.run_id, api_artifact_id: response.artifact_id };
    node.status = 'success';
    state.connections.filter(edge => edge.from === node.id).forEach(edge => { edge.content = node.output; edge.type = io[node.type].out; edge.updatedAt = new Date().toLocaleString(); });
    state.runs.unshift({ id: runId, module: node.id, status: '成功', execution_mode: 'online', started_at: started.toISOString(), duration_ms: Date.now() - started.getTime(), inputs: inputs.length, output_type: io[node.type].out });
    state.artifacts.unshift({ id: response.artifact_id, type: io[node.type].out, producer: node.id, created_at: new Date().toISOString(), size: JSON.stringify(node.output).length, content: node.output });
    save(); nodes(); detail(); toast(`${node.name} 已由 DataValor API 执行`);
  } catch (error) {
    node.status = 'failed';
    node.output = { execution_mode: 'online', trace: [{ step: 'api_execution', status: 'failed', error: error.message }] };
    state.runs.unshift({ id: runId, module: node.id, status: '失败', execution_mode: 'online', started_at: started.toISOString(), error: error.message });
    save(); nodes(); detail(); toast(`运行失败：${error.message}`);
  }
};

const renderOfflinePageWithPlainCopy = renderOfflinePage;
renderOfflinePage = function(page, reason) {
  renderOfflinePageWithPlainCopy(page, reason);
  document.querySelectorAll('#resourceView b, #resourceView small, #resourceView p').forEach(element => {
    if (element.textContent === '准备真实运行') element.textContent = '连接本地服务';
    if (element.textContent === '组件能力目录') element.textContent = '组件目录';
    if (element.textContent.includes('真实执行')) {
      element.textContent = element.textContent.replace('真实执行', '由 Python 服务执行');
    }
  });
};
