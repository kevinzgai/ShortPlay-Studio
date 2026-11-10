/* 回归脚本共用的「安全清场」：只删本次自己新建的项目，真实项目一个都不碰。
 *
 * 踩过的坑（2026-11-09）：
 *   以前的写法是
 *     const beforeIds = new Set((await api("projects")).projects.map(p => p.id));
 *     ... 跑完把不在 beforeIds 里的全删掉
 *   只要开跑那一刻列表取回来是空（服务刚重启 / 静态资源没挂好 / 请求偶发失败），
 *   beforeIds 就是空集合，收尾时把「全部真实项目」都当成新建的删进 .trash。
 *   实测一次干掉过 24 个真实项目。
 *
 * 本模块刻意自己发 fetch、不接收各脚本的 api() 封装：
 * 那些封装签名并不统一（有的是 (path, body)、有的是 (path, init)），
 * 混用会把请求体塞错、服务端读不到 id，接口明明报错脚本却当成删除成功。
 *
 * 现在的规矩：
 *   1. 快照必须成功且非空，否则直接拒跑（一个项目都不删）
 *   2. 只删「不在快照里」且「createdAt 不早于开跑时刻」的项目；老项目一律不碰
 *   3. 时间统一用本地时间，与 server.py 的 datetime.now().isoformat() 对齐
 *   4. 每次删除都核对服务端返回值，删失败要吵出来
 *   5. 收尾对账：项目总数必须回到开跑水平
 */

const DEFAULT_BASE = "http://127.0.0.1:8177";

/** 本地时间，格式与 server.py 的 createdAt 一致：2026-11-09T17:40:20 */
function localStamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
    "T" + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

async function getProjects(base) {
  const res = await fetch(base + "/api/projects", { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  const json = await res.json();
  const rows = (json && json.projects) || [];
  if (!Array.isArray(rows)) throw new Error("项目列表格式异常：" + JSON.stringify(json).slice(0, 200));
  return rows;
}

async function deleteProject(base, id) {
  const res = await fetch(base + "/api/projects/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id })
  });
  let json = null;
  try { json = await res.json(); } catch (_) {}
  if (!res.ok || !json || json.ok !== true) {
    throw new Error("服务端拒绝删除：" + (json && (json.error || json.message) || "HTTP " + res.status));
  }
  return json;
}

/**
 * 开跑前拍快照。空项目库是异常状态，直接拒跑，避免收尾把真实项目全删。
 * @param {{base?:string, label?:string}} opt
 * @returns {Promise<{ids:Set<string>, startedAt:string, count:number, base:string}>}
 */
export async function snapshotProjects(opt = {}) {
  const base = opt.base || DEFAULT_BASE;
  const label = opt.label || "verify";
  let rows;
  try {
    rows = await getProjects(base);
  } catch (err) {
    console.error(
      "\n[安全拦截] 开跑时读不到项目列表（" + label + "）：" + err.message + "\n" +
      "  服务没起来 / 端口不对都会这样。本用例直接退出，不动任何项目。\n"
    );
    process.exit(2);
  }
  if (rows.length === 0) {
    console.error(
      "\n[安全拦截] 开跑时项目列表为空（" + label + "）。\n" +
      "  这通常是服务刚重启、路径没加载完或请求偶发失败。\n" +
      "  为免收尾时把真实项目当成「本次新建」删进 .trash，本用例直接退出，不动任何项目。\n" +
      "  确认项目库本来就应该为空时，设环境变量 SHORTPLAY_ALLOW_EMPTY=1 再跑。\n"
    );
    if (process.env.SHORTPLAY_ALLOW_EMPTY !== "1") process.exit(2);
  }
  const snap = { ids: new Set(rows.map((p) => p.id)), startedAt: localStamp(), count: rows.length, base };
  console.log("[清场] " + label + " 开跑快照：" + snap.count + " 个项目，起点 " + snap.startedAt);
  installCrashGuard(snap, label);
  return snap;
}

/* 崩溃也要清场（2026-11-10 加）。
 *
 * 为什么必须有：cleanupNewProjects 只删「不早于开跑时刻」的项目，这是防误删真实项目的安全规则；
 * 但它有个副作用——某次崩溃/超时跳过了清场，那些临时项目在下一轮就变成「老项目」，
 * 从此永远没人清，会一直堆在 projects/ 里。实测三次崩溃漏了 97 个。
 *
 * 这里在拍快照时就挂上进程级兜底：脚本抛未捕获异常 / Promise 未处理拒绝时，
 * 先按同一套规则清场，再以 1 退出。20 个套件都调 snapshotProjects，所以不用逐个改。
 */
let _guardInstalled = false;
function installCrashGuard(snap, label) {
  if (_guardInstalled) return;
  _guardInstalled = true;
  const bail = (err) => {
    console.error("\n[清场] 脚本异常退出，先清场再退：" + ((err && err.message) || err));
    Promise.resolve()
      .then(() => cleanupNewProjects(snap, { label: label + " · 异常清场" }))
      .catch(() => {})
      .then(() => reportBalance(snap))
      .catch(() => {})
      .then(() => process.exit(1));
  };
  process.on("uncaughtException", bail);
  process.on("unhandledRejection", bail);
}

/**
 * 收尾清场：只删本次会话新建的项目。
 * @param {{ids:Set<string>, startedAt:string, base:string}} snap
 * @param {{keep?:string[], label?:string}} opt
 * @returns {Promise<string[]>} 实际删掉的 id
 */
export async function cleanupNewProjects(snap, opt = {}) {
  const base = (snap && snap.base) || DEFAULT_BASE;
  const keep = new Set(opt.keep || []);
  const label = opt.label || "verify";
  let rows;
  try {
    rows = await getProjects(base);
  } catch (err) {
    console.error("[清场] 读取项目列表失败，跳过清场（宁可不删）：" + err.message);
    return [];
  }
  const mine = rows.filter((p) => {
    if (!p || !p.id) return false;
    if (snap.ids.has(p.id)) return false;
    if (keep.has(p.id)) return false;
    const born = String(p.createdAt || "");
    if (born && born < snap.startedAt) return false; // 老项目（含从回收站捞回的），不碰
    return true;
  });
  if (!mine.length) {
    console.log("[清场] " + label + " 没有需要清理的临时项目");
    return [];
  }
  const removed = [];
  for (const p of mine) {
    try {
      await deleteProject(base, p.id);
      removed.push(p.id);
      console.log("[清场] 已删除临时项目 " + p.id + "（" + (p.name || "未命名") + "）");
    } catch (err) {
      console.error("[清场] 删除失败 " + p.id + "（" + (p.name || "未命名") + "）：" + err.message);
    }
  }
  return removed;
}

/** 收尾对账：项目总数是否回到开跑时的水平 */
export async function reportBalance(snap) {
  const base = (snap && snap.base) || DEFAULT_BASE;
  try {
    const rows = await getProjects(base);
    const extra = rows.length - snap.count;
    console.log("[清场] 收尾对账：开跑 " + snap.count + " 个 → 现在 " + rows.length + " 个" +
      (extra === 0 ? "（平衡）" :
        extra > 0 ? "（多出 " + extra + " 个，需人工看一眼）" :
          "（少了 " + (-extra) + " 个，需人工看一眼）"));
  } catch (_) { /* 对账失败不影响结果 */ }
}
