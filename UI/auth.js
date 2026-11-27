async function authRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body.data;
}

function feedback(element, message, success = false) {
  element.textContent = message;
  element.classList.toggle("success", success);
}

async function logout() {
  await authRequest("/api/auth/logout", { method: "POST" }).catch(() => null);
  window.location.assign("/login");
}

function bindLogin() {
  const form = document.querySelector("#loginForm");
  const message = document.querySelector("#loginFeedback");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    feedback(message, "正在验证账号…");
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await authRequest("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: document.querySelector("#loginUsername").value,
          password: document.querySelector("#loginPassword").value,
        }),
      });
      window.location.assign("/");
    } catch (error) {
      const text = error.message === "invalid username or password"
        ? "账号或密码不正确。"
        : error.message;
      feedback(message, text);
      submit.disabled = false;
    }
  });
}

function openPasswordDialog(account) {
  const dialog = document.querySelector("#passwordDialog");
  document.querySelector("#resetAccountId").value = account.account_id;
  document.querySelector("#passwordDialogAccount").textContent = `为 ${account.username} 设置新密码（至少 10 个字符）`;
  document.querySelector("#resetPassword").value = "";
  feedback(document.querySelector("#passwordFeedback"), "");
  dialog.showModal();
  document.querySelector("#resetPassword").focus();
}

function accountRow(account) {
  const row = document.createElement("tr");
  const identity = document.createElement("td");
  identity.className = "account-name";
  const name = document.createElement("strong");
  name.textContent = account.username;
  const id = document.createElement("small");
  id.textContent = account.account_id;
  identity.append(name, id);

  const role = document.createElement("td");
  role.textContent = account.role === "admin" ? "管理员" : "普通账号";
  const statusCell = document.createElement("td");
  const status = document.createElement("span");
  status.className = `account-status${account.active ? "" : " inactive"}`;
  status.textContent = account.active ? "使用中" : "已停用";
  statusCell.append(status);
  const created = document.createElement("td");
  created.textContent = new Date(account.created_at).toLocaleString("zh-CN", { hour12: false });

  const actions = document.createElement("td");
  actions.className = "account-actions";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = `account-action${account.active ? " danger" : ""}`;
  toggle.textContent = account.active ? "停用" : "启用";
  toggle.addEventListener("click", async () => {
    await authRequest(`/api/admin/accounts/${account.account_id}`, {
      method: "PATCH",
      body: JSON.stringify({ active: !account.active }),
    });
    await loadAccounts();
  });
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "account-action";
  reset.textContent = "重置密码";
  reset.addEventListener("click", () => openPasswordDialog(account));
  actions.append(toggle, reset);
  row.append(identity, role, statusCell, created, actions);
  return row;
}

async function loadAccounts() {
  const data = await authRequest("/api/admin/accounts");
  document.querySelector("#accountRows").replaceChildren(...data.accounts.map(accountRow));
  const active = data.accounts.filter((item) => item.active).length;
  document.querySelector("#accountCount").textContent = `${data.accounts.length} 个账号 · ${active} 个启用`;
}

function bindPasswordDialog() {
  const dialog = document.querySelector("#passwordDialog");
  document.querySelector("#cancelPasswordReset").addEventListener("click", () => dialog.close());
  document.querySelector("#resetPasswordForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#passwordFeedback");
    feedback(message, "正在保存新密码…");
    try {
      const accountId = document.querySelector("#resetAccountId").value;
      await authRequest(`/api/admin/accounts/${accountId}/password`, {
        method: "POST",
        body: JSON.stringify({ password: document.querySelector("#resetPassword").value }),
      });
      dialog.close();
      feedback(document.querySelector("#accountFeedback"), "密码已重置，原有登录会话已经失效。", true);
    } catch (error) {
      feedback(message, error.message);
    }
  });
}

async function bindAdmin() {
  try {
    const me = await authRequest("/api/auth/me");
    if (me.account.role !== "admin") {
      window.location.replace("/");
      return;
    }
    document.querySelector("#adminIdentity").textContent = `${me.account.username} · 管理员`;
    await loadAccounts();
  } catch {
    window.location.replace("/login");
    return;
  }

  bindPasswordDialog();
  document.querySelector("#refreshAccounts").addEventListener("click", () => {
    loadAccounts().catch((error) => feedback(document.querySelector("#accountFeedback"), error.message));
  });
  document.querySelector("#adminLogout").addEventListener("click", logout);
  document.querySelector("#accountForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const message = document.querySelector("#accountFeedback");
    feedback(message, "正在创建账号…");
    try {
      await authRequest("/api/admin/accounts", {
        method: "POST",
        body: JSON.stringify({
          username: document.querySelector("#accountUsername").value,
          password: document.querySelector("#accountPassword").value,
          role: document.querySelector("#accountRole").value,
        }),
      });
      form.reset();
      feedback(message, "账号已创建，可立即登录独立工作区。", true);
      await loadAccounts();
    } catch (error) {
      feedback(message, error.message);
    }
  });
}

if (document.body.dataset.authPage === "login") bindLogin();
if (document.body.dataset.authPage === "admin") bindAdmin();
