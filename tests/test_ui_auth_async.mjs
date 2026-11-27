import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

class Element {
  constructor() {
    this.listeners = new Map();
    this.classList = { toggle() {} };
    this.dataset = {};
    this.textContent = "";
    this.value = "";
    this.resetCount = 0;
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  append() {}
  replaceChildren() {}
  close() {}
  focus() {}
  showModal() {}

  reset() {
    this.resetCount += 1;
  }
}

function response(data) {
  return {
    ok: true,
    status: 200,
    async json() {
      return { data };
    },
  };
}

test("account creation resets the submitted form after the API await", async () => {
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const accountForm = element("#accountForm");
  element("#accountUsername").value = "researcher-01";
  element("#accountPassword").value = "researcher-password";
  element("#accountRole").value = "user";

  const document = {
    body: { dataset: { authPage: "admin" } },
    querySelector: element,
    createElement() {
      return new Element();
    },
  };
  const fetch = async (path, options = {}) => {
    if (path === "/api/auth/me") {
      return response({ account: { role: "admin", username: "admin" } });
    }
    if (path === "/api/admin/accounts" && options.method === "POST") {
      return response({ account: { username: "researcher-01" } });
    }
    if (path === "/api/admin/accounts") return response({ accounts: [] });
    throw new Error(`unexpected request: ${path}`);
  };
  const source = await readFile(new URL("../UI/auth.js", import.meta.url), "utf8");
  vm.runInNewContext(source, {
    document,
    fetch,
    window: { location: { assign() {}, replace() {} } },
    console,
  });
  await new Promise(setImmediate);

  const event = {
    currentTarget: accountForm,
    preventDefault() {},
  };
  const completion = accountForm.listeners.get("submit")(event);
  event.currentTarget = null;
  await completion;

  assert.equal(accountForm.resetCount, 1);
  assert.equal(element("#accountFeedback").textContent, "账号已创建，可立即登录独立工作区。");
});
