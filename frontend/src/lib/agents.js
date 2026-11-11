/* =========================================================================
 * Agent 工作台 · 接口层
 * 与 lib/ai.js 保持同样的「同源 /api」约定；
 * 角色与技能都是文件，服务端每次调用重新读盘，保存后无需重启。
 * ========================================================================= */
const BASE = "";

function url(p) { return BASE + "/api/" + p; }

async function request(path, opts, timeoutMs) {
  const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs || 240000) : null;
  try {
    const r = await fetch(url(path), {
      method: opts && opts.method ? opts.method : "GET",
      headers: opts && opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts && opts.body ? JSON.stringify(opts.body) : undefined,
      signal: ctl ? ctl.signal : undefined,
      cache: "no-store"
    });
    let data = {};
    try { data = await r.json(); } catch (_) { data = {}; }
    if (!r.ok) throw new Error(data.detail || ("接口返回 " + r.status));
    return data;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

const post = (p, body, ms) => request(p, { method: "POST", body }, ms);
const qs = (o) => "?" + new URLSearchParams(o).toString();

export const AgentAPI = {
  list: () => request("agents"),
  prompt: (id) => request("agents/prompt" + qs({ id })),
  savePrompt: (id, content) => post("agents/save", { id, content }),
  patch: (id, patch) => post("agents/patch", { id, patch }),
  add: (spec) => post("agents/add", spec),
  remove: (id) => post("agents/delete", { id }),
  run: (id, payload) => post("agents/run", Object.assign({ id }, payload), 260000),

  skills: () => request("skills"),
  skill: (id) => request("skills/detail" + qs({ id })),
  saveSkill: (id, content) => post("skills/save", { id, content }),
  addSkill: (id, content) => post("skills/add", { id, content }),
  removeSkill: (id) => post("skills/delete", { id })
};

export default AgentAPI;
