/* =========================================================================
 * ShortPlay Studio · 剧本解析 / 体检 / 分镜编排引擎
 * 纯函数、零依赖、确定性：同样的剧本 + 同样的配置永远得到同样的分镜。
 * ESM：浏览器与 Node 共用同一份纯函数逻辑（生成示例结果复用）。
 * ========================================================================= */

  /* ----------------------------- 默认配置 ----------------------------- */
  var DEFAULT_CONFIG = {
    pacing: "standard",      // standard 标准 | compact 紧凑 | cinematic 电影感
    shotSize: "auto",        // auto 自动 | dialogue 对白优先 | wide 全景优先
    defaultDuration: 4,      // 单镜基准时长（秒）
    establishing: true,      // 每场建立镜头
    closing: true,           // 每场收束镜头
    cameraNotes: true,       // 生成运镜 / 声音备注
    aspect: "16:9",
    videoQuality: "standard", // 出片端画质档位：fast / standard / high（只影响导出与宽高）
    dialoguePerShot: 1
  };

  /* --------------------------- AI 分镜描述卡 --------------------------- */
  var DETAIL_FIELDS = ["subject", "action", "composition", "sizeReason", "camera",
                       "light", "mood", "sound", "transition"];
  var DETAIL_LABELS = {
    subject: "画面主体", action: "动作 / 变化", composition: "构图与机位", sizeReason: "景别依据",
    camera: "运镜", light: "光线与色温", mood: "情绪与表演", sound: "声音", transition: "剪辑衔接",
    lens: "焦距景深", cameraPosition: "机位摆位", eyeline: "视线落点", focus: "焦点", stability: "稳定性"
  };
  // 构图量化字段（学自 shuohao-skills）：lens / cameraPosition / composition / eyeline / focus / stability
  var SHOT_CRAFT = ["lens", "cameraPosition", "eyeline", "focus", "stability"];
  function normalizeDetail(d) {
    var src = d && typeof d === "object" ? d : {};
    var out = {};
    DETAIL_FIELDS.concat(SHOT_CRAFT).forEach(function (k) { out[k] = trim(src[k] == null ? "" : src[k]); });
    return out;
  }
  function detailParts(d) {
    var obj = normalizeDetail(d);
    return DETAIL_FIELDS.concat(SHOT_CRAFT).map(function (k) { return obj[k] ? DETAIL_LABELS[k] + "：" + obj[k] : ""; })
      .filter(Boolean);
  }
  function detailText(d) { return detailParts(d).join(" ｜ "); }

  var SIZES = ["远景", "全景", "中景", "近景", "特写"];
  var CAMERA = ["固定机位", "缓慢推进", "轻微手持", "横移跟拍", "缓慢拉远", "过肩镜头"];
  var SOUND = ["", " · 环境音：雨声", " · 环境音：室内底噪", " · 留白，只留对白"];

  var INT_EXT = { "INT": "内景", "INT.": "内景", "内": "内景", "内景": "内景", "EXT": "外景", "EXT.": "外景", "外": "外景", "外景": "外景" };
  var TIME_WORDS = ["清晨", "早晨", "上午", "中午", "午后", "下午", "黄昏", "傍晚", "日", "白天", "夜", "深夜", "凌晨", "晚上", "稍后", "连续", "次日", "同一时间", "雨后", "清晨"];
  var NON_SPEAKERS = ["地点", "时间", "场景", "备注", "字幕", "镜头", "提示", "说明", "内外景", "角色", "人物", "动作", "转场"];
  // 拆解阶段「原文没写」时的内部兜底值：既不能当成地点/时间，也不该出现在界面上
  var PLACEHOLDER_WORDS = ["未注明", "未指定", "未标注", "未确定", "未写明", "未提及", "未填写", "未知", "待定", "不详"];
  function isPlaceholder(v) { return PLACEHOLDER_WORDS.indexOf(trim(v)) >= 0; }

  /* ------------------------------ 小工具 ------------------------------ */
  function trim(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }
  function clean(s) { return trim(s).replace(/^[△▲·•\-\*]+\s*/, "").replace(/^[（(]|[）)]$/g, "").trim(); }
  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }
  function hash(str) { var h = 2166136261; for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0); }
  function pick(arr, seed) { return arr[hash(String(seed)) % arr.length]; }
  function pad3(n) { return String(n).padStart(3, "0"); }

  var CN_NUM = { "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10 };
  function toNum(s) {
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    if (CN_NUM[s]) return CN_NUM[s];
    if (/^十[一二三四五六七八九]$/.test(s)) return 10 + CN_NUM[s[1]];
    var m = /^\s*(\d+)\s*$/.exec(s);
    return m ? parseInt(m[1], 10) : NaN;
  }

  /* --------------------------- 剧本文本解析 --------------------------- */
  /**
   * 支持的写法（可混用）：
   *   《片名》                      标题
   *   第1场 外景 · 便利店门口 · 夜   场次（也可写 场景1 / 1. INT. 咖啡馆 - 日 / 【场景：...】）
   *   【地点：便利店】【时间：夜】【内外景：内景】   显式补全标记
   *   【角色别名：明=小明】         角色合并标记（作用于全剧）
   *   林晚：又是一整夜的雨。        对白
   *   林晚（把咖啡推回去）：你不是…  带动作提示的对白
   *   △ 陈默的手在发抖             动作
   *   （镜头缓缓拉远，…）           整行括号动作
   *   雨下得很急，霓虹招牌…        无冒号的叙述也视为动作
   */
  function parseScript(text) {
    var raw = String(text || "").replace(/\r\n?/g, "\n");
    var lines = raw.split("\n");
    var result = {
      title: "", scenes: [], characters: [], locations: [],
      stats: { scenes: 0, characters: 0, lines: 0, actions: 0, words: raw.replace(/\s/g, "").length },
      aliases: {}
    };
    var current = null;
    var seq = 0;

    function newScene(no, rawHead) {
      seq += 1;
      var s = {
        no: isNaN(no) ? seq : no, order: seq, raw: trim(rawHead) || ("第" + seq + "场"),
        intExt: "", location: "", time: "", headLine: 0,
        actions: [], lines: [], characters: []
      };
      result.scenes.push(s);
      return s;
    }

    for (var i = 0; i < lines.length; i++) {
      var line = trim(lines[i]);
      if (!line) continue;

      // 片名
      if (!result.title && /^[《【#]/.test(line) && i <= 2) {
        var t = /^《([^》]+)》/.exec(line) || /^#+\s*(.+)$/.exec(line);
        if (t) { result.title = trim(t[1]); continue; }
      }

      // 显式补全标记
      var mark = /^[\[【]\s*(地点|时间|内外景|场景名称)\s*[：:]\s*([^\]】]+)[\]】]\s*$/.exec(line);
      if (mark) {
        if (!current) current = newScene(1, "");
        var v = trim(mark[2]);
        if (mark[1] === "地点" || mark[1] === "场景名称") current.location = v;
        else if (mark[1] === "时间") current.time = v;
        else current.intExt = INT_EXT[v.toUpperCase()] || INT_EXT[v] || v;
        continue;
      }
      var alias = /^[\[【]\s*角色别名\s*[：:]\s*([^\]】]+)[\]】]\s*$/.exec(line);
      if (alias) {
        trim(alias[1]).split(/[;,，；]/).forEach(function (pair) {
          var kv = pair.split(/[=＝→>]/);
          if (kv.length === 2 && trim(kv[0]) && trim(kv[1])) result.aliases[trim(kv[0])] = trim(kv[1]);
        });
        continue;
      }

      // 场次行
      var head = matchSceneHead(line);
      if (head) {
        current = newScene(head.no, line);
        current.headLine = i + 1;
        current.intExt = head.intExt || "";
        current.location = head.location || "";
        current.time = head.time || "";
        parseHeadParts(current, line);
        continue;
      }

      // 没有场次头 → 自动建立第 1 场（纯文本剧本也能用）
      if (!current) { current = newScene(1, ""); current.headLine = 0; }

      // 独立一行的地点/时间补充（无括号写法）
      var kv = /^(地点|时间|内外景|场景)\s*[：:]\s*(.+)$/.exec(line);
      if (kv) {
        var val = trim(kv[2]);
        if (kv[1] === "地点" || kv[1] === "场景") current.location = val;
        else if (kv[1] === "时间") current.time = val;
        else current.intExt = INT_EXT[val.toUpperCase()] || INT_EXT[val] || val;
        continue;
      }

      // 对白：角色（可选舞台提示）：内容
      var dlg = /^([^：:\s（）()【】\[\]]{1,12})\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(.+)$/.exec(line);
      if (dlg && NON_SPEAKERS.indexOf(dlg[1]) < 0 && !/^(第|场|INT|EXT)/i.test(dlg[1])) {
        current.lines.push({ speaker: trim(dlg[1]), stage: trim(dlg[2] || ""), text: trim(dlg[3]), lineNo: i + 1 });
        continue;
      }

      // 其余都算动作 / 画面描述
      current.actions.push({ text: clean(line), lineNo: i + 1, marked: /^[△▲]/.test(line) });
    }

    // 归一化角色别名 + 汇总
    var charSet = {};
    var prevExt = "";
    result.scenes.forEach(function (s) {
      s.lines.forEach(function (l) { l.speaker = result.aliases[l.speaker] || l.speaker; });
      var set = {};
      s.lines.forEach(function (l) { set[l.speaker] = 1; });
      s.characters = Object.keys(set);
      s.characters.forEach(function (c) { charSet[c] = 1; });
      // 占位词一律当「没写」，不占字段
      if (isPlaceholder(s.location)) s.location = "";
      if (isPlaceholder(s.intExt)) s.intExt = "";
      if (isPlaceholder(s.time)) s.time = "";
      // 内外景是「同一布景连续场次」的稳定属性，可沿用上一场；
      // 地点与时间不继承 —— 切场就可能换景，猜错比留空更误导。
      if (!s.intExt && prevExt) s.intExt = prevExt;
      if (!s.location) s.location = "";
      if (!s.intExt) s.intExt = "";
      if (!s.time) s.time = "";
      prevExt = s.intExt;
    });
    result.characters = Object.keys(charSet);
    var locSet = {};
    result.scenes.forEach(function (s) { if (s.location) locSet[s.location] = 1; });
    result.locations = Object.keys(locSet);
    result.stats.scenes = result.scenes.length;
    result.stats.characters = result.characters.length;
    result.stats.lines = result.scenes.reduce(function (a, s) { return a + s.lines.length; }, 0);
    result.stats.actions = result.scenes.reduce(function (a, s) { return a + s.actions.length; }, 0);
    if (!result.title) result.title = inferTitle(raw) || "未命名短剧";
    return result;
  }

  function inferTitle(raw) {
    var m = /《([^》]+)》/.exec(raw) || /^#+\s*(.+)$/m.exec(raw);
    return m ? trim(m[1]) : "";
  }

  function matchSceneHead(line) {
    var m;
    // 第1场 / 第 一 场 / 场次3 / 场景 2
    if ((m = /^(?:第\s*([0-9一二三四五六七八九十]+)\s*场|场次\s*([0-9]+)|场景\s*([0-9]+)|SCENE\s*([0-9]+))/i.exec(line))) {
      var n = toNum(m[1] || m[2] || m[3] || m[4]);
      return { no: n, intExt: "", location: "", time: "" };
    }
    // 1. INT. 咖啡馆 - 日   /   【场景：内景 · 咖啡馆 · 日】
    if ((m = /^\s*(\d+)[\.、]\s*(INT|EXT|内景|外景)[\.．]?\s*(.+)$/i.exec(line))) {
      return { no: parseInt(m[1], 10), intExt: INT_EXT[m[2].toUpperCase()] || m[2], location: "", time: "" };
    }
    if ((m = /^[\[【]\s*场景\s*[：:]\s*([^\]】]+)[\]】]/.exec(line))) {
      return { no: NaN, intExt: "", location: "", time: "" };
    }
    // 独立以 内景/外景/INT./EXT. 起头
    if ((m = /^(INT\.?|EXT\.?|内景|外景)\s*[·:：\-—\-/]?\s*(.*)$/i.exec(line))) {
      return { no: NaN, intExt: INT_EXT[m[1].toUpperCase()] || m[1], location: "", time: "" };
    }
    return null;
  }

  /** 从场次标题行里拆出「外景 · 便利店门口 · 夜」这样的片段 */
  function parseHeadParts(scene, line) {
    var body = line
      .replace(/^第\s*[0-9一二三四五六七八九十]+\s*场\s*/, "")
      .replace(/^(?:场次|场景|SCENE)\s*\d+\s*/i, "")
      .replace(/^\d+[\.、]\s*(?:INT\.?|EXT\.?|内景|外景)[\.．]?\s*/i, "")
      .replace(/^[\[【]|[】\]]$/g, "");
    var parts = body.split(/[·｜|/\-—–,，、\s]{1,}/).filter(Boolean);
    parts.forEach(function (p) {
      var q = trim(p).replace(/^(地点|时间|内外景)[：:]\s*/, "");
      if (!q || isPlaceholder(q)) return;
      if (INT_EXT[q.toUpperCase()] || INT_EXT[q]) { if (!scene.intExt) scene.intExt = INT_EXT[q.toUpperCase()] || INT_EXT[q]; return; }
      if (TIME_WORDS.indexOf(q) >= 0 || (q.length <= 6 && TIME_WORDS.some(function (w) { return q.indexOf(w) >= 0; }))) {
        if (!scene.time) scene.time = q; return;
      }
      if (!scene.location && q.length <= 20 && !/^第.+场$/.test(q)) scene.location = q;
    });
  }

  /* ------------------- 稿子规范化：类型判定 / 规范度 / 本地补场次 ------------------- */
  var DLG_LINE_RE = /^[^：:\s（）()【】\[\]△▲]{1,12}\s*(?:[（(][^）)]*[）)])?\s*[：:]\s*\S/;

  /**
   * 稿子类型三档 —— 决定「上传的文件」走哪条路：
   *   scene  已带场次头，本地规则直接解析，0 AI 成本
   *   simple 有「角色：台词」但没场次头，本地补场次号即可，0 AI 成本
   *   prose  小说 / 散文 / 公众号文，必须 AI 忠实转写，否则只能拆出 1 场 0 对白
   */
  function classifySource(text) {
    var t = String(text || "");
    var compact = t.replace(/\s/g, "");
    if (!compact) return { kind: "empty", heads: 0, dialogues: 0, chars: 0 };
    var heads = 0, dialogues = 0;
    t.replace(/\r\n?/g, "\n").split("\n").forEach(function (rawLine) {
      var line = trim(rawLine);
      if (!line) return;
      if (matchSceneHead(line)) { heads++; return; }
      if (DLG_LINE_RE.test(line)) dialogues++;
    });
    var kind = heads ? "scene" : (dialogues >= 3 ? "simple" : "prose");
    return { kind: kind, heads: heads, dialogues: dialogues, chars: compact.length };
  }

  /**
   * 规范度：把「离能被 AI 正确拆解还差什么」拆成 5 项可执行检查。
   * 与 diagnose 分工：diagnose 查「内容有没有错」，这里查「格式够不够用」。
   */
  function scriptSpec(text, parsed) {
    var p = parsed || parseScript(String(text || ""));
    var total = p.scenes.length || 0;
    var items = [];
    var hasTitle = !!p.title && p.title !== "未命名短剧";
    items.push({
      key: "title", label: "片名", state: hasTitle ? "ok" : "warn",
      detail: hasTitle ? "《" + p.title + "》" : "没写《片名》，不影响拆解，导出时叫「未命名短剧」"
    });
    var withHead = p.scenes.filter(function (s) { return s.headLine; }).length;
    items.push({
      key: "head", label: "场次头",
      state: !total || !withHead ? "bad" : (withHead === total ? "ok" : "warn"),
      detail: !withHead ? "一场都没标，AI 只能把整篇当 1 场" : withHead + " / " + total + " 场有场次头"
    });
    var full = p.scenes.filter(function (s) { return s.intExt && s.location && s.time; }).length;
    items.push({
      key: "head3", label: "内外景·地点·时间",
      state: total && full === total ? "ok" : (full ? "warn" : "bad"),
      detail: total ? full + " / " + total + " 场写全" : "还没有场次"
    });
    items.push({
      key: "dlg", label: "对白已标说话人", state: p.stats.lines ? "ok" : "bad",
      detail: p.stats.lines
        ? p.stats.lines + " 句对白，" + (p.stats.characters || 0) + " 个角色"
        : "一句对白都没识别到，分镜会退化成空镜"
    });
    var pairs = [];
    (p.characters || []).forEach(function (a, i) {
      (p.characters || []).forEach(function (b, j) {
        if (j <= i || a === b) return;
        if (a.length !== b.length && (a.indexOf(b) >= 0 || b.indexOf(a) >= 0)) pairs.push([a, b]);
      });
    });
    items.push({
      key: "names", label: "角色名一致", state: pairs.length ? "warn" : "ok",
      detail: pairs.length
        ? pairs.slice(0, 3).map(function (x) { return x[0] + " / " + x[1]; }).join("、") + " 像同一个人，可用【角色别名：小明=明】合并"
        : (p.characters || []).length + " 个角色，没有疑似重名"
    });
    var ok = items.filter(function (i) { return i.state === "ok"; }).length;
    return { items: items, ok: ok, score: Math.round(ok / items.length * 100) };
  }

  /**
   * 本地补场次号（只服务 simple 类型，不调 AI、不改一个字）。
   * 按空行切块，单行块并回上一场，再逐块补「第N场」。
   * 只补场号、不编内外景/地点/时间 —— 编错会污染参考图与提示词；
   * 缺的三要素交给第 2 步体检卡一键补，或人工补。
   */
  function normalizeLocal(text) {
    var t = String(text || "").replace(/\r\n?/g, "\n");
    if (!t.trim()) return { script: t, scenes: 0, changed: false, reason: "empty" };
    var lines = t.split("\n");
    if (lines.some(function (l) { return !!matchSceneHead(trim(l)); })) {
      return { script: t, scenes: 0, changed: false, reason: "already" };
    }
    var blocks = [], cur = [];
    lines.forEach(function (l) {
      if (!trim(l)) { if (cur.length) { blocks.push(cur); cur = []; } return; }
      cur.push(l);
    });
    if (cur.length) blocks.push(cur);
    if (!blocks.length) return { script: t, scenes: 0, changed: false, reason: "empty" };
    var merged = [];
    blocks.forEach(function (b) {
      if (b.length <= 1 && merged.length) merged[merged.length - 1].push("", b[0]);
      else merged.push(b.slice());
    });
    var out = [];
    merged.forEach(function (b, i) {
      if (i) out.push("");
      out.push("第" + (i + 1) + "场");
      b.forEach(function (l) { out.push(l); });
    });
    return { script: out.join("\n"), scenes: merged.length, changed: true, reason: "added" };
  }

  /* ------------------------- 信息缺失 / 冲突体检 ------------------------- */
  function diagnose(text, parsed) {
    var issues = [];
    var raw = String(text || "");
    function add(code, level, title, detail, fix) {
      issues.push({ id: code + "_" + issues.length, code: code, level: level, title: title, detail: detail, fix: fix || null });
    }

    if (raw.replace(/\s/g, "").length < 20) {
      add("empty", "error", "剧本内容太少", "还没识别到可用的剧情内容。可以粘贴剧本文字、上传 .txt，或一键载入示例剧本。", null);
      return issues;
    }
    if (!parsed.scenes.length || (parsed.scenes.length === 1 && !parsed.scenes[0].headLine)) {
      add("no-scene", "warn", "没有识别到场次标记", "剧本里没找到「第1场 / 场景1 / INT. 地点 - 日」这类场次标记，已按单场处理。补上场次要按剧情分段会更准。", { type: "auto", label: "按单场处理" });
    }
    // 场号重复
    var seen = {}, dup = [];
    parsed.scenes.forEach(function (s) { if (seen[s.no]) dup.push(s.no); seen[s.no] = 1; });
    if (dup.length) {
      add("dup-scene-no", "error", "场次编号重复", "第 " + dup.join("、") + " 场出现了多次，分镜顺序会混淆。", { type: "auto", label: "自动重排场号" });
    }
    // 缺地点 / 内外景 / 时间
    var noLoc = parsed.scenes.filter(function (s) { return !s.location; });
    if (noLoc.length) {
      add("missing-location", "warn", noLoc.length + " 个场次没写地点", "缺地点的场次：" + noLoc.map(function (s) { return "第" + s.no + "场"; }).join("、") + "。不补也能生成，画面描述会用「未写明地点」。",
        { type: "input", label: "补写地点", placeholder: "例如：便利店门口", sceneNos: noLoc.map(function (s) { return s.no; }) });
    }
    // 场次头的占位词（老版本拆解产物：第1场 未注明 · 乡下爷爷家 · 未注明）
    var PH_RE = "(?:未注明|未指定|未标注|未知|待定|不详)";
    var phHeads = raw.split(/\r?\n/).filter(function (l) {
      var t2 = trim(l);
      if (!matchSceneHead(t2)) return false;
      return new RegExp("第\\s*[0-9０-９一二三四五六七八九十]+\\s*场\\s+" + PH_RE).test(t2) ||
        new RegExp("[·・|｜]\\s*" + PH_RE + "\\s*(?:[·・|｜]|$)").test(t2);
    });
    if (phHeads.length) {
      add("placeholder-head", "warn", phHeads.length + " 个场次头写着「未注明」",
        "「未注明」是拆解时原文没写、系统留的占位词，不是真实内容。它会顶掉真正的地点，让分镜标签退化成「第1场 · 未注明」。一键清掉即可；想更准就回剧本补上内外景与时间，格式例：第1场 内景 · 乡下爷爷家 · 傍晚。",
        { type: "clean-head", label: "清掉占位词" });
    }
    var noIE = parsed.scenes.filter(function (s) { return !s.intExt; });
    if (noIE.length) {
      add("missing-intext", "warn", noIE.length + " 个场次没标内外景", "缺内/外景标注，默认按「内景」生成建立镜头。",
        { type: "auto", label: "统一补为内景", value: "内景" });
    }
    var noTime = parsed.scenes.filter(function (s) { return !s.time; });
    if (noTime.length) {
      add("missing-time", "warn", noTime.length + " 个场次没写时间", "缺时间信息，默认按「日」处理，光线描述会比较笼统。",
        { type: "auto", label: "统一补为日", value: "日" });
    }
    // 空场
    var emptyScenes = parsed.scenes.filter(function (s) { return !s.lines.length && !s.actions.length; });
    if (emptyScenes.length) {
      add("empty-scene", "error", "有场次没有内容", "第 " + emptyScenes.map(function (s) { return s.no; }).join("、") + " 场既没有对白也没有动作，无法拆出分镜。请回到剧本补充。", null);
    }
    // 角色别名疑似冲突
    var cs = parsed.characters, pairs = [];
    for (var i = 0; i < cs.length; i++) for (var j = i + 1; j < cs.length; j++) {
      var a = cs[i], b = cs[j];
      if ((a.length !== b.length) && (a.indexOf(b) >= 0 || b.indexOf(a) >= 0) && Math.min(a.length, b.length) >= 1) pairs.push([a, b]);
    }
    if (pairs.length) {
      add("alias-conflict", "warn", "角色名可能不统一", pairs.map(function (p) { return "「" + p[0] + "」与「" + p[1] + "」"; }).join("、") + " 可能指同一个人，会被算成两个角色。",
        { type: "alias", label: "合并为同一角色", pairs: pairs });
    }
    if (!parsed.stats.lines) {
      add("no-dialogue", "warn", "整部剧没有对白", "识别不到「角色：台词」格式的对白，生成的分镜台词列会是空的。确认剧本是否用了别的写法。", null);
    }
    // 裸台词（引号开头但无角色名）
    var bare = raw.split("\n").filter(function (l) { return /^\s*[「“"][^」”"]{4,}[」”"]\s*$/.test(l); });
    if (bare.length) {
      add("bare-line", "warn", "有台词没写说话人", "检测到 " + bare.length + " 行用引号包住但没有角色名，例如「" + trim(bare[0]).slice(0, 24) + "」。请改成「角色：台词」。", null);
    }
    return issues;
  }

  /** 把体检建议写回剧本文本（文本与界面始终一致，且可被撤销） */
  function applyFix(text, fix, parsed) {
    var lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    var t = fix.type;
    if (t === "auto" && fix.label === "自动重排场号") {
      var n = 0;
      return lines.map(function (l) {
        return l.replace(/^(第\s*)([0-9一二三四五六七八九十]+)(\s*场)/, function (_, a, _b, c) { n += 1; return a + n + c; })
          .replace(/^((?:场次|场景|SCENE)\s*)(\d+)/i, function (_, a) { n += 1; return a + n; });
      }).join("\n");
    }
    if (t === "auto" && fix.label === "按单场处理") {
      return "第1场 内景 · 未写明地点 · 日\n" + String(text || "");
    }
    if (t === "input" && fix.value) {
      var targets = fix.sceneNos || [];
      var idx = [];
      lines.forEach(function (l, i) {
        var h = matchSceneHead(trim(l));
        if (h && (targets.length === 0 || targets.indexOf(isNaN(h.no) ? 0 : h.no) >= 0)) idx.push(i);
      });
      // 没找到场次头就插到开头
      if (!idx.length) idx = [0];
      var out = [], cur = 0;
      for (var k = 0; k < idx.length; k++) {
        var at = idx[k];
        while (cur <= at) { out.push(lines[cur]); cur += 1; }
        out.push("【地点：" + trim(fix.value) + "】");
      }
      while (cur < lines.length) { out.push(lines[cur]); cur += 1; }
      return out.join("\n");
    }
    if (t === "auto" && (fix.value === "内景" || fix.value === "外景")) {
      var out2 = [];
      lines.forEach(function (l) {
        out2.push(l);
        if (matchSceneHead(trim(l)) && !/(内景|外景|INT|EXT)/i.test(l)) out2.push("【内外景：" + fix.value + "】");
      });
      // 纯文本没有场次头时，补在最前面
      if (!lines.some(function (l) { return !!matchSceneHead(trim(l)); })) out2.unshift("第1场 " + fix.value);
      return out2.join("\n");
    }
    if (t === "auto" && fix.value === "日") {
      var out3 = [];
      lines.forEach(function (l) {
        out3.push(l);
        if (matchSceneHead(trim(l)) && !/(清晨|早晨|上午|中午|午后|下午|黄昏|傍晚|夜|凌晨|稍后|连续|次日|日)/.test(l)) {
          out3.push("【时间：" + fix.value + "】");
        }
      });
      return out3.join("\n");
    }
    if (t === "clean-head") {
      return lines.map(function (l) {
        var hm = /^(\s*第\s*[0-9０-９一二三四五六七八九十百零两]+\s*场)\s*(.*)$/.exec(l);
        if (!hm) return l;
        var segs = String(hm[2] || "").split(/[·・|｜]/)
          .map(function (x) { return trim(x); })
          .filter(function (x) { return x && !isPlaceholder(x); });
        return trim(hm[1]) + (segs.length ? " " + segs.join(" · ") : "");
      }).join("\n");
    }
    if (t === "alias" && fix.pairs && fix.pairs.length) {
      var marks = fix.pairs.map(function (p) {
        var shortName = p[0].length <= p[1].length ? p[0] : p[1];
        var longName = p[0].length > p[1].length ? p[0] : p[1];
        return "【角色别名：" + shortName + "=" + longName + "】";
      });
      return String(text || "").replace(/\s*$/, "") + "\n" + marks.join("\n") + "\n";
    }
    return text;
  }

  /* --------------------------- 分镜编排规则 --------------------------- */
  function sceneLabel(s) {
    var loc = isPlaceholder(s.location) ? "" : (s.location || "");
    var tm = isPlaceholder(s.time) ? "" : (s.time || "");
    return "第" + s.no + "场" + (loc ? " · " + loc : "") + (tm ? " · " + tm : "");
  }

  function chooseSize(kind, text, index, config, variant) {
    var t = String(text || "");
    if (config.shotSize === "dialogue") return kind === "establishing" ? "全景" : (index % 2 ? "近景" : "中景");
    if (config.shotSize === "wide") return kind === "dialogue" ? "中景" : (index % 3 === 0 ? "远景" : "全景");
    if (kind === "establishing") return config.pacing === "cinematic" ? "远景" : "全景";
    if (kind === "closing") return "远景";
    if (kind === "dialogue") {
      if (/[?？!！]|\.\.\.|…|为什么|记得|终于|其实/.test(t)) return "特写";
      return ["中景", "近景", "特写", "中景"][(index + variant) % 4];
    }
    if (/镜头.*拉远|航拍|俯拍/.test(t)) return "远景";
    if (/镜头|推近/.test(t)) return "中景";
    var prop = /手在|手指|照片|屏幕|手机|字条|雨滴|水洼|指尖|眼神|表情/.test(t);
    var moving = /走进|走出|跑|搬|推开|坐下|站起|收回|放下|拿起|停在|进来|离开/.test(t);
    if (prop && !moving) return "特写";
    if (moving) return "全景";
    return ["中景", "全景", "近景"][(index + variant) % 3];
  }

  function actionVisual(text, scene) {
    var t = clean(text);
    if (!t) return (scene.location || "场景") + "，画面安静地停留片刻。";
    if (/^镜头/.test(t)) return t;
    return t.replace(/[。；;]$/, "") + "。";
  }

  function dialogueVisual(line, scene, size, variant) {
    var place = scene.location || "场景内";
    var stage = line.stage ? "，" + clean(line.stage) : "";
    var mood = /[?？]|为什么|谁/.test(line.text) ? "带着疑问看向对方" : (/[!！]/.test(line.text) ? "情绪略激动" : "神情克制");
    var bg = size === "特写" ? "背景虚化，只留人物面部与眼神" : (size === "近景" ? "背景轻微虚化" : place + "的环境保留在画面里");
    return line.speaker + stage + "，" + mood + "，开口说出台词。" + bg + "。";
  }

  function notesFor(kind, size, scene, index, config, variant) {
    if (!config.cameraNotes) return "";
    var cam = pick(CAMERA, scene.no + "-" + index + "-" + variant + "-" + kind);
    var env = /雨|雪|风/.test((scene.actions[0] || {}).text || "") ? " · 环境音：雨声" : "";
    if (kind === "establishing") return "建立镜头 · " + cam + env + " · 交代空间关系";
    if (kind === "closing") return "收束镜头 · " + cam + " · 淡出转场";
    if (kind === "dialogue") return size + "正反打 · " + cam + " · 同期声，台词清晰";
    return cam + env + " · 动作一次完整拍完";
  }

  function durFor(text, kind, config) {
    var n = String(text || "").replace(/[\s，。、！？；：「」]/g, "").length;
    var d = config.defaultDuration + Math.round((n - 12) / 10);
    if (kind === "establishing") d = config.defaultDuration + 1;
    if (kind === "closing") d = config.defaultDuration;
    if (config.pacing === "compact") d += 1;
    if (config.pacing === "cinematic") d -= 1;
    return clamp(Math.round(d * 2) / 2, 2, 10);
  }

  function makeShot(o) {
    return {
      id: o.id,
      no: o.no,
      code: pad3(o.no),
      originCode: pad3(o.no),
      sceneNo: o.sceneNo,
      sceneLabel: o.sceneLabel,
      kind: o.kind,
      visual: o.visual,
      size: o.size,
      duration: o.duration,
      dialogue: o.dialogue || "",
      speaker: o.speaker || "",
      notes: o.notes || "",
      edited: {},
      source: o.source || "",
      episode: o.episode || 0,      // 0 = 未分集；>=1 为集号
      ai: !!o.ai,                   // 是否由大模型生成
      detail: normalizeDetail(o.detail),  // AI 分镜描述卡（9 项，可空）
      patched: !!o.patched,         // 服务端因漏项自动补齐的镜头
      charIds: [],                  // 绑定的角色资产（顺序 = 参考图槽位顺序）
      sceneId: "",                  // 绑定的场景资产
      propIds: [],                  // 绑定的道具资产
      assetSig: "",                 // 绑定时的资产签名，用于「资产已改」检测
      locked: false                 // 锁定后批量重生成不覆盖
    };
  }

  /* ------------------------------ 分集 ------------------------------ */
  function pad2(n) { return String(n).padStart(2, "0"); }
  function episodeLabel(ep) {
    if (!ep || !ep.no) return "未分集";
    return "第" + ep.no + "集" + (ep.title ? " · " + ep.title : "");
  }

  /** 离线分集兜底：只按场次边界切，绝不把一场拆到两集。 */
  function localEpisodes(parsed, wanted) {
    var scenes = (parsed && parsed.scenes) || [];
    if (!scenes.length) return [];
    var n = Number(wanted) > 0 ? clamp(Math.round(Number(wanted)), 1, 6)
      : clamp(Math.ceil(scenes.length / 2), 1, 6);
    n = Math.min(n, scenes.length);
    var per = scenes.length / n;
    var eps = [];
    for (var i = 0; i < n; i++) {
      var from = Math.floor(i * per), to = Math.floor((i + 1) * per) - 1;
      if (i === n - 1) to = scenes.length - 1;
      if (to < from) continue;
      var group = scenes.slice(from, to + 1);
      var first = group[0], last = group[group.length - 1];
      var lastLine = last.lines.length ? last.lines[last.lines.length - 1] : null;
      var firstAction = first.actions.length ? clean(first.actions[0].text) : "";
      eps.push({
        no: eps.length + 1,
        title: (first.location || firstAction || "开场").slice(0, 12),
        synopsis: (group.map(function (s) { return s.location; }).filter(Boolean).join(" → ") || firstAction).slice(0, 90),
        sceneFrom: first.no, sceneTo: last.no,
        hook: lastLine ? (lastLine.speaker + "：" + lastLine.text).slice(0, 90) : firstAction.slice(0, 90),
        source: "local"
      });
    }
    return eps;
  }

  /** 取某一集对应的剧本文字片段（按解析器记录的行号，含场次标题行）。 */
  function scriptSlice(text, parsed, ep) {
    var lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    var scenes = ((parsed && parsed.scenes) || []).filter(function (s) {
      return s.no >= ep.sceneFrom && s.no <= ep.sceneTo;
    });
    if (!scenes.length) return String(text || "");
    var lo = Infinity, hi = 0;
    scenes.forEach(function (s) {
      if (s.headLine) { lo = Math.min(lo, s.headLine); hi = Math.max(hi, s.headLine); }
      (s.actions || []).concat(s.lines || []).forEach(function (x) {
        if (x.lineNo) { lo = Math.min(lo, x.lineNo); hi = Math.max(hi, x.lineNo); }
      });
    });
    if (!isFinite(lo)) return String(text || "");
    return lines.slice(lo - 1, hi).join("\n");
  }

  /** 场次编号 → 集号（场次重复时取第一处）。 */
  function episodeOf(episodes, sceneNo) {
    var hit = 0;
    (episodes || []).forEach(function (ep) {
      if (!hit && sceneNo >= ep.sceneFrom && sceneNo <= ep.sceneTo) hit = ep.no;
    });
    return hit;
  }
  function assignEpisodes(shots, episodes) {
    return (shots || []).map(function (s) {
      return Object.assign({}, s, { episode: episodeOf(episodes, s.sceneNo) });
    });
  }

  /** 有分集时镜号按集内连号 E01-001；无分集时保持 001 全局连号。 */
  function renumberShots(shots, episodes) {
    var counter = {};
    return (shots || []).map(function (s, i) {
      var ep = episodes && episodes.length ? (s.episode || 0) : 0;
      counter[ep] = (counter[ep] || 0) + 1;
      return Object.assign({}, s, {
        no: i + 1,
        code: ep ? "E" + pad2(ep) + "-" + pad3(counter[ep]) : pad3(i + 1)
      });
    });
  }

  /** 按剧情顺序批量生成全部分镜 */
  function buildStoryboard(parsed, config, variant) {
    var cfg = Object.assign({}, DEFAULT_CONFIG, config || {});
    var v = variant || 0;
    var shots = [];
    var no = 0;
    function push(o) { no += 1; o.no = no; shots.push(makeShot(o)); }

    parsed.scenes.forEach(function (s) {
      var label = sceneLabel(s);
      var firstAction = s.actions.length ? clean(s.actions[0].text) : "";
      var idx = 0;

      // 1) 建立镜头
      if (cfg.establishing) {
        var w = (s.intExt ? s.intExt + "，" : "") + (s.location || "未写明地点") + (s.time ? "，" + s.time : "") + "。" +
          (firstAction ? firstAction.replace(/[。；]$/, "") + "。" : "画面缓缓展开。");
        push({
          id: "s" + s.order + "_est", sceneNo: s.no, sceneLabel: label, kind: "establishing",
          visual: w, size: chooseSize("establishing", firstAction, idx, cfg, v),
          duration: durFor("", "establishing", cfg),
          notes: notesFor("establishing", "全景", s, idx, cfg, v), source: firstAction
        });
        idx += 1;
      }

      // 2) 动作镜头（跳过已用于建立镜头的首条叙述，避免重复）
      s.actions.forEach(function (a, ai) {
        if (cfg.establishing && ai === 0 && !a.marked) return;
        var t = clean(a.text);
        if (!t) return;
        if (cfg.pacing === "compact" && ai > 0 && !a.marked && t.length < 14) return;
        push({
          id: "s" + s.order + "_a" + ai, sceneNo: s.no, sceneLabel: label, kind: "action",
          visual: actionVisual(a.text, s), size: chooseSize("action", t, idx, cfg, v),
          duration: durFor(t, "action", cfg), notes: notesFor("action", "", s, idx, cfg, v), source: t
        });
        idx += 1;
      });

      // 3) 对白镜头
      var pending = [];
      function flushDialogue() {
        if (!pending.length) return;
        var text = pending.map(function (l) { return l.text; }).join(" ");
        var speaker = pending[0].speaker;
        var last = pending[pending.length - 1];
        var size = chooseSize("dialogue", text, idx, cfg, v);
        push({
          id: "s" + s.order + "_d" + pending[0].lineNo, sceneNo: s.no, sceneLabel: label, kind: "dialogue",
          visual: dialogueVisual({ speaker: speaker, stage: last.stage, text: text }, s, size, v),
          size: size, duration: durFor(text, "dialogue", cfg),
          dialogue: pending.map(function (l) { return l.speaker + (l.stage ? "（" + l.stage + "）" : "") + "：" + l.text; }).join(" / "),
          speaker: speaker, notes: notesFor("dialogue", size, s, idx, cfg, v), source: text
        });
        idx += 1;
        pending = [];
      }
      s.lines.forEach(function (l, li) {
        if (cfg.pacing === "compact") {
          if (pending.length && (pending[pending.length - 1].speaker !== l.speaker || pending.length >= 2)) flushDialogue();
          pending.push(l);
        } else {
          flushDialogue();
          pending.push(l);
          flushDialogue();
        }
        // 电影感：不同角色对话之间插一个反应特写
        if (cfg.pacing === "cinematic" && s.lines[li + 1] && s.lines[li + 1].speaker !== l.speaker) {
          flushDialogue();
          push({
            id: "s" + s.order + "_r" + li, sceneNo: s.no, sceneLabel: label, kind: "action",
            visual: l.speaker + "话音落下，" + s.lines[li + 1].speaker + "沉默地看着对方，没有立刻接话。",
            size: "特写", duration: 3, notes: "反应镜头 · 固定机位 · 留白一拍", source: "reaction"
          });
          idx += 1;
        }
      });
      flushDialogue();

      // 4) 收束镜头（若剧本自己已写了拉远镜头则不重复）
      var selfClosing = s.actions.some(function (a) { return /拉远|淡出|镜头缓缓/.test(a.text); });
      if (cfg.closing && shots.length >= 2 && !selfClosing && s.order < parsed.scenes.length) {
        push({
          id: "s" + s.order + "_end", sceneNo: s.no, sceneLabel: label, kind: "closing",
          visual: "镜头缓缓拉远，" + (s.location || "场景") + "的光线与" + (s.time || "此刻") + "的氛围收进画面，留出转场余韵。",
          size: "远景", duration: durFor("", "closing", cfg),
          notes: notesFor("closing", "远景", s, idx, cfg, v), source: "closing"
        });
      }
    });
    return shots;
  }

  /** 批量重生成：只重算画面/景别/时长/备注，台词保持；手动改过的字段默认保留 */
  function regenerateShots(shots, ids, parsed, config, variant, overwriteEdited) {
    var cfg = Object.assign({}, DEFAULT_CONFIG, config || {});
    var idSet = {}; (ids || []).forEach(function (i) { idSet[i] = 1; });
    var v = (variant || 0) + 1;
    return shots.map(function (sh, index) {
      if (!idSet[sh.id]) return sh;
      if (sh.locked) return sh;   // 锁定镜头不参与批量重生成（借鉴 lumenx 的 pinned/locked）
      var size = chooseSize(sh.kind, sh.source || sh.visual, index, cfg, v);
      var dur = durFor(sh.source || sh.visual, sh.kind, cfg);
      var cam = pick(CAMERA, sh.id + "-" + v);
      var notes = cfg.cameraNotes
        ? (sh.kind === "dialogue" ? size + "正反打 · " + cam + " · 同期声" : cam + " · " + (sh.kind === "closing" ? "淡出转场" : "动作完整"))
        : "";
      var visual = sh.visual;
      if (sh.kind === "action" && sh.source && sh.source !== "reaction" && sh.source !== "closing") {
        visual = actionVisual(sh.source, { location: "" });
      } else if (sh.kind === "dialogue" && sh.source) {
        visual = dialogueVisual({ speaker: sh.speaker || "人物", stage: "", text: sh.source }, { location: "" }, size, v);
      }
      var keep = sh.edited || {};
      var allow = !!overwriteEdited;
      function field(name, value) { return (!allow && keep[name]) ? sh[name] : value; }
      return Object.assign({}, sh, {
        visual: field("visual", visual), size: field("size", size),
        duration: field("duration", dur), notes: field("notes", notes),
        variant: v
      });
    });
  }

  /* --------------------------- 资产层 ---------------------------
   * 思路来自 lumenx 的资产池：角色/场景/道具做成「有实体」的资产，
   * 分镜只存 id，导出时才把资产外观编译进提示词 —— 改一次角色外观，全部镜头同步。
   * 这里先做单项目一层（不做 Series/Global 多级），但保留 source 标记以便以后扩展。
   */
  var ASSET_KIND_LABEL = { character: "角色", scene: "场景", prop: "道具" };
  var AGE_RE = /\d{1,3}\s*岁|未成年|少年|少女|青年|中年|老年|孩童|儿童/;
  var WEAR_RE = /穿|外套|衬衫|裙|西装|制服|风衣|围裙|卫衣|夹克|毛衣|睡衣|雨衣|工装|马甲|背心|短袖|长袍/;
  var ASSET_FIELDS = {
    character: ["appearance", "wardrobe", "persona"],
    scene: ["appearance"],
    prop: ["appearance"]
  };

  function assetId(kind, key) {
    var pre = { character: "c:", scene: "sc:", prop: "p:" }[kind] || "a:";
    return pre + trim(key).replace(/[|]/g, "-");
  }

  /** 从剧本里的 `林晚（27岁，便利店店员）` 抓外观线索，不用用户额外填。 */
  function appearanceHint(name, scenes) {
    if (!name) return "";
    var re = new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*[（(]([^）)]{2,40})[）)]");
    for (var i = 0; i < scenes.length; i++) {
      var pool = (scenes[i].actions || []).concat(scenes[i].lines || []);
      for (var j = 0; j < pool.length; j++) {
        var m = re.exec(pool[j].text || "");
        if (m) return m[1];
      }
    }
    return "";
  }
  /** `27岁，便利店店员` → { age, role }；`穿深蓝制服` → { wardrobe } */
  function parseHint(hint) {
    var out = { age: "", role: "", wardrobe: "", appearance: "" };
    if (!hint) return out;
    var rest = [];
    String(hint).split(/[，,、；;]/).map(trim).filter(Boolean).forEach(function (seg) {
      if (!out.age && AGE_RE.test(seg) && seg.length <= 10) { out.age = seg; return; }
      if (!out.wardrobe && WEAR_RE.test(seg)) { out.wardrobe = seg; return; }
      rest.push(seg);
    });
    out.role = rest.shift() || "";
    out.appearance = rest.join("，");
    return out;
  }

  /**
   * 旧资产的认领索引。
   * 资产重建有两条路径（剧本重解析 buildAssets / 资产包合并 applyAssetPack），
   * 以前各写了一份查找规则，规则一分叉就出现「一处认得回、另一处认不回」——
   * 参考图刷新后消失的 bug 就出在这儿。现在索引和认领顺序都只有这一份：
   * id → 内外景+时间+名字 → 场次号 → 名字。
   * 场景 id 有两套写法（规则层 sc:外景-老宅-日、资产包层 sc:老宅|外景|日），
   * 所以不能只看 id；而 AI 又常把名字改一个字，所以名字只能作为最后的兜底。
   */
  function prevIndex(prev) {
    var ix = {
      charById: {}, charByName: {}, sceneById: {}, sceneByName: {},
      sceneByKey: {}, sceneByNo: {}, propByName: {}, used: {}
    };
    ((prev && prev.characters) || []).forEach(function (a) {
      if (!a) return;
      if (a.id && !ix.charById[a.id]) ix.charById[a.id] = a;
      if (a.name && !ix.charByName[a.name]) ix.charByName[a.name] = a;
    });
    ((prev && prev.scenes) || []).forEach(function (a) {
      if (!a) return;
      if (a.id && !ix.sceneById[a.id]) ix.sceneById[a.id] = a;
      if (a.name && !ix.sceneByName[a.name]) ix.sceneByName[a.name] = a;
      var k = sceneKey(a.intExt, a.time, a.name);
      if (!ix.sceneByKey[k]) ix.sceneByKey[k] = a;
      (a.sceneNos || []).forEach(function (n) {
        if (ix.sceneByNo[n] === undefined) ix.sceneByNo[n] = a;
      });
    });
    ((prev && prev.props) || []).forEach(function (a) {
      if (a && a.name && !ix.propByName[a.name]) ix.propByName[a.name] = a;
    });
    return ix;
  }
  function sceneKey(intExt, time, name) {
    return [intExt || "", time || "", name || ""].join("|");
  }
  /** 一条旧资产最多被认领一次：否则「老宅·日」「老宅·夜」两场会抢到同一张参考图。 */
  function claimScene(ix, cand) {
    var tries = [
      ix.sceneById[cand.id],
      ix.sceneByKey[sceneKey(cand.intExt, cand.time, cand.name)],
      ix.sceneByNo[cand.no],
      ix.sceneByName[cand.name]
    ];
    for (var i = 0; i < tries.length; i++) {
      var a = tries[i];
      if (!a || ix.used[a.id]) continue;
      ix.used[a.id] = 1;
      return a;
    }
    return null;
  }
  /**
   * 重建只负责「按剧本补骨架」，不负责删东西。
   * 带过参考图 / 手改字段 / 锁定 / 提示词的资产一律保留，否则「奶奶」这种
   * 只在台词里被提到、剧本没给她单独场次的角色，一刷新就被静默清掉。
   */
  function hasAuthored(a) {
    return !!(a && (a.refImage || (a.genImages || []).length || a.locked ||
      (a.touched && Object.keys(a.touched).length) ||
      a.keyword || a.keywordEn || a.sceneEn ||
      (a.prompts && Object.keys(a.prompts).length) ||
      (a.anchors && Object.keys(a.anchors).length)));
  }
  function claimChar(ix, name, id) {
    var a = ix.charById[id] || ix.charByName[name];
    if (!a || ix.used[a.id]) return null;
    ix.used[a.id] = 1;
    return a;
  }

  /** 剧本 → 资产清单。用户改过的字段（外观/服装/参考图/锁定）在重新解析时保留。 */
  function buildAssets(parsed, prev) {
    var scenes = (parsed && parsed.scenes) || [];
    var ix = prevIndex(prev);

    var lineCount = {};
    scenes.forEach(function (s) {
      (s.lines || []).forEach(function (l) {
        if (l.speaker) lineCount[l.speaker] = (lineCount[l.speaker] || 0) + 1;
      });
    });
    var maxLines = 1;
    Object.keys(lineCount).forEach(function (k) { if (lineCount[k] > maxLines) maxLines = lineCount[k]; });

    // 只在动作描述里出现、一句台词都没有的角色（群众/反派）也要能绑定，
    // 否则提示词里不会带他的外观。用「句读 + 人名 + 人类动作动词」保守抽取，宁缺毋滥。
    var CAST_VERBS = "推门|走进|走出|抬头|低头|转身|回头|看向|盯着|打量|站起|坐下|伸手|握紧|拿起|放下|靠在|冲出|跑进|跪下|愣住|皱眉|点头|摇头|开口|轻声|沉声|抬眼|垂眼";
    var STOP_NAMES = ["然后", "忽然", "突然", "这时", "此刻", "接着", "随即", "于是", "两人", "众人", "所有", "有人", "没人", "自己", "对方", "镜头", "画面", "他们", "她们", "我们", "你们"];
    // 人名不会以代词/副词/虚词开头，也不会含时态助词
    var NAME_BAD_HEAD = "他她它你我您这那哪就还也都没不又便才正已很太更要会能可只刚却竟然依旧仍然";
    var NAME_BAD_BODY = "的了着过们";
    function plausibleName(n) {
      if (!n || n.length < 2 || n.length > 3) return false;
      if (STOP_NAMES.indexOf(n) >= 0) return false;
      if (NAME_BAD_HEAD.indexOf(n[0]) >= 0) return false;
      for (var i = 0; i < n.length; i++) if (NAME_BAD_BODY.indexOf(n[i]) >= 0) return false;
      return true;
    }
    function inferredCast() {
      var known = {};
      ((parsed && parsed.characters) || []).forEach(function (n) { known[n] = 1; });
      var out = [];
      var re = new RegExp("(?:^|[，。！？；：、\\s])([\\u4e00-\\u9fa5]{2,3})(?=" + CAST_VERBS + ")", "g");
      scenes.forEach(function (s) {
        (s.actions || []).forEach(function (a) {
          var t = String(a.text || ""), m;
          while ((m = re.exec(t))) {
            var name = m[1];
            if (known[name] || out.indexOf(name) >= 0) continue;
            if (!plausibleName(name)) continue;
            out.push(name);
          }
        });
      });
      return out;
    }
    var castNames = ((parsed && parsed.characters) || []).slice();
    inferredCast().forEach(function (n) { if (castNames.indexOf(n) < 0) castNames.push(n); });

    var characters = castNames.map(function (name) {
      var id = assetId("character", name);
      var p = claimChar(ix, name, id);
      var hint = parseHint(appearanceHint(name, scenes));
      var t = (p && p.touched) || {};
      var frozen = !!(p && p.locked);
      // 用户手改过的字段优先于剧本推断；整条锁定则一律不动
      function keep(field, hintVal, prevVal) {
        if (frozen || t[field]) return prevVal || "";
        return hintVal || prevVal || "";
      }
      var inScenes = [];
      scenes.forEach(function (s) { if ((s.characters || []).indexOf(name) >= 0) inScenes.push(s.no); });
      return {
        id: id, kind: "character", name: name,
        aliases: (p && p.aliases) || [],
        age: keep("age", hint.age, p && p.age),
        role: keep("role", hint.role, p && p.role),
        wardrobe: keep("wardrobe", hint.wardrobe, p && p.wardrobe),
        appearance: keep("appearance", hint.appearance, p && p.appearance),
        persona: (p && p.persona) || "",
        touched: t,
        weight: clamp(1 + Math.round(((lineCount[name] || 0) / maxLines) * 4), 1, 5),
        refImage: (p && p.refImage) || "", refName: (p && p.refName) || "",
        locked: !!(p && p.locked), starred: !!(p && p.starred),
        sceneNos: inScenes, lines: lineCount[name] || 0,
        source: (p && p.source) || "script"
      };
    });

    // 剧本解析没提到、但已经有内容的角色（AI 分解出的次要角色 / 只在台词里出现的名字）保留
    var seenChar = {};
    characters.forEach(function (c) { seenChar[c.name] = 1; });
    ((prev && prev.characters) || []).forEach(function (a) {
      if (!a || seenChar[a.name] || ix.used[a.id] || !hasAuthored(a)) return;
      seenChar[a.name] = 1;
      characters.push(a);
    });

    var scenesOut = [], seen = {};
    scenes.forEach(function (s) {
      var key = [s.intExt || "", s.location || "", s.time || ""].join("|");
      var id = assetId("scene", key);
      if (seen[id]) { seen[id].sceneNos.push(s.no); return; }
      var sceneName = s.location || ("场景" + s.no);
      // 认领顺序由 claimScene 统一：id → 内外景+时间+名字 → 场次号 → 名字
      var p = claimScene(ix, { id: id, name: sceneName, intExt: s.intExt, time: s.time, no: s.no });
      var a = {
        id: (p && p.id) || id, kind: "scene", name: sceneName,
        intExt: s.intExt || "", time: s.time || "",
        appearance: (p && p.appearance) || "",
        refImage: (p && p.refImage) || "", refName: (p && p.refName) || "",
        locked: !!(p && p.locked), starred: !!(p && p.starred),
        sceneNos: [s.no], source: "script"
      };
      seen[id] = a; scenesOut.push(a);
    });
    ((prev && prev.scenes) || []).forEach(function (a) {
      if (!a || seen[a.id] || ix.used[a.id]) return;
      if (a.source === "manual" || hasAuthored(a)) {
        seen[a.id] = a; scenesOut.push(a);
      }
    });

    return { characters: characters, scenes: scenesOut, props: ((prev && prev.props) || []).slice() };
  }

  /**
   * AI 资产包 → 界面资产层。
   * 资产包负责「有内容的设定」（编号 / 优先级 / 三锚点 / 固定关键词串 / 提示词 / 溯源），
   * 界面资产层继续负责「用户的改动」（手改字段 / 参考图 / 锁定），两者合并而不是覆盖。
   * 规则：锁定整条不动；touched 字段一律以用户为准；剧本里有但资产包漏掉的角色自动补位，
   * 否则 bindShot 会绑不上，提示词里就少了这个人的外观。
   */
  function applyAssetPack(prev, pack, parsed) {
    var pa = (pack && pack.assets) || {};
    var ix = prevIndex(prev);

    function merge(prevItem, fields) {
      var out = Object.assign({}, fields);
      if (!prevItem) return out;
      if (prevItem.locked) {
        // 整条锁定：设定不动，但编号 / 提示词这些「系统字段」仍然跟随资产包
        return Object.assign({}, prevItem, {
          code: out.code || prevItem.code, priority: out.priority || prevItem.priority,
          anchors: out.anchors || prevItem.anchors, prompts: out.prompts || prevItem.prompts,
          keywordEn: out.keywordEn || prevItem.keywordEn, locked: true
        });
      }
      Object.keys(prevItem.touched || {}).forEach(function (k) {
        // 锚点是嵌套字段，手改用 anchors.face 这种点路径记账，合并时要落到子对象上
        if (k.indexOf("anchors.") === 0) {
          var ak = k.slice(8);
          out.anchors = Object.assign({}, out.anchors || {});
          out.anchors[ak] = (prevItem.anchors || {})[ak];
          return;
        }
        if (k in out || k === "keyword" || k === "appearance" || k === "wardrobe") out[k] = prevItem[k];
      });
      ["refImage", "refName", "genImages", "locked", "starred", "touched"].forEach(function (k) {
        if (prevItem[k] !== undefined) out[k] = prevItem[k];
      });
      if (prevItem.id) out.id = prevItem.id;   // id 沿用，别每次重新生成
      return out;
    }

    var characters = ((pa.characters) || []).map(function (c, i) {
      var name = trim(c.name || "");
      if (!name) return null;
      var p = claimChar(ix, name, "c:" + name);
      return merge(p, {
        id: "c:" + name, kind: "character", name: name,
        aliases: (c.aliases || []).slice(),
        code: c.code || "C" + pad2(i + 1), priority: c.priority || "P1",
        visibility: c.visibility || "", age: c.age || "", role: c.role || "",
        wardrobe: c.wardrobe || "", appearance: c.appearance || "",
        persona: (p && p.persona) || "",
        anchors: c.anchors || {}, keyword: c.keyword || "", keywordEn: c.keywordEn || "",
        prompts: c.prompts || {}, source: c.source || "inferred",
        evidence: c.evidence || [], sceneNos: c.sceneNos || [],
        weight: c.weight || 3, lines: (p && p.lines) || 0,
        touched: {}, refImage: "", refName: "", locked: false, starred: false
      });
    }).filter(Boolean);

    // 资产包漏掉的剧本角色（例如模型只挑了主要人物）：用规则结果补位，保证绑定不断
    var covered = {};
    characters.forEach(function (c) {
      covered[c.name] = 1;
      (c.aliases || []).forEach(function (a) { covered[a] = 1; });
    });
    ((parsed && parsed.characters) || []).forEach(function (n) {
      if (!n || covered[n]) return;
      var p = claimChar(ix, n, "c:" + n);
      characters.push(Object.assign({
        id: "c:" + n, kind: "character", name: n, aliases: [], code: "",
        priority: "P1", age: (p && p.age) || "", role: (p && p.role) || "",
        wardrobe: (p && p.wardrobe) || "", appearance: (p && p.appearance) || "",
        anchors: {}, keyword: "", prompts: {}, source: "script", evidence: [],
        sceneNos: [], weight: (p && p.weight) || 2, touched: (p && p.touched) || {},
        refImage: (p && p.refImage) || "", refName: (p && p.refName) || "",
        locked: !!(p && p.locked), starred: !!(p && p.starred)
      }, {}));
      covered[n] = 1;
    });

    var scenes = ((pa.scenes) || []).map(function (sc, i) {
      var name = trim(sc.name || "");
      if (!name) return null;
      // 与剧本重建用同一个 claimScene：id → 内外景+时间+名字 → 场次号 → 名字
      var prevItem = claimScene(ix, {
        id: "sc:" + name + "|" + (sc.intExt || "") + "|" + (sc.time || ""),
        name: name, intExt: sc.intExt, time: sc.time, no: (sc.sceneNos || [])[0]
      });
      var nos = (sc.sceneNos || []).slice();
      if (!nos.length && prevItem) nos = (prevItem.sceneNos || []).slice();
      return merge(prevItem, {
        id: "sc:" + name + "|" + (sc.intExt || "") + "|" + (sc.time || ""),
        kind: "scene", name: name,
        code: sc.code || "S" + pad2(i + 1), priority: sc.priority || "P1",
        intExt: sc.intExt || (prevItem && prevItem.intExt) || "",
        time: sc.time || (prevItem && prevItem.time) || "",
        appearance: sc.appearance || ((sc.anchors && sc.anchors.props) || []).join("；"),
        anchors: sc.anchors || {}, sceneEn: sc.sceneEn || "",
        prompts: sc.prompts || {}, source: sc.source || "inferred",
        evidence: sc.evidence || [], sceneNos: nos,
        touched: {}, refImage: "", refName: "", locked: false, starred: false
      });
    }).filter(Boolean);

    // 手动加的 / 资产包没覆盖到的场景保留（按场次号判断，不按名字）
    var coveredNos = {};
    scenes.forEach(function (s) { (s.sceneNos || []).forEach(function (n) { coveredNos[n] = 1; }); });
    ((prev && prev.scenes) || []).forEach(function (a) {
      if (ix.used[a.id]) return;   // 已被上面的资产包条目认领，别重复挂进来
      var keepIt = (a.source === "manual" && !scenes.some(function (s) { return s.name === a.name; }))
        || (a.sceneNos || []).some(function (n) { return !coveredNos[n]; });
      if (keepIt) scenes.push(a);
    });

    var props = ((pa.props) || []).map(function (pr, i) {
      var name = trim(pr.name || "");
      if (!name) return null;
      var p = ix.propByName[name] || null;
      if (p) ix.used[p.id] = 1;
      return merge(p, {
        id: "p:" + name, kind: "prop", name: name,
        code: pr.code || "P" + pad2(i + 1), priority: pr.priority || "P1",
        appearance: pr.appearance || name, boundTo: pr.boundTo || [],
        // 英文道具名要跨重解析保住：没有它，出图只能拿中文名当主体
        propEn: pr.propEn || (p && p.propEn) || "",
        anchors: {}, source: pr.source || "inferred", evidence: pr.evidence || [],
        refImage: "", refName: "", locked: false
      });
    }).filter(Boolean);
    ((prev && prev.props) || []).forEach(function (a) {
      if (!props.some(function (x) { return x.name === a.name; })) props.push(a);
    });

    return { characters: characters, scenes: scenes, props: props };
  }

  function allAssets(assets) {
    return ((assets && assets.characters) || [])
      .concat((assets && assets.scenes) || [], (assets && assets.props) || []);
  }
  function findAsset(assets, id) {
    if (!id) return null;
    var hit = allAssets(assets).filter(function (a) { return a.id === id; });
    return hit.length ? hit[0] : null;
  }
  /** 分镜绑定到的资产实体（顺序即槽位顺序）。 */
  function boundOf(shot, assets, kind) {
    var list = (assets && assets[kind + "s"]) || [];
    var ids = kind === "character" ? (shot.charIds || [])
      : kind === "scene" ? (shot.sceneId ? [shot.sceneId] : []) : (shot.propIds || []);
    return ids.map(function (id) {
      var hit = list.filter(function (a) { return a.id === id; });
      return hit.length ? hit[0] : null;
    }).filter(Boolean);
  }

  /** 绑定：说话人排第一，其余按在画面描述里出现的先后（= 出场顺序 = 参考图顺序）。 */
  function bindShot(shot, assets) {
    var chars = (assets && assets.characters) || [];
    var scenes = (assets && assets.scenes) || [];
    var props = (assets && assets.props) || [];
    var text = [shot.visual, shot.dialogue, shot.notes].join(" ");

    var ranked = [];
    chars.forEach(function (c) {
      var names = [c.name].concat(c.aliases || []);
      var pos = -1, spoken = false;
      names.forEach(function (n) {
        if (!n) return;
        if (shot.speaker && n === shot.speaker) spoken = true;
        var p = text.indexOf(n);
        if (p >= 0 && (pos < 0 || p < pos)) pos = p;
      });
      if (spoken) pos = -100;
      if (pos !== -1) ranked.push({ id: c.id, pos: pos });
    });
    ranked.sort(function (a, b) { return a.pos - b.pos; });
    var charIds = [];
    ranked.forEach(function (r) { if (charIds.indexOf(r.id) < 0) charIds.push(r.id); });

    var sc = scenes.filter(function (s) { return (s.sceneNos || []).indexOf(shot.sceneNo) >= 0; })[0];
    var sceneId = sc ? sc.id : "";
    var propIds = props.filter(function (p) { return p.name && text.indexOf(p.name) >= 0; })
      .map(function (p) { return p.id; });

    var ref = { charIds: charIds, sceneId: sceneId, propIds: propIds };
    return Object.assign({}, shot, ref, { assetSig: assetSignature(ref, assets) });
  }
  function bindAssets(shots, assets) {
    return (shots || []).map(function (s) { return bindShot(s, assets); });
  }

  function assetDescriptor(a) {
    if (!a) return "";
    return [a.kind, a.name, a.age || "", a.role || "", a.wardrobe || "",
      a.appearance || "", String(a.refImage || "").slice(0, 48)].join("/");
  }
  /** 资产签名：外观/服装/参考图任一变化，签名就变 → 镜头提示词标记为过期。 */
  function assetSignature(ref, assets) {
    var parts = [];
    (ref.charIds || []).forEach(function (id) { parts.push(assetDescriptor(findAsset(assets, id))); });
    if (ref.sceneId) parts.push(assetDescriptor(findAsset(assets, ref.sceneId)));
    (ref.propIds || []).forEach(function (id) { parts.push(assetDescriptor(findAsset(assets, id))); });
    return String(hash(parts.join("|")));
  }
  function assetStale(shot, assets) {
    return !!shot.assetSig && shot.assetSig !== assetSignature(shot, assets);
  }

  function appearanceText(c) {
    // 有「固定关键词串」就原样注入，逐字不改 —— 角色一致性全靠它，别在镜头里重写全脸。
    var kw = trim((c && c.keyword) || "");
    if (kw) return c.name + "，" + kw;
    var bits = [c.name];
    if (c.age) bits.push(c.age);
    if (c.wardrobe) bits.push("穿" + String(c.wardrobe).replace(/^穿/, ""));
    else if (c.appearance) bits.push(String(c.appearance).slice(0, 60));
    else if (c.role) bits.push(c.role);
    return bits.join("，");
  }
  /** H3 正文用通用身份（禁名字）：林晚(店员的) → 一名便利店店员。 */
  function genericRole(assets, name) {
    if (!assets || !name) return null;
    var hit = null;
    (assets.characters || []).forEach(function (c) { if (c.name === name) hit = c; });
    if (!hit) return null;
    var bits = [];
    var age = hit.age ? String(hit.age).replace(/\D/g, "") : "";
    if (age) bits.push(age + "岁");
    var role = hit.role || (hit.name !== name ? hit.name : "");
    if (!role && hit.wardrobe) role = String(hit.wardrobe).slice(0, 8);
    if (role) bits.push(role);
    if (!bits.length) return null;
    return (age ? "" : "一位") + bits.join("，");
  }
  /** scene 描述交给 H3（改名）。 */
  function sceneText(a) {
    return [a.name, a.intExt, a.time, a.appearance].filter(Boolean).join("，");
  }

  /** 台词 → 口型提示：视频模型需要显式的「张嘴说话」才会生成嘴部动作。 */
  function dialogueCue(shot) {
    var line = trim(shot.dialogue || "");
    if (!line) return "";
    var speaker = trim(shot.speaker || "") || "角色";
    var seg = line.split("：");
    if (seg.length > 1 && trim(seg[0]).length <= 12) { speaker = trim(seg[0]); line = seg.slice(1).join("："); }
    var mood = trim((shot.detail && shot.detail.mood) || "");
    return speaker + "张嘴说话" + (mood ? "，表情" + mood : "") + "，台词：「" + line + "」";
  }

  /**
   * 提示词编译：主体/动作 → 光线 → 运镜 → 景别/构图 → 角色外观 → 场景 → 道具 → 情绪 → 口型 → 画幅。
   * 每一段都先查重，避免「中景，中景」这类重复堆积。
   */
  function assemblePrompt(shot, assets, config) {
    var d = normalizeDetail(shot.detail);
    var parts = [];
    function joined() { return parts.join("。"); }
    function has(t) { return !!t && joined().indexOf(t) >= 0; }
    // 每段去掉尾部的句读再拼接，避免「画面里。。中景。」
    function add(t) { t = trim(t).replace(/[。，、；,.;:：]+$/, ""); if (t) parts.push(t); }

    add(shot.visual);
    if (d.light && !has(d.light)) add(d.light);
    if (d.camera && !has(d.camera)) add(d.camera);
    var shotBits = [];
    if (shot.size && !has(shot.size)) shotBits.push(shot.size);
    if (d.composition && !has(d.composition)) shotBits.push(d.composition);
    if (shotBits.length) add(shotBits.join("，"));

    var chars = boundOf(shot, assets, "character");
    if (chars.length) add("角色：" + chars.map(appearanceText).join("；"));
    var scs = boundOf(shot, assets, "scene");
    if (scs.length) add("场景：" + scs.map(sceneText).join("；"));
    var pps = boundOf(shot, assets, "prop");
    if (pps.length) add("道具：" + pps.map(function (p) { return p.name; }).join("、"));

    if (d.mood && !has(d.mood)) add(d.mood);
    var cue = dialogueCue(shot);
    if (cue) add(cue);
    add("短剧质感，" + ((config && config.aspect) || "16:9") + " 画幅");
    return parts.filter(Boolean).join("。") + "。";
  }

  /**
   * H3 视频提示词 · 镜头行（一段一次生成的画面主体部分）。
   * 规范学自 shuohao-skills/novel-storyboard（references/h3-prompt.md + shot-writing.md）：
   *   1. 正文禁角色名，用通用身份（林晚 → 一名 27岁，便利店店员）
   *   2. 台词逐字保留，放进 <d>[Chinese] …</d>；说话人身份写在外面
   *   3. 一个镜头一个主运镜，写成动作句；不写画幅、不写画风
   *   4. 声音三分层：台词/歌声→本行；环境与动作声→soundscape；配乐→music
   */
  function h3ShotDesc(shot, assets, sec) {
    var d = normalizeDetail(shot.detail);
    var parts = [];
    function has(t) { return !!t && parts.join("。").indexOf(t) >= 0; }
    function add(t) { t = trim(t).replace(/[。，、；,.;:：]+$/, ""); if (t) parts.push(t); }

    // 取一个画面主体：detail.subject / action 里的名字换成通用身份
    var subject = trim(d.subject || "");
    var action = trim(d.action || "");
    var who = null;
    var chars = boundOf(shot, assets, "character");
    // 优先用说话人当主体；否则用第一个绑定的角色
    var lead = shot.speaker || ((chars[0] || {}).name || "");
    if (lead && assets) who = genericRole(assets, lead);
    if (!who && chars.length && assets) who = genericRole(assets, chars[0].name);
    if (!who) who = "人物";

    // 动作描述：detail.action 优先；否则从 shot.visual 提取，并把其中的角色名换成通用身份
    var actionText = trim(d.action || "");
    var leadName = lead;
    if (!actionText) {
      actionText = String(shot.visual || "");
      // 把句子里的所有角色名替换成通用身份（现成的 who），避免正文出现剧本人名
      if (chars.length) {
        chars.forEach(function (c) {
          if (!c.name) return;
          var wr = genericRole(assets, c.name) || "人物";
          // 优先替换「名字（身份括注）」整体，避免名字和括注各替换一次造成重复
          actionText = actionText.replace(new RegExp(escapeRegExp(c.name) + "\\s*[（(][^）)]*[）)]"), wr);
          actionText = actionText.split(c.name).join(wr);
        });
      }
      actionText = trim(actionText).replace(/^[，,。、\s]+/, "").replace(/(远景|全景|中景|近景|特写)+$/, "");
    }
    // 情绪 → 外化（不准写"很悲伤"）
    if (d.mood && !has(d.mood) && !/说|开口|台词/.test(d.mood)) add("表情" + d.mood.replace(/[，。、,;]\s*$/, ""));

    // 主运镜：一部一镜，成动作句
    var cam = trim((d.camera || "").replace(/^运镜[：:]\s*/, ""));
    var camText = "";
    if (cam && !/固定|不动/.test(cam)) {
      var kw = cam.split(/[，,。\s]/)[0].replace(/镜头/g, "");
      if (kw) camText = "镜头" + kw;
    }

    // 组装主体 + 动作：动作文本已含通用身份，不再重复前置 who
    var bodyBit = actionText || who;
    if (/^[，,。、\s]/.test(bodyBit)) bodyBit = bodyBit.replace(/^[，,。、\s]+/, "");
    if (camText) add(camText + "，" + bodyBit); else add(bodyBit);

    // 景别 + 构图量化
    var sbits = [];
    if (shot.size && !has(shot.size)) sbits.push(shot.size);
    if (d.composition && !has(d.composition)) sbits.push(d.composition);
    if (sbits.length) add(sbits.join("，"));

    // 对白：逐字保留进 <d>，说话人身份写在外面（禁名字）
    var line = trim(shot.dialogue || "");
    if (line && !shot.silence) {
      var seg = line.split("：");
      var sp = trim(shot.speaker || "");
      if (seg.length > 1 && trim(seg[0]).length <= 12 && !sp) { sp = trim(seg[0]); line = seg.slice(1).join("："); }
      if (sp) {
        var gr = genericRole(assets, sp) || "有人";
        add(gr + "说，台词：" + "<d>[Chinese] " + line + "</d>");
      } else {
        add("（画外）台词：" + "<d>[Chinese] " + line + "</d>");
      }
    }
    return parts.filter(Boolean).join("。") + "。";
  }

  function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  /**
   * 一条 H3 提示词 = 对齐指令 + 每个 [Shot k] 一行 + soundscape + music。
   * norm 学自 shuohao-skills/novel-storyboard（references/h3-prompt.md）：
   *   首行固定对齐指令；[Shot 1] 锚定 <Picture 1>；后续切标记切点时刻；
   *   台词逐字进 <d>[Chinese]…</d>；正文禁名字（用通用身份）；不写画风/画幅。
   * shots: [{shot, visual, size, camera, composition, mood, dialogue, speaker, second}]
   */
  function h3Prompt(shots, assets, config, refImageUrl) {
    var lines = [];
    var esc = function (s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); };

    // 首行对齐指令：有首帧图给官方句，没有就整段纯正文（t2v）不给对齐行
    if (refImageUrl) {
      lines.push("For the target video, at 0.00 seconds into the target video, <Picture 1> is fully referenced.");
      lines.push("");
    } else {
      lines.push("The following describes the actions and dialogue within the shot.");
      lines.push("");
    }

    lines.push("integrated_multimodal_description:");
    shots.forEach(function (it, idx) {
      var sec = Number(it.second) || 0;
      var prefix = "";
      if (idx === 0) {
        prefix = refImageUrl ? "[Shot 1] " : "[Shot 1] ";
      } else {
        var mm = Math.floor(sec / 60), ss = (sec % 60).toFixed(3).padStart(6, "0");
        prefix = "[Shot " + (idx + 1) + "] At 00:" + String(mm).padStart(2, "0") + ":" + ss + ", the camera cuts to ";
      }
      lines.push(prefix + h3ShotDesc(it.shot, assets, sec));
    });

    // 声景：环境与动作声（不复述台词）；配乐：没有就 N/A
    var scSound = trim((config && config.soundscape) || shotSoundscape(shots));
    lines.push("");
    lines.push("overall_soundscape: " + (scSound || "ambient room tone, subtle crowd noise"));
    lines.push("non_diegetic_music: " + (config && config.music ? config.music : "N/A"));
    return lines.join("\n");
  }

  /** 从段内镜头备注聚合一条环境声。 */
  function shotSoundscape(shots) {
    var found = [];
    shots.forEach(function (it) {
      var n = trim((it.shot && it.shot.notes) || "");
      var m = /环境声|声景[：:]\s*([^\n;]+)/.exec(n);
      if (m) found.push(trim(m[1]));
    });
    return found.join("；");
  }
  function h3PromptDefault(shot, assets, config) {
    return h3Prompt([{ shot: shot, second: 0 }], assets, config, null);
  }

  /** 参考图槽位表：角色优先、场景顺延，槽位顺序就是参考图顺序（模型入参契约）。 */
  function refsFor(shot, assets) {
    var out = [], slot = 1;
    boundOf(shot, assets, "character").forEach(function (c) {
      out.push({ slot: "character" + slot, kind: "character", name: c.name, image: c.refImage || "" });
      slot += 1;
    });
    boundOf(shot, assets, "scene").forEach(function (s) {
      out.push({ slot: "character" + slot, kind: "scene", name: s.name, image: s.refImage || "" });
      slot += 1;
    });
    return out;
  }

  /** 槽位标签版画面描述：`林晚[character1:林晚]`。只给认槽位的模型用，通用模型用纯文本版。 */
  function tagPrompt(shot, assets) {
    var text = String(shot.visual || "");
    if (!text || /\[character\d+:/.test(text)) return text;
    var slot = 1;
    boundOf(shot, assets, "character").forEach(function (c) {
      var pos = text.indexOf(c.name);
      if (pos < 0) return;
      text = text.slice(0, pos) + c.name + "[character" + slot + ":" + c.name + "]" + text.slice(pos + c.name.length);
      slot += 1;
    });
    boundOf(shot, assets, "scene").forEach(function (s) {
      if (!s.name) return;
      var pos = text.indexOf(s.name);
      if (pos < 0) return;
      text = text.slice(0, pos) + s.name + "[character" + slot + ":" + s.name + "]" + text.slice(pos + s.name.length);
    });
    return text;
  }

  /** 资产改动后刷新提示词（不动手改过的画面描述）。 */
  function refreshShotAssets(shot, assets) {
    return bindShot(shot, assets);
  }

  /* ------------------- 出片端契约（comfyui-h3-demo /v1/videos） -------------------
    对端的硬约束（实抓 gateway/app.py + registry.py）：
      · mode 只有 t2v / i2v / fl2v —— 没有多参考图模式
      · duration 只有 5s / 8s / 10s 三档 —— 连续秒数会被 400 拒
      · width / height 必须是 32 的整数倍
      · prompt 上限 4000 字符
      · i2v 只接受一张「首帧」图，不是参考图
    所以这里做一层翻译：连续时长吸附档位、画幅换算成合法宽高、多槽位参考图降级为文字。
    翻不动的地方（多图、被拉长的时长）如实写进 preflight 告警，不假装能跑。
  ------------------------------------------------------------------------- */
  var H3_CONTRACT = {
    endpoint: "/v1/videos",
    modes: ["t2v", "i2v", "fl2v"],
    durations: ["5s", "8s", "10s"],
    promptMaxLength: 4000,
    multiRefSupported: false,
    note: "i2v 只吃一张首帧图；多槽位参考图需 r2v 类模型，本接口不支持"
  };

  var H3_SECONDS = { "5s": 5, "8s": 8, "10s": 10 };

  // 每档画质 × 每种画幅的宽高，全部是 32 的整数倍（H3 VAE 硬约束）。
  var H3_FRAMES = {
    "16:9": { fast: [864, 480], standard: [1024, 576], high: [1344, 768] },
    "9:16": { fast: [480, 864], standard: [576, 1024], high: [768, 1344] },
    "1:1": { fast: [640, 640], standard: [768, 768], high: [1024, 1024] },
    "2.39:1": { fast: [1088, 448], standard: [1280, 544], high: [1536, 640] }
  };

  function h3Frame(aspect, quality) {
    var q = (quality && H3_FRAMES["16:9"][quality]) ? quality : "standard";
    var row = H3_FRAMES[aspect] || H3_FRAMES["16:9"];
    var wh = row[q];
    return { quality: q, aspect: H3_FRAMES[aspect] ? aspect : "16:9", width: wh[0], height: wh[1] };
  }

  /** 连续时长 → 对端档位。向上就近（宁可多一点帧，也别把台词挤掉）。 */
  function h3Duration(sec) {
    var n = Number(sec) || 0;
    var pick = n <= 5 ? "5s" : (n <= 8 ? "8s" : "10s");
    return { value: pick, seconds: H3_SECONDS[pick], snapped: Math.abs(n - H3_SECONDS[pick]) > 0.01 };
  }

  /** 单镜 → 对端入参。mode 由「有没有可当首帧的图」决定，不是由有没有参考图决定。 */
  function h3Item(shot, assets, config, frame) {
    var refs = refsFor(shot, assets);
    var withImg = refs.filter(function (r) { return r.image; });
    var first = withImg[0] || null;
    refs.forEach(function (r) {
      r.role = !r.image ? "" : (first && r.slot === first.slot ? "firstFrame" : "reference");
    });
    var dur = h3Duration(shot.duration);
    var f = frame || h3Frame((config && config.aspect) || "16:9", (config && config.videoQuality) || "standard");
    var prompt = assemblePrompt(shot, assets, config);
    return {
      shot: shot.code,
      mode: first ? "i2v" : "t2v",
      duration: dur.value,
      durationSnapped: dur.snapped,
      quality: f.quality,
      width: f.width,
      height: f.height,
      prompt: prompt,
      promptLength: prompt.length,
      promptTooLong: prompt.length > H3_CONTRACT.promptMaxLength,
      refs: refs,
      multiRef: withImg.length > 1,
      firstFrameUrl: (first || {}).image || ""
    };
  }

  /** 导出前预检：把「跑不了 / 会变形」的地方一次性说清。 */
  function h3Preflight(items, shots, assets) {
    var p = {
      shots: items.length, t2v: 0, i2v: 0,
      multiRef: 0, durationSnapped: 0, promptTooLong: 0,
      scriptSeconds: totalDuration(shots), outputSeconds: 0,
      // 资产是否真的用上了：这两个数字是「一致性有没有落地」的体检指标
      assetBound: 0, assetKeywordExpected: 0, assetKeywordInjected: 0,
      warnings: []
    };
    var chars = (assets && assets.characters) || [];
    items.forEach(function (it, i) {
      if (it.mode === "i2v") p.i2v += 1; else p.t2v += 1;
      if (it.multiRef) p.multiRef += 1;
      if (it.durationSnapped) p.durationSnapped += 1;
      if (it.promptTooLong) p.promptTooLong += 1;
      p.outputSeconds += H3_SECONDS[it.duration] || 0;

      var s = shots[i] || {};
      if ((s.charIds || []).length || s.sceneId) p.assetBound += 1;
      var kws = chars.filter(function (c) {
        return (s.charIds || []).indexOf(c.id) >= 0 && c.keyword;
      }).map(function (c) { return c.keyword; });
      if (kws.length) {
        p.assetKeywordExpected += 1;
        if (kws.every(function (k) { return String(it.prompt || "").indexOf(k) >= 0; })) {
          p.assetKeywordInjected += 1;
        }
      }
    });
    if (!p.assetKeywordExpected && p.shots) {
      p.warnings.push("没有任何镜头带固定关键词串：先做一次资产分解，角色一致性目前只靠文字硬撑");
    } else if (p.assetKeywordExpected > p.assetKeywordInjected) {
      p.warnings.push((p.assetKeywordExpected - p.assetKeywordInjected) +
        " 个镜头该带关键词串却没带上（设定改过但没刷新提示词？）");
    }
    if (p.multiRef) {
      p.warnings.push(p.multiRef + " 个镜头挂了两张以上参考图，该接口只吃一张首帧，其余已降级为提示词里的文字描述");
    }
    if (p.durationSnapped) {
      p.warnings.push(p.durationSnapped + " 个镜头的时长吸附到 5/8/10 秒档位：成片 " +
        p.scriptSeconds + " 秒 → " + p.outputSeconds + " 秒");
    }
    if (p.promptTooLong) {
      p.warnings.push(p.promptTooLong + " 条提示词超过 " + H3_CONTRACT.promptMaxLength + " 字符上限，需精简后再提交");
    }
    return p;
  }

  // 画面比例协议：只接受 16:9 / 9:16，其余记进 note 并回退 16:9。
  var LEGAL_ASPECTS = ["16:9", "9:16"];

  /**
   * 段（segment）：一次生成调用。按「不跨场 + 累计 ≤ maxSeg 秒」把镜头分组成段。
   * 段内每个镜头一个切点（上一段的累计秒数），首镜 0 秒。
   * 返回 [{ sceneNo, seconds, shots:[{shot, start, dur}] }]
   * 借鉴 shuohao-skills 的「段 = 一次 H3 生成」思想；我们的对端上限 10s（H3_CONTRACT.durations）。
   */
  function segmentShots(shots, maxSegSeconds) {
    var cap = maxSegSeconds || 10;      // 对端 duration 上限 = 10s
    var segs = [];
    var cur = null;
    shots.forEach(function (s) {
      var dur = Number(s.duration) || H3_SECONDS["5s"];
      if (!cur) {
        cur = { sceneNo: s.sceneNo, acc: 0, shots: [] };
        segs.push(cur);
      }
      // 不跨场；超上限开新段（单镜本身 > cap 也独立成段，交给对端吸附）
      if (cur.acc + dur > cap || cur.sceneNo !== s.sceneNo) {
        if (cur.acc > 0 || cur.shots.length) {
          cur = { sceneNo: s.sceneNo, acc: 0, shots: [] };
          segs.push(cur);
        }
      }
      cur.shots.push({ shot: s, start: cur.acc, dur: dur });
      cur.acc += dur;
    });
    return segs;
  }

  /**
   * 一段顶层的 H3 提示词（含切点时刻 + soundscape + music）。
   * 段内每镜一行 [Shot k]；非首镜带切点时刻 At mm:ss.xxx。
   */
  function h3SegmentPrompt(seg, assets, config, refImageUrl) {
    var items = seg.shots.map(function (it) {
      return { shot: it.shot, second: it.start };
    });
    return h3Prompt(items, assets, config, refImageUrl);
  }

  /**
   * 镜头级校验（学自 shuohao-skills 第 3 步的硬门）：
   *   A. 每切时长在合理区间（2–10s，对端可吸附档位）
   *   B. 台词能装进镜头：台词按 4字/秒 折算 ≤ 镜头时长
   *   C. H3 正文不含角色名（视频模型禁名字，只有 <d> 块内台词允许）
   * 返回 [{code, level, shot, title, detail}]，供导出的 preflight 与界面展示。
   */
  function validateShots(shots, assets) {
    var out = [];
    var names = (assets && assets.characters) ? assets.characters.map(function (c) { return c.name; }) : [];
    shots.forEach(function (s) {
      var dur = Number(s.duration) || 0;
      if (dur < 2 || dur > 10) {
        out.push({ code: "cut-duration", level: "warn", shot: s.code, title: "镜头时长偏离区间", detail: "第 " + s.code + " 镜为 " + dur + " 秒，短剧节奏区间建议 2–10 秒（对端可吸附 5/8/10s）。" });
      }
      var line = String(s.dialogue || "").replace(/<d>\[Chinese\]|<\/d>/g, "").split("：").slice(1).join("：");
      // 台词秒数（汉字按 4字/秒，含标点）
      var chars = line.replace(/\s/g, "").length;
      var speechSec = Math.ceil(chars / 4);
      if (line && speechSec > dur) {
        out.push({ code: "line-overflow", level: "error", shot: s.code, title: "台词装不进镜头", detail: "第 " + s.code + " 镜台词约需 " + speechSec + " 秒（" + chars + " 字），但镜头只有 " + dur + " 秒，会被切掉尾音。" });
      }
      // H3 正文禁角色名（剥掉 <d> 台词块后检查）
      if (names.length) {
        var h3 = h3ShotDesc(s, assets, 0).replace(/<d>\[Chinese\][\s\S]*?<\/d>/g, "");
        var bad = names.filter(function (n) { return n && h3.indexOf(n) >= 0; });
        if (bad.length) {
          out.push({ code: "h3-role-name", level: "warn", shot: s.code, title: "H3 正文出现角色名", detail: "第 " + s.code + " 镜「" + bad.join("、") + "」应写成通用身份（视频模型规范禁名字）。" });
        }
      }
    });
    return out;
  }

  /* ------------------------------- 导出 ------------------------------- */
  function csvCell(v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; }

  function formatExport(kind, payload) {
    var meta = payload.meta || {}, shots = payload.shots || [], parsed = payload.parsed || {}, config = payload.config || {};
    var eps = payload.episodes || [];
    var assets = payload.assets || null;
    var hasEp = eps.length > 0;
    function castOf(s) { return boundOf(s, assets, "character").map(function (c) { return c.name; }).join("、"); }
    function epOf(s) {
      var n = s.episode || episodeOf(eps, s.sceneNo);
      var e = eps.filter(function (x) { return x.no === n; })[0];
      return e ? "第" + e.no + "集" + (e.title ? " · " + e.title : "") : "";
    }
    if (kind === "json") {
      return JSON.stringify({
        meta: meta, config: config, script: parsed,
        assets: assets ? {
          characters: assets.characters, scenes: assets.scenes, props: assets.props,
          note: "分镜里的 charIds / sceneId / propIds 指向这里的资产；assetSig 用于判断提示词是否过期"
        } : null,
        episodes: hasEp ? eps.map(function (e) {
          return { no: e.no, title: e.title, synopsis: e.synopsis, sceneFrom: e.sceneFrom, sceneTo: e.sceneTo, hook: e.hook };
        }) : [],
        shots: shots
      }, null, 2);
    }
    if (kind === "csv") {
      var detailHead = DETAIL_FIELDS.map(function (k) { return "分镜-" + DETAIL_LABELS[k]; });
      var head = (hasEp ? ["集"] : []).concat(
        ["镜号", "场次", "场景", "出场角色", "类型", "画面描述", "景别", "时长(秒)", "台词", "备注", "原始镜号"]
      ).concat(detailHead).concat(["自动补镜"]);
      var rows = shots.map(function (s) {
        var d = normalizeDetail(s.detail);
        return (hasEp ? [epOf(s)] : []).concat(
          [s.code, "第" + s.sceneNo + "场", s.sceneLabel, castOf(s), kindName(s.kind), s.visual, s.size, s.duration, s.dialogue, s.notes, s.originCode]
        ).concat(DETAIL_FIELDS.map(function (k) { return d[k]; }))
          .concat([s.patched ? "是" : ""]).map(csvCell).join(",");
      });
      return "\ufeff" + head.map(csvCell).join(",") + "\n" + rows.join("\n");
    }
    if (kind === "md") {
      var out = ["# " + (meta.title || "短剧") + " · 分镜表", "",
        "> 共 " + shots.length + " 个镜头 / " + (parsed.stats ? parsed.stats.scenes : 0) + " 场" +
        (hasEp ? " / " + eps.length + " 集" : "") + " / 总时长约 " + totalDuration(shots) + " 秒　·　画幅 " + config.aspect, ""];
      if (assets && assets.characters.length) {
        out.push("## 角色设定（全剧共用）", "", "| 角色 | 年龄 | 服装 | 外观 | 戏份 |", "| --- | --- | --- | --- | --- |");
        assets.characters.forEach(function (c) {
          out.push("| " + mdCell(c.name) + " | " + mdCell(c.age || "—") + " | " + mdCell(c.wardrobe || "—") +
            " | " + mdCell(c.appearance || c.role || "—") + " | " + c.weight + "/5 |");
        });
        out.push("");
      }
      var lastEp = null, lastScene = null;
      shots.forEach(function (s) {
        var ep = hasEp ? epOf(s) : "";
        if (hasEp && ep !== lastEp) {
          var e = eps.filter(function (x) { return "第" + x.no + "集" + (x.title ? " · " + x.title : "") === ep; })[0];
          out.push("", "# " + (ep || "分集"), "");
          if (e && e.synopsis) out.push("> " + mdCell(e.synopsis), "");
          if (e && e.hook) out.push("> 集尾钩子：" + mdCell(e.hook), "");
          lastEp = ep; lastScene = null;
        }
        if (s.sceneNo !== lastScene) { out.push("", "## " + s.sceneLabel, "", "| 镜号 | 出场角色 | 画面描述 | 景别 | 时长 | 台词 | 备注 | 分镜描述卡 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"); lastScene = s.sceneNo; }
        var dt = detailParts(s.detail).map(mdCell).join("<br>") || "—";
        out.push("| " + s.code + " | " + mdCell(castOf(s) || "—") + " | " + mdCell(s.visual) + " | " + s.size + " | " + s.duration + "s | " +
          mdCell(s.dialogue || "—") + " | " + mdCell(s.notes || "—") + " | " + dt + " |" +
          (s.patched ? " <!-- 自动补镜 -->" : ""));
      });
      return out.join("\n");
    }
    if (kind === "txt") {
      var t = [(meta.title || "短剧") + " · 拍摄清单", "共 " + shots.length + " 镜" + (hasEp ? " / " + eps.length + " 集" : "") + "，约 " + totalDuration(shots) + " 秒", ""];
      var curEp = null;
      shots.forEach(function (s) {
        if (hasEp) {
          var ep = epOf(s);
          if (ep !== curEp) { t.push("", "═══ " + ep + " ═══", ""); curEp = ep; }
        }
        t.push("【" + s.code + "】" + s.sceneLabel + "　" + s.size + "　" + s.duration + "s" + (s.locked ? "　🔒 锁定" : ""));
        var cast = castOf(s);
        if (cast) t.push("  角色：" + cast);
        t.push("  画面：" + s.visual);
        if (s.dialogue) t.push("  台词：" + s.dialogue);
        if (s.notes) t.push("  备注：" + s.notes);
        var parts = detailParts(s.detail);
        if (parts.length) {
          t.push("  分镜卡：");
          parts.forEach(function (p) { t.push("    · " + p); });
        }
        if (s.patched) t.push("  ※ AI 漏项自动补镜");
        t.push("");
      });
      return t.join("\n");
    }
    if (kind === "video-prompts") {
      // 对接 comfyui-h3-demo POST /v1/videos。
      // schema v4：在 v3 的「每镜一条」之上，新增「段」——一次生成调用（≤10s，不跨场），
      // 整段一条 h3Prompt（[Shot k] 带切点时刻 + soundscape + music）。
      // v2 的 "r2v" 名已废弃（对端无多参考图模式）；i2v = 有首帧图。
      var frame = h3Frame(config.aspect || "16:9", config.videoQuality || "standard");
      var items = shots.map(function (s) {
        var it = h3Item(s, assets, config, frame);
        it.episode = hasEp ? epOf(s) : "";
        it.scene = s.sceneLabel;
        it.size = s.size;
        it.scriptDuration = s.duration;   // 分镜表里的原时长，吸附后仍保留以便回查
        it.taggedPrompt = tagPrompt(s, assets);
        it.cast = it.refs.filter(function (r) { return r.kind === "character"; }).map(function (r) { return r.name; });
        it.dialogue = s.dialogue || "";
        it.speaker = s.speaker || "";
        it.locked = !!s.locked;
        it.notes = s.notes;
        it.assetStale = assetStale(s, assets);
        // H3 专属字段：正文（通用身份、禁画风/画幅、台词进 <d> 块）+ 顶到切点的对齐行
        it.h3Shot = h3ShotDesc(s, assets, 0);
        it.h3Prompt = h3Prompt([{ shot: s, second: 0 }], assets, config, it.firstFrameUrl || null);
        return it;
      });

      // 段级视图：一次生成调用。干净的组，供「按段提交」和界面分组。
      var segs = segmentShots(shots, 10).map(function (seg, i) {
        var refs = seg.shots.reduce(function (acc, x) { return acc.concat(refsFor(x.shot, assets)); }, []);
        var withImg = refs.filter(function (r) { return r.image; });
        var firstFrame = withImg[0] || null;
        var durSec = seg.shots.reduce(function (a, x) { return a + x.dur; }, 0);
        return {
          seg: pad3(i + 1), sceneNo: seg.sceneNo, scene: "", // 由调用方填 sceneLabel
          shots: seg.shots.map(function (x) { return x.shot.code; }),
          seconds: Math.round(durSec), startSeconds: 0,
          mode: firstFrame ? "i2v" : "t2v",
          firstFrameUrl: (firstFrame || {}).image || "",
          frame: frame,
          duration: E_dur(seg),   // 段总秒 → 对端档位（吸附）
          h3Prompt: h3SegmentPrompt(seg, assets, config, (firstFrame || {}).image || "")
        };
      });
      // 回填 scene 与段内相对切点
      segs.forEach(function (seg) {
        var fr = shots.find(function (s) { return s.code === seg.shots[0]; });
        if (fr) seg.scene = fr.sceneLabel;
      });

      return JSON.stringify({
        schema: "shortplay-v4",
        target: "comfyui-h3-demo POST /v1/videos",
        contract: H3_CONTRACT,
        aspect: (LEGAL_ASPECTS.indexOf(config.aspect) >= 0 ? config.aspect : "16:9") || "16:9",
        frame: frame,
        preflight: Object.assign(h3Preflight(items, shots, assets), { cutChecks: validateShots(shots, assets) }),
        // 段（一次生成调用）
        segments: segs,
        // refs 的槽位顺序 = 参考图顺序（角色优先、场景顺延），character1 是第一个槽。
        assets: assets ? {
          characters: assets.characters.map(function (c) {
            return { id: c.id, name: c.name, age: c.age, wardrobe: c.wardrobe, appearance: c.appearance, ref: c.refImage || "" };
          }),
          scenes: assets.scenes.map(function (s) {
            return { id: s.id, name: s.name, intExt: s.intExt, time: s.time, appearance: s.appearance, ref: s.refImage || "" };
          }),
          props: assets.props.map(function (p) { return { id: p.id, name: p.name }; })
        } : null,
        episodes: hasEp ? eps.map(function (e) { return { no: e.no, title: e.title, sceneFrom: e.sceneFrom, sceneTo: e.sceneTo }; }) : [],
        items: items
      }, null, 2);
    }
    return "";
  }

  function E_dur(seg) {
    var sec = seg.seconds;
    var pick = sec <= 5 ? "5s" : (sec <= 8 ? "8s" : "10s");
    return pick;
  }

  function mdCell(v) { return String(v || "").replace(/\|/g, "\\|").replace(/\n/g, " "); }
  function kindName(k) { return { establishing: "建立", action: "动作", dialogue: "对白", closing: "收束" }[k] || k; }
  function totalDuration(shots) { return Math.round(shots.reduce(function (a, s) { return a + (Number(s.duration) || 0); }, 0) * 10) / 10; }

  /* ------------------------------ 示例剧本 ------------------------------ */
  var SAMPLE_SCRIPT = [
    "《雨夜便利店》",
    "",
    "第1场 外景 · 便利店门口 · 夜",
    "雨下得很急，霓虹招牌在水洼里碎成一片。",
    "林晚（27岁，便利店店员）把伞架搬到门边，抬头看了眼街对面。",
    "△ 一辆黑色轿车停在路边，没有熄火。",
    "林晚：又是一整夜的雨。",
    "（她低头看了眼手机，屏幕上是三条未读消息。）",
    "",
    "第2场 内景 · 便利店收银台 · 连续",
    "自动门叮咚响。",
    "陈默（30岁，外套湿透）走进来，把一罐热咖啡放在柜台上。",
    "陈默：还有热的吗？",
    "林晚：只剩这一罐了。",
    "△ 陈默的手在发抖，他没有抬头。",
    "林晚（把咖啡推回去）：你不是第一次来这儿。",
    "陈默：……我以前住这附近。",
    "",
    "第3场 内景 · 便利店靠窗座位 · 稍后",
    "两人隔着一张小桌坐下，雨声被玻璃挡在外面。",
    "林晚：你一直在等谁？",
    "陈默：等我女儿。她以前每天这个点来买酸奶。",
    "△ 陈默从口袋里拿出一张旧照片，推到桌子中间。",
    "林晚没有说话，把那罐热咖啡轻轻推到照片旁边。",
    "（镜头缓缓拉远，便利店的暖光在雨夜里像一小块岛。）",
    "",
    "第4场 外景 · 便利店门口 · 次日清晨",
    "雨停了。林晚把伞架收回店里，街对面的车位空着。",
    "△ 柜台上留着那张旧照片，背面写着一行字：谢谢你还记得。",
    "林晚（轻声）：明天见。"
  ].join("\n");

  var SAMPLE_PROBLEM_SCRIPT = [
    "《待补全示例》",
    "",
    "第1场",
    "雨下得很大，街灯亮着。",
    "小明：这里好像没人。",
    "明：要不要进去看看？",
    "",
    "第1场",
    "小明：灯还亮着。"
  ].join("\n");

export const Engine = {
    DEFAULT_CONFIG: DEFAULT_CONFIG,
    SIZES: SIZES,
    DETAIL_FIELDS: DETAIL_FIELDS,
    DETAIL_LABELS: DETAIL_LABELS,
    normalizeDetail: normalizeDetail,
    detailParts: detailParts,
    detailText: detailText,
    SAMPLE_SCRIPT: SAMPLE_SCRIPT,
    SAMPLE_PROBLEM_SCRIPT: SAMPLE_PROBLEM_SCRIPT,
    parseScript: parseScript,
    classifySource: classifySource,
    scriptSpec: scriptSpec,
    normalizeLocal: normalizeLocal,
    diagnose: diagnose,
    applyFix: applyFix,
    buildStoryboard: buildStoryboard,
    regenerateShots: regenerateShots,
    formatExport: formatExport,
    totalDuration: totalDuration,
    kindName: kindName,
    sceneLabel: sceneLabel,
    pad3: pad3, pad2: pad2,
    episodeLabel: episodeLabel,
    localEpisodes: localEpisodes,
    scriptSlice: scriptSlice,
    episodeOf: episodeOf,
    assignEpisodes: assignEpisodes,
    renumberShots: renumberShots,
    /* 资产层 */
    ASSET_KIND_LABEL: ASSET_KIND_LABEL,
    ASSET_FIELDS: ASSET_FIELDS,
    assetId: assetId,
    buildAssets: buildAssets,
    applyAssetPack: applyAssetPack,
    findAsset: findAsset,
    boundOf: boundOf,
    bindShot: bindShot,
    bindAssets: bindAssets,
    assetSignature: assetSignature,
    assetStale: assetStale,
    refreshShotAssets: refreshShotAssets,
    appearanceText: appearanceText,
    /* 提示词编译 */
    assemblePrompt: assemblePrompt,
    tagPrompt: tagPrompt,
    refsFor: refsFor,
    dialogueCue: dialogueCue,
    /* H3 视频提示词（规范学自 shuohao-skills/novel-storyboard） */
    h3ShotDesc: h3ShotDesc,
    h3Prompt: h3Prompt,
    h3PromptDefault: h3PromptDefault,
    genericRole: genericRole,
    SHOT_CRAFT: SHOT_CRAFT,
    /* 段（一次生成调用） */
    segmentShots: segmentShots,
    h3SegmentPrompt: h3SegmentPrompt,
    LEGAL_ASPECTS: LEGAL_ASPECTS,
    validateShots: validateShots,
    /* 出片端契约适配（comfyui-h3-demo） */
    H3_CONTRACT: H3_CONTRACT,
    h3Frame: h3Frame,
    h3Duration: h3Duration,
    h3Item: h3Item,
    h3Preflight: h3Preflight
};

export default Engine;
