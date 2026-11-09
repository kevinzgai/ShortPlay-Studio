/* =========================================================================
 * ShortPlay Studio · AI 编排层（自动分集 + 自动分镜）
 * ESM：浏览器与 Node 复用同一条编排链路（示例生成器直接 import）
 * 只做编排与归一化，界面状态由 app.js 管理；任何一集失败都只降级该集。
 * ========================================================================= */
import E from "./engine.js";

  var BASE = "";   // 相对路径，同源；Node 里由 setBase 指定
  function setBase(url) { BASE = String(url || "").replace(/\/$/, ""); }
  function url(p) { return (BASE || "") + "/api/" + p; }

  function post(path, body, timeoutMs) {
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, timeoutMs || 180000) : null;
    return fetch(url(path), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: ctl ? ctl.signal : undefined
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, data: j }; });
    }).then(function (res) {
      if (!res.ok) throw new Error((res.data && res.data.detail) || ("接口返回 " + res.status));
      return res.data;
    }).finally(function () { if (timer) clearTimeout(timer); });
  }

  function checkConfig() {
    return fetch(url("config"), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("探测失败 " + r.status);
      return r.json();
    });
  }

  /* ---------------- 语言模型接入（可存多条，切换一条生效） ---------------- */
  function llmProviders() {
    return fetch(url("llm/providers"), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("读取模型配置失败 " + r.status);
      return r.json();
    });
  }
  function llmSave(p) { return post("llm/providers/save", p, 20000); }
  function llmActivate(id) { return post("llm/providers/activate", { id: id }, 20000); }
  function llmRemove(id) { return post("llm/providers/delete", { id: id }, 20000); }
  /** 真发一次最小请求；apiKey 传 null 表示沿用已存的 Key。 */
  function llmTest(p) { return post("llm/test", p, 45000); }

  function plan(script, parsed, wanted) {
    return post("ai/plan", {
      script: script, scenes: parsed.scenes,
      episodes: (Number(wanted) > 0 ? Number(wanted) : "auto")
    }, 150000);
  }

  /** 工作流第 1 阶段：小说体 / 散文体 → 场次剧本（服务端做原文保真校验）。 */
  function adaptNovel(script) {
    return post("ai/adapt", { script: script }, 240000);
  }

  /** 格式识别：没有场次行、且几乎没有「角色：台词」行，就当成小说体。 */
  function isNovelScript(script) {
    var t = String(script || "");
    if (/^\s*第\s*\d+\s*场/m.test(t)) return false;
    if (/^\s*(场景\s*\d+|INT\.|EXT\.|Scene\s*\d+)/im.test(t)) return false;
    var dlg = t.split("\n").filter(function (l) {
      return /^[^：:\s△第《【]{1,12}(?:[（(][^）)]*[）)])?\s*[：:]\s*\S/.test(l.trim());
    }).length;
    if (dlg >= 3) return false;  // 无场次行但有成段对白，算简易剧本而不是小说
    return t.replace(/\s/g, "").length >= 60;
  }

  /** 资产链 stage：剧本 / 小说全文 + 场次索引 → 资产包（角色/场景/道具 + 关键提示词）。 */
  function assets(script, parsed) {
    return post("ai/assets", {
      script: script, scenes: (parsed && parsed.scenes) || []
    }, 240000);
  }

  /** 资产包 + 分镜表 → 每镜起始帧提示词（纯模板，不调模型）。 */
  function frames(shots, pack, aspect) {
    return post("ai/frames", { shots: shots, pack: pack, aspect: aspect || "16:9" }, 90000);
  }

  /** 单个角色 / 场景的形象补全：只改这一项，不重跑整剧本分解。 */
  function fillAsset(body) {
    return post("ai/asset-fill", body, 150000);
  }

  /** 本地 ComfyUI 探测 / 批量出图队列。generate 秒回 jobId，之后轮询 job。 */
  function comfyStatus() {
    return fetch(url("comfy/status"), { cache: "no-store" }).then(function (r) {
      return r.json();
    });
  }
  function comfyGenerate(body) {
    return post("comfy/generate", body, 30000);
  }
  /** 只拼提示词、不出图：用来核对「界面上的描述」和「本地真正发的那串」是否一致 */
  function comfyPrompt(body) {
    return post("comfy/prompt", body, 15000);
  }

  // 参考图上传：原文件直接落盘（服务端不压缩），回一个可 <img src> 的地址。
  // 大图 base64 走网络要一会儿，超时给足。
  function uploadProjectRef(body) {
    return post("projects/upload-ref", body, 120000);
  }
  function comfyJob(id, full) {
    return fetch(url("comfy/job?id=" + encodeURIComponent(id) + (full ? "&full=1" : "")),
      { cache: "no-store" }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.detail || ("任务查询失败 " + r.status));
        return j;
      });
    });
  }

  /** 整个项目打包：文本在前端渲染，资产正文与服务端 README / manifest 一起压成 zip。 */
  function exportZip(body) {
    return fetch(url("export/zip"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error((j && j.detail) || ("打包失败 " + r.status));
        });
      }
      var name = "export.zip";
      var cd = r.headers.get("Content-Disposition") || "";
      var m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
      if (m) { try { name = decodeURIComponent(m[1]); } catch (e) { /* 保持默认 */ } }
      return r.blob().then(function (b) { return { blob: b, name: name }; });
    });
  }

  function storyboard(script, parsed, ep, config) {
    var scenes = parsed.scenes.filter(function (s) {
      return s.no >= ep.sceneFrom && s.no <= ep.sceneTo;
    });
    return post("ai/storyboard", {
      script: E.scriptSlice(script, parsed, ep) || script,
      episode: ep, scenes: scenes, config: config
    }, 180000);
  }

  /** 模型输出 → 界面 shot 结构（统一 id / 集号 / 镜号 / 场景标签）。 */
  function toShots(groups, episodes, parsed, config) {
    var shots = [], n = 0;
    episodes.forEach(function (ep, ei) {
      (groups[ei] || []).forEach(function (raw, i) {
        n += 1;
        var scene = parsed.scenes.filter(function (x) { return x.no === raw.sceneNo; })[0]
          || parsed.scenes.filter(function (x) { return x.no >= ep.sceneFrom && x.no <= ep.sceneTo; })[0]
          || parsed.scenes[0] || { no: ep.sceneFrom };
        shots.push({
          id: "ai_e" + ep.no + "_s" + (i + 1),
          no: n, code: "", originCode: "",
          sceneNo: raw.sceneNo,
          sceneLabel: E.sceneLabel(scene),
          kind: raw.kind, visual: raw.visual, size: raw.size,
          duration: raw.duration, dialogue: raw.dialogue || "",
          speaker: raw.speaker || "", notes: raw.notes || "",
          edited: {}, source: raw.visual, episode: ep.no, ai: raw.ai !== false,
          detail: E.normalizeDetail(raw.detail), patched: !!raw.patched
        });
      });
    });
    shots = E.renumberShots(shots, episodes);
    shots.forEach(function (s) { s.originCode = s.code; });
    return shots;
  }

  /** 某一集 AI 失败时的本地兜底镜头。 */
  function localShotsForEpisode(parsed, config, ep, localAll) {
    var picked = localAll.filter(function (s) {
      return s.sceneNo >= ep.sceneFrom && s.sceneNo <= ep.sceneTo;
    });
    return picked.map(function (s, i) {
      return Object.assign({}, s, {
        id: "local_e" + ep.no + "_s" + (i + 1),
        episode: ep.no, ai: false
      });
    });
  }

  /**
   * 完整链路：分集 → 逐集分镜 → 归一化。
   * onProgress(stage, text) 用于界面显示进度；degraded 记录哪些集降级了。
   */
  function run(opts) {
    var script = opts.script, parsed = opts.parsed, config = opts.config || {};
    var wanted = opts.episodes || "auto";
    var onProgress = opts.onProgress || function () {};
    var out = {
      episodes: [], shots: [], model: "", source: "ai",
      degraded: [], warnings: [], planSource: "ai", adapt: null,
      assetPack: null, assetWarnings: [], frames: [], frameStats: null,
      coverage: { dialogueTotal: 0, dialogueFromModel: 0, actionTotal: 0, actionFromModel: 0, patched: 0 }
    };
    var localAll = E.buildStoryboard(parsed, config, 0);
    var pack = null;

    // 工作流 stage 1：识别格式 → （小说体）忠实转写 → 重新解析
    return checkConfig().then(function (cfg) {
      if (!cfg.llm) throw new Error("NO_KEY");
      out.model = cfg.model || "";
      if (!isNovelScript(script)) return null;
      onProgress("adapt", "检测到小说体 / 散文体，正在忠实转写成场次剧本…");
      return post("ai/adapt", { script: script }, 240000).then(function (r) {
        if (!r.script || r.script.length < 40) throw new Error("转写没有返回有效剧本");
        script = r.script;
        parsed = E.parseScript(script);          // 关键：后续所有阶段必须基于转写版
        localAll = E.buildStoryboard(parsed, config, 0);
        out.adapt = {
          script: r.script, coverage: r.coverage || {},
          warnings: r.warnings || [], model: r.model || ""
        };
        (r.warnings || []).forEach(function (w) { out.warnings.push("转写校验：" + w); });
        onProgress("adapt", "转写完成：" + parsed.stats.scenes + " 场 / " +
          parsed.stats.lines + " 句对白，进入剧本体检…");
      });
    }).then(function () {
      // 工作流 stage 2：资产分解。失败不阻断 —— 退回 E.buildAssets 的规则结果，
      // 只是提示词里少了固定关键词串，出片一致性会退化，界面会明说。
      onProgress("assets", "正在拆解角色 / 场景 / 道具，生成三视图与概念图提示词…");
      return assets(script, parsed).then(function (r) {
        pack = r;
        out.assetPack = r;
        (r.warnings || []).forEach(function (w) { out.assetWarnings.push(w); });
        onProgress("assets", "资产包就绪：" +
          ((r.assets && r.assets.characters) || []).length + " 角色 / " +
          ((r.assets && r.assets.scenes) || []).length + " 场景 / " +
          ((r.assets && r.assets.props) || []).length + " 道具");
      }).catch(function (err) {
        out.assetWarnings.push("资产分解失败（" + err.message + "），已退回规则抽取：设定会变空壳");
      });
    }).then(function () {
      onProgress("plan", "AI 正在通读剧本、规划分集…");
      return plan(script, parsed, wanted);
    }).then(function (p) {
      out.episodes = p.episodes || [];
      if (!out.episodes.length) throw new Error("AI 没有给出有效的分集方案");
      out.episodes.forEach(function (e) { e.source = "ai"; });
      onProgress("shots", "共 " + out.episodes.length + " 集，开始逐集拆分镜头…");
      // 串行，避免并发打爆上游限流；逐集回调进度
      var chain = Promise.resolve();
      var groups = [];
      out.episodes.forEach(function (ep, i) {
        chain = chain.then(function () {
          onProgress("shots", "正在生成第 " + ep.no + " / " + out.episodes.length + " 集《" + (ep.title || "") + "》的分镜…");
          return storyboard(script, parsed, ep, config).then(function (r) {
            groups[i] = r.shots || [];
            (r.warnings || []).forEach(function (w) { out.warnings.push(w); });
            var cv = r.coverage || {};
            Object.keys(out.coverage).forEach(function (k) {
              out.coverage[k] += Number(cv[k] || 0);
            });
          }).catch(function (err) {
            out.degraded.push({ no: ep.no, reason: err.message });
            groups[i] = localShotsForEpisode(parsed, config, ep, localAll).map(function (s) {
              return {
                sceneNo: s.sceneNo, kind: s.kind, visual: s.visual, size: s.size,
                duration: s.duration, dialogue: s.dialogue, speaker: s.speaker,
                notes: s.notes, ai: false, detail: E.normalizeDetail(s.detail)
              };
            });
          });
        });
      });
      return chain.then(function () { return groups; });
    }).then(function (groups) {
      onProgress("verify", "正在逐条核对台词 / 动作覆盖…");
      out.shots = toShots(groups, out.episodes, parsed, config);
      if (out.degraded.length === out.episodes.length) out.source = "local";
      if (!pack || !out.shots.length) return out;
      // 工作流 stage 3：资产包 + 分镜表 → 每镜起始帧提示词（本地模板，秒回）。
      // 失败只降级这一层，分镜本身照常可用。
      onProgress("frames", "正在按资产包生成 " + out.shots.length + " 个镜头的起始帧提示词…");
      return frames(out.shots, pack, config.aspect).then(function (r) {
        out.frames = r.frames || [];
        out.frameStats = r.stats || null;
        return out;
      }).catch(function (err) {
        out.assetWarnings.push("起始帧提示词生成失败：" + err.message);
        return out;
      });
    }).catch(function (err) {
      // 整体失败（没 Key / 分集失败 / 网络不通）：完全走本地，保证一定有结果
      out.source = "local"; out.planSource = "local";
      out.fallbackReason = err.message || "AI 不可用";
      out.episodes = E.localEpisodes(parsed, wanted).map(function (e) {
        return Object.assign(e, { source: "local" });
      });
      out.shots = E.renumberShots(E.assignEpisodes(localAll, out.episodes), out.episodes);
      return out;
    });
  }

  /* ------------------ 拆解任务（后端执行 + 事件流推进度） ------------------
     后端跑完整流程，每个阶段开始 / 结束都写一条事件；前端只订阅与渲染。
     EventSource 连续失败两次就切轮询 —— 进度不能停在某个百分比上装死。 */
  function startParseTask(body) { return post("parse/start", body, 20000); }

  function parseTaskState(id) {
    return fetch(url("parse/state?id=" + encodeURIComponent(id)), { cache: "no-store" })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error((j && j.detail) || ("任务查询失败 " + r.status));
          return j;
        });
      });
  }

  function parseTaskLatest() {
    return fetch(url("parse/latest"), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .catch(function () { return { task: null }; });
  }

  function cancelParseTask(id) { return post("parse/cancel", { id: id }, 10000); }

  /**
   * 订阅任务事件；done 时 resolve 整份快照，failed / cancelled 时 reject（err.snapshot 带现场）。
   * onEvent(ev, meta) 逐条回调，meta.live = "sse" | "poll"。
   */
  function watchParseTask(id, onEvent) {
    return new Promise(function (resolve, reject) {
      var es = null, timer = null, done = false, lastSeq = 0, errs = 0, live = "sse";

      function stop() {
        if (es) { try { es.close(); } catch (e) { /* 已关闭 */ } es = null; }
        if (timer) { clearTimeout(timer); timer = null; }
      }
      function fire(ev) {
        lastSeq = Math.max(lastSeq, Number(ev.seq) || 0);
        try { if (onEvent) onEvent(ev, { live: live }); } catch (e) { /* 渲染出错不影响任务本身 */ }
      }
      function finish() {
        if (done) return;
        done = true; stop();
        parseTaskState(id).then(resolve).catch(function () { resolve({ id: id, status: "done" }); });
      }
      function abort(err) {
        if (done) return;
        done = true; stop();
        parseTaskState(id).then(function (s) {
          err.snapshot = s; reject(err);
        }).catch(function () { reject(err); });
      }
      function handle(ev) {
        if (!ev) return;
        fire(ev);
        if (ev.type === "done") finish();
        else if (ev.type === "error") abort(new Error(ev.detail || "拆解失败"));
      }
      function poll() {
        if (done) return;
        live = "poll";
        var tick = function () {
          if (done) return;
          parseTaskState(id).then(function (s) {
            (s.events || []).forEach(function (e) { if ((e.seq || 0) > lastSeq) handle(e); });
            if (done) return;
            if (s.ended) {
              if (s.status === "done") finish();
              else abort(new Error(((s.errors || [])[0] || {}).message || "拆解失败"));
              return;
            }
            timer = setTimeout(tick, 900);
          }).catch(function () { timer = setTimeout(tick, 2000); });
        };
        tick();
      }

      try {
        es = new EventSource(url("parse/events?id=" + encodeURIComponent(id) + "&since=" + lastSeq));
        es.onopen = function () { errs = 0; live = "sse"; };
        es.onmessage = function (m) {
          var ev = null;
          try { ev = JSON.parse(m.data); } catch (e) { return; }
          handle(ev);
        };
        es.onerror = function () {
          if (done) return;
          errs += 1;
          if (errs >= 2) {                    // 浏览器自动重连也不通，改轮询把进度接上
            if (es) { try { es.close(); } catch (e) { /* ignore */ } es = null; }
            poll();
          }
        };
      } catch (e) { poll(); }
    });
  }

export const AIStudio = {
  setBase: setBase, checkConfig: checkConfig, plan: plan,
  llmProviders: llmProviders, llmSave: llmSave, llmActivate: llmActivate,
  llmRemove: llmRemove, llmTest: llmTest,
  storyboard: storyboard, toShots: toShots, run: run,
  assets: assets, frames: frames, exportZip: exportZip,
  fillAsset: fillAsset, comfyStatus: comfyStatus,
  comfyGenerate: comfyGenerate, comfyJob: comfyJob, comfyPrompt: comfyPrompt,
  uploadProjectRef: uploadProjectRef,
  adaptNovel: adaptNovel, isNovelScript: isNovelScript,
  localEpisodes: E.localEpisodes,
  startParseTask: startParseTask, watchParseTask: watchParseTask,
  parseTaskState: parseTaskState, parseTaskLatest: parseTaskLatest,
  cancelParseTask: cancelParseTask,
  localShotsForEpisode: localShotsForEpisode
};

export default AIStudio;
