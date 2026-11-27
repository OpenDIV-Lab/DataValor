const OfflineWorkbench = (() => {
  const STORAGE_KEY = "datavalor.offline.workspace.v1";
  const EMPTY_WORKSPACE = { products: [], participants: [], artifacts: [], runs: [], batches: [] };
  let memoryWorkspace = null;

  function copy(value) {
    return JSON.parse(JSON.stringify(value ?? null));
  }

  function seed() {
    return window.DATAVALOR_STANDALONE || { scenarios: [], schemas: {}, components: [] };
  }

  function readWorkspace() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      return value ? { ...copy(EMPTY_WORKSPACE), ...JSON.parse(value) } : copy(EMPTY_WORKSPACE);
    } catch (_) {
      memoryWorkspace ||= copy(EMPTY_WORKSPACE);
      return copy(memoryWorkspace);
    }
  }

  function writeWorkspace(workspace) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace));
    } catch (_) {
      memoryWorkspace = copy(workspace);
    }
  }

  function upsert(workspace, collection, idField, value) {
    const index = workspace[collection].findIndex((item) => item[idField] === value[idField]);
    if (index === -1) workspace[collection].push(copy(value));
    else workspace[collection][index] = copy(value);
  }

  function inferSchema(records) {
    const schema = {};
    records.forEach((record) => {
      Object.entries(record || {}).forEach(([key, value]) => {
        const type = value === null ? "null" : Array.isArray(value) ? "array" : typeof value;
        schema[key] ||= { types: [], nullable: false };
        if (!schema[key].types.includes(type)) schema[key].types.push(type);
        if (value === null) schema[key].nullable = true;
      });
    });
    return schema;
  }

  function splitDelimitedLine(line, delimiter) {
    const cells = [];
    let current = "";
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (character === '"' && quoted && line[index + 1] === '"') {
        current += '"'; index += 1;
      } else if (character === '"') quoted = !quoted;
      else if (character === delimiter && !quoted) { cells.push(current); current = ""; }
      else current += character;
    }
    cells.push(current);
    return cells;
  }

  function parseInput(inputType, content) {
    const errors = [];
    let records = [];
    try {
      if (inputType === "json") {
        const parsed = typeof content === "string" ? JSON.parse(content || "[]") : content;
        records = Array.isArray(parsed) ? parsed : [parsed];
      } else if (inputType === "jsonl") {
        records = String(content || "").split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line));
      } else if (inputType === "csv" || inputType === "tsv") {
        const delimiter = inputType === "tsv" ? "\t" : ",";
        const lines = String(content || "").split(/\r?\n/).filter((line) => line.trim());
        const headers = lines.length ? splitDelimitedLine(lines[0], delimiter) : [];
        records = lines.slice(1).map((line) => Object.fromEntries(headers.map((header, index) => [header, splitDelimitedLine(line, delimiter)[index] ?? ""])));
      } else if (inputType === "key_value") {
        const parsed = typeof content === "string" ? JSON.parse(content || "{}") : content;
        records = [parsed];
      } else {
        throw new Error(`离线文件暂不支持 ${inputType} 输入`);
      }
      if (records.some((record) => !record || typeof record !== "object" || Array.isArray(record))) throw new Error("每条记录必须是对象");
    } catch (error) {
      errors.push({ message: error.message }); records = [];
    }
    return { records, schema: inferSchema(records), errors, input_type: inputType };
  }

  function dashboard(workspace) {
    const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
    const kinds = Object.fromEntries(["governance", "profile", "evaluation", "valuation", "pricing", "market"].map((kind) => [kind, workspace.artifacts.filter((item) => item.kind === kind).length]));
    const totalRecords = workspace.products.reduce((sum, item) => sum + number(item.data?.record_count ?? item.records?.length), 0);
    const referenceValue = workspace.products.reduce((sum, item) => sum + number(item.metadata?.asking_price), 0);
    return {
      summary: {
        products: workspace.products.length, participants: workspace.participants.length,
        total_records: totalRecords, reference_value: referenceValue,
        batches: workspace.batches.length, runs: workspace.runs.length,
        artifacts: workspace.artifacts.length, components: seed().components.length,
        available_capabilities: 0,
      },
      recent_runs: [...workspace.runs].reverse().slice(0, 5),
      modules: {
        products: { registered: workspace.products.length, total_records: totalRecords, reference_value: referenceValue },
        governance: { registered: kinds.governance }, profile: { registered: kinds.profile },
        evaluation: { registered: kinds.evaluation }, valuation: { registered: kinds.valuation, total_value: 0 },
        pricing: { registered: kinds.pricing, total_price: 0 },
        market: { registered: kinds.market, participants: workspace.participants.length, allocations: 0 },
      },
    };
  }

  function loadScenario(scenarioId) {
    const scenario = seed().scenarios.find((item) => item.scenario_id === scenarioId);
    if (!scenario) throw new Error(`未知场景：${scenarioId}`);
    const workspace = readWorkspace();
    let loaded = 0; let updated = 0;
    scenario.products.forEach((product) => {
      if (workspace.products.some((item) => item.product_id === product.product_id)) updated += 1;
      else loaded += 1;
      upsert(workspace, "products", "product_id", product);
    });
    (scenario.offline_participants || []).forEach((participant) => upsert(workspace, "participants", "participant_id", participant));
    writeWorkspace(workspace);
    return {
      scenario_id: scenarioId, loaded, updated,
      product_ids: scenario.products.map((item) => item.product_id),
      participants_registered: (scenario.offline_participants || []).length,
      participant_ids: (scenario.offline_participants || []).map((item) => item.participant_id),
      scenario: copy(scenario),
    };
  }

  async function request(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const body = typeof options.body === "string" ? JSON.parse(options.body || "{}") : (options.body || {});
    const workspace = readWorkspace();

    if (method === "GET" && path === "/health") return { status: "offline_ready", mode: "standalone" };
    if (method === "GET" && path === "/workbench/scenarios") return { scenarios: copy(seed().scenarios) };
    if (method === "GET" && path === "/workbench/schemas") return copy(seed().schemas);
    if (method === "GET" && path === "/components") return { components: copy(seed().components) };
    if (method === "GET" && path === "/products") return { products: copy(workspace.products) };
    if (method === "GET" && path === "/participants") return { participants: copy(workspace.participants) };
    if (method === "GET" && path === "/artifacts") return { artifacts: copy(workspace.artifacts) };
    if (method === "GET" && path === "/runs") return { runs: copy(workspace.runs) };
    if (method === "GET" && path === "/batches") return { batches: copy(workspace.batches) };
    if (method === "GET" && path === "/dashboard") return dashboard(workspace);

    const scenarioMatch = path.match(/^\/workbench\/scenarios\/([^/]+)\/load$/);
    if (method === "POST" && scenarioMatch) return loadScenario(decodeURIComponent(scenarioMatch[1]));
    if (method === "POST" && path === "/inputs/preview") return { preview: parseInput(body.input_type, body.content) };

    if (method === "POST" && path === "/products") {
      if (workspace.products.some((item) => item.product_id === body.product_id)) throw new Error("数据产品已存在");
      workspace.products.push(copy(body)); writeWorkspace(workspace); return { product: copy(body) };
    }
    const productMatch = path.match(/^\/products\/([^/]+)$/);
    if (method === "PUT" && productMatch) {
      upsert(workspace, "products", "product_id", body); writeWorkspace(workspace); return { product: copy(body) };
    }
    if (method === "DELETE" && productMatch) {
      const before = workspace.products.length;
      workspace.products = workspace.products.filter((item) => item.product_id !== decodeURIComponent(productMatch[1]));
      writeWorkspace(workspace); return { deleted: before !== workspace.products.length };
    }

    if (method === "POST" && path === "/participants") {
      if (workspace.participants.some((item) => item.participant_id === body.participant_id)) throw new Error("参与者已存在");
      workspace.participants.push(copy(body)); writeWorkspace(workspace); return { participant: copy(body) };
    }
    const participantMatch = path.match(/^\/participants\/([^/]+)$/);
    if (method === "PUT" && participantMatch) {
      upsert(workspace, "participants", "participant_id", body); writeWorkspace(workspace); return { participant: copy(body) };
    }
    if (method === "DELETE" && participantMatch) {
      const before = workspace.participants.length;
      workspace.participants = workspace.participants.filter((item) => item.participant_id !== decodeURIComponent(participantMatch[1]));
      writeWorkspace(workspace); return { deleted: before !== workspace.participants.length };
    }

    if (method === "POST" && path === "/batches") {
      const batch = OfflineExecutionEngine.executeBatch(workspace, body);
      writeWorkspace(workspace);
      return { batch: copy(batch) };
    }
    if (method === "POST" && path === "/market/agent-orders") {
      return copy(OfflineExecutionEngine.generateAgentOrders(workspace, body));
    }
    const operationMatch = path.match(/^\/operations\/([^/]+)$/);
    if (method === "POST" && operationMatch) {
      const operation = decodeURIComponent(operationMatch[1]);
      const productIds = body.product_ids?.length ? body.product_ids : body.product_id ? [body.product_id] : [];
      const batch = OfflineExecutionEngine.executeBatch(workspace, {
        product_ids: productIds,
        operations: [operation],
        parameters: { [operation]: body.parameters || {} },
        label: `Offline ${operation}`,
        fail_fast: true,
      });
      writeWorkspace(workspace);
      const stage = operation === "market" ? batch.market_stage : batch.items[0]?.stages?.[0];
      if (!stage || stage.status !== "succeeded") throw new Error(stage?.error?.message || `${operation} execution failed`);
      return { run_id: stage.run_id, artifact_id: stage.artifact_id, result: copy(stage.result) };
    }
    throw new Error(`离线工作区不支持 ${method} ${path}`);
  }

  return { request, storageKey: STORAGE_KEY };
})();
