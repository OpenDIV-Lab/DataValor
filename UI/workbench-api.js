const WorkbenchAPI = {
  online: false,

  async request(path, options = {}) {
    const response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      const detail = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg).join("; ")
        : body.detail;
      throw new Error(detail || body.error?.message || `HTTP ${response.status}`);
    }
    return body.data;
  },

  get(path) {
    return this.request(path);
  },

  post(path, data = {}) {
    return this.request(path, { method: "POST", body: JSON.stringify(data) });
  },
};
