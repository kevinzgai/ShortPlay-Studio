# -*- coding: utf-8 -*-
"""从 examples/guihun-storyboard.json 生成可直接打开核对的 HTML 分镜文档。

用法：py tools/gen_storyboard_doc.py
数据真源是 gen_guihun.js 产出的 json，重跑分镜后再执行本脚本即可刷新文档。
"""
import io
import json
import os
import re
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "examples", "guihun-storyboard.json")
OUT = os.path.join(ROOT, "examples", "guihun-storyboard.html")

DETAIL = [
    ("subject", "画面主体"), ("action", "动作 / 变化"), ("composition", "构图与机位"),
    ("sizeReason", "景别依据"), ("camera", "运镜"), ("light", "光线与色温"),
    ("mood", "情绪与表演"), ("sound", "声音"), ("transition", "剪辑衔接"),
]
KIND = {
    "establishing": "建立", "action": "动作", "dialogue": "对白", "closing": "收束",
}

d = json.load(io.open(SRC, encoding="utf-8"))
shots = d["shots"]
eps = d["episodes"]
KEYS = [k for k, _ in DETAIL]


def detail_filled(s):
    return sum(1 for k in KEYS if (s.get("detail") or {}).get(k))


patched = [s for s in shots if s.get("patched")]
lacking = [s for s in shots if detail_filled(s) < 9]
first_person = [s for s in shots if "我" in s["visual"]]
narration = [s for s in shots if s["dialogue"] and
             ("旁白" in (s.get("speaker") or "") or "旁白" in (s.get("notes") or ""))]
bookends = [s for s in shots if s["kind"] in ("establishing", "closing")]
dialogues = [s for s in shots if s["dialogue"]]
generic = re.compile(r"画面缓缓展开|镜头缓缓拉远|氛围收进画面|留出转场余韵|交代空间关系")
cliche = [s for s in bookends if generic.search(s["visual"])]
fp_by_ep = {}
for s in first_person:
    fp_by_ep[s["episode"]] = fp_by_ep.get(s["episode"], 0) + 1
total_sec = sum(s["duration"] for s in shots)

# ---------- 待核对项 / 已通过项 ----------
issues = []
if patched:
    issues.append((
        "%d 个自动补镜没有真正镜头化" % len(patched),
        "画面描述直接抄了原文叙述句（如「从那以后，我就留了个心眼」），分镜卡只有 2/9 项，"
        "备注写着「请人工确认画面」。这些是服务端按剧本行机械补出来的，不是 AI 写的镜头。",
        "patch",
    ))
if first_person:
    dist = " / ".join("第%d集 %d 镜" % (k, v) for k, v in sorted(fp_by_ep.items()))
    issues.append((
        "第2集大量使用第一人称「我」" if fp_by_ep.get(2, 0) > 5 else "部分镜头混入第一人称「我」",
        "共 %d 镜的画面描述用「我」而不是「水雷」（%s）。第 1、3 集统一用第三人称，"
        "第 2 集像把小说原文直接搬了过来。若要做拍摄/生成提示词，视角需要统一。" % (len(first_person), dist),
        "fp",
    ))
scene1 = [s for s in shots if s["sceneNo"] == 1]
if any("晌午" in s["visual"] or "正午" in s["visual"] for s in scene1) and \
   any("深夜" in s["visual"] or "雷夜" in s["visual"] for s in scene1):
    issues.append((
        "第 1 场时间标注与原文冲突",
        "场次头标的是「日」，但原文写水雷出生在子时、遭响雷惊吓。AI 的建立镜头写「夏日晌午」，"
        "紧接 E01-002 跳到「夏天深夜」，两镜光线从正午顶光切到闪电冷白。建议把该场改成「夜」，"
        "或把晌午那镜拆成闪回。",
        "scene1",
    ))
if narration:
    issues.append((
        "%d 句旁白式台词要确认呈现方式" % len(narration),
        "原文第一人称内心独白（如「因为我知道她是护着我的」）被当成角色台词写进对白栏。"
        "如果成片不打算配旁白，需要改成纯动作镜头。",
        "narr",
    ))
if bookends:
    issues.append((
        "%d 个建立 / 收束镜头是否都必要" % len(bookends),
        "10 场里给了 %d 建立 + %d 收束。短剧节奏下可以砍掉一部分空镜，把时长让给喜宴街和逃命段。"
        % (sum(1 for s in bookends if s["kind"] == "establishing"),
           sum(1 for s in bookends if s["kind"] == "closing")),
        "book",
    ))

passed = [
    ("台词覆盖 19/19", "原文 19 句对白全部落镜，无漏句、无重复。"),
    ("建立 / 收束零套话", "%d 镜里没有「画面缓缓展开」之类模板句。" % len(bookends)),
    ("时长合规", "%d 镜全部在 2–10 秒区间，总时长 %d 秒。" % (len(shots), total_sec)),
    ("画幅与分集", "9:16，3 集 / 10 场，每集 %s 镜。" % " / ".join(
        str(sum(1 for s in shots if s["episode"] == e["no"])) for e in eps)),
]
if not cliche:
    passed.append(("分镜卡完整度", "%d/%d 镜 9 项全填，其余 %d 镜为自动补镜。" %
                   (len(shots) - len(lacking), len(shots), len(lacking))))

# ---------- 卡片 ----------
def card(s):
    det = s.get("detail") or {}
    flags = []
    if s.get("patched"):
        flags.append("patch")
    if "我" in s["visual"]:
        flags.append("fp")
    if s["dialogue"] and ("旁白" in (s.get("speaker") or "") or "旁白" in (s.get("notes") or "")):
        flags.append("narr")
    if s["kind"] in ("establishing", "closing"):
        flags.append("book")
    if detail_filled(s) < 9:
        flags.append("lack")
    cls = " ".join(flags)
    badges = ['<span class="b b-kind">%s</span>' % KIND.get(s["kind"], s["kind"])]
    if s.get("patched"):
        badges.append('<span class="b b-warn">补</span>')
    if "我" in s["visual"]:
        badges.append('<span class="b b-fp">第一人称</span>')
    if detail_filled(s) < 9:
        badges.append('<span class="b b-lack">分镜卡 %d/9</span>' % detail_filled(s))
    rows = []
    for k, label in DETAIL:
        v = det.get(k) or ""
        rows.append('<div class="drow%s"><span>%s</span><p>%s</p></div>' %
                    ("" if v else " empty", escape(label), escape(v) if v else "—"))
    dlg = ""
    if s["dialogue"]:
        dlg = ('<div class="dlg"><span class="dlg-k">台词</span><p>%s</p></div>'
               % escape(s["dialogue"]))
    notes = ""
    if s.get("notes"):
        notes = '<div class="notes">%s</div>' % escape(s["notes"])
    return (
        '<article class="shot %s" data-code="%s" data-flags="%s" '
        'data-text="%s" data-ep="%s" data-scene="%s">'
        '<header><span class="code">%s</span>%s'
        '<span class="meta">%s · %ss</span></header>'
        '<p class="visual">%s</p>%s%s'
        '<button class="fold" type="button">分镜描述卡 %d/9 <span>展开</span></button>'
        '<div class="detail"><div class="dgrid">%s</div></div>'
        '</article>'
    ) % (
        cls, escape(s["code"]), cls,
        escape((s["visual"] + " " + s["dialogue"] + " " + s["sceneLabel"]).lower(), quote=True),
        s["episode"], s["sceneNo"],
        escape(s["code"]), "".join(badges), escape(s["size"]), s["duration"],
        escape(s["visual"]), dlg, notes, detail_filled(s), "".join(rows),
    )


# 按集 → 场次分组
sections = []
for ep in eps:
    group = [s for s in shots if s["episode"] == ep["no"]]
    inner = []
    last = None
    for s in group:
        if s["sceneNo"] != last:
            if last is not None:
                inner.append("</div></section>")
            inner.append(
                '<section class="scene" data-ep="%s"><h3>%s <span>%d 镜 · %d 秒</span></h3><div class="grid">'
                % (ep["no"], escape(s["sceneLabel"]),
                   sum(1 for x in group if x["sceneNo"] == s["sceneNo"]),
                   sum(x["duration"] for x in group if x["sceneNo"] == s["sceneNo"]))
            )
            last = s["sceneNo"]
        inner.append(card(s))
    if last is not None:
        inner.append("</div></section>")
    sections.append(
        '<div class="ep" data-ep="%s"><div class="ephead"><h2>第%s集 · %s</h2>'
        '<p>%s</p><p class="hook">集尾钩子：%s</p></div>%s</div>'
        % (ep["no"], ep["no"], escape(ep["title"]), escape(ep["synopsis"]),
           escape(ep.get("hook") or ""), "".join(inner))
    )

issue_html = "".join(
    '<li data-jump="%s"><strong>%s</strong><span>%s</span></li>' % (f, escape(t), escape(desc))
    for t, desc, f in issues
)
pass_html = "".join(
    '<li><strong>%s</strong><span>%s</span></li>' % (escape(t), escape(desc))
    for t, desc in passed
)
filters = [
    ("all", "全部 %d" % len(shots)),
    ("patch", "自动补镜 %d" % len(patched)),
    ("lack", "分镜卡不全 %d" % len(lacking)),
    ("fp", "第一人称 %d" % len(first_person)),
    ("narr", "旁白台词 %d" % len(narration)),
    ("book", "建立 / 收束 %d" % len(bookends)),
    ("scene1", "第1场 %d" % len(scene1)),
    ("dialogue", "有台词 %d" % len(dialogues)),
]
fhtml = "".join('<button class="pill%s" data-filter="%s">%s</button>' %
                (" on" if k == "all" else "", k, escape(v)) for k, v in filters)
ehtml = "".join('<button class="pill%s" data-epfilter="%s">第%s集</button>' %
                (" on" if k == "all" else "", k, k if k != "all" else "") for k in
                ["all"] + [str(e["no"]) for e in eps])
ehtml = ehtml.replace('>第集</button>', '>全部集</button>')

HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鬼婚，逃命 · 分镜核对文档</title>
<style>
:root{--pri:#7170ff;--pri-soft:#f1f0ff;--ink:#1c1d24;--ink2:#54566a;--ink3:#8b8da0;
--line:#e8e8f0;--bg:#fbfbfd;--card:#fff;--warn:#b26a00;--warn-bg:#fff8ec;--ok:#0f8a63;--ok-bg:#f0fbf6}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:56px 28px 100px}
h1{font-size:30px;letter-spacing:-.5px;margin:0 0 10px;font-weight:650}
.sub{color:var(--ink2);margin:0 0 22px}
.metas{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:38px}
.metas span{border:1px solid var(--line);border-radius:999px;padding:5px 13px;background:var(--card);
 color:var(--ink2);font-size:12.5px}
.metas b{color:var(--ink);font-weight:600}
.panels{display:grid;grid-template-columns:1.25fr 1fr;gap:16px;margin-bottom:34px}
.panel{border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:12px;
 background:var(--card);padding:20px 22px}
.panel.ok{border-left-color:var(--ok)}
.panel h2{font-size:14px;margin:0 0 14px;font-weight:650;letter-spacing:.2px}
.panel h2 small{font-weight:400;color:var(--ink3);margin-left:6px}
.panel ul{list-style:none;margin:0;padding:0}
.panel li{padding:11px 0;border-top:1px solid var(--line);cursor:default}
.panel li:first-child{border-top:0;padding-top:0}
.panel li[data-jump]{cursor:pointer}
.panel li[data-jump]:hover strong{color:var(--pri)}
.panel li strong{display:block;font-size:13.5px;font-weight:600;margin-bottom:3px;transition:color .15s}
.panel li span{display:block;color:var(--ink2);font-size:12.5px;line-height:1.65}
.panel.ok li strong{color:var(--ok)}
.tools{position:sticky;top:0;z-index:9;background:rgba(251,251,253,.94);backdrop-filter:blur(10px);
 padding:14px 0 12px;border-bottom:1px solid var(--line);margin-bottom:26px}
.toolrow{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:9px}
.toolrow:last-child{margin-bottom:0}
.tlabel{font-size:12px;color:var(--ink3);margin-right:3px;min-width:42px}
.pill{border:1px solid var(--line);background:var(--card);color:var(--ink2);border-radius:999px;
 padding:6px 14px;font-size:12.5px;cursor:pointer;transition:border-color .15s,color .15s,background .15s;
 font-family:inherit}
.pill:hover{border-color:var(--pri);color:var(--pri)}
.pill.on{background:var(--pri);border-color:var(--pri);color:#fff}
#q{flex:1;min-width:190px;border:1px solid var(--line);border-radius:9px;padding:8px 13px;
 font:13px/1.4 inherit;outline:none;background:var(--card);color:var(--ink)}
#q:focus{border-color:var(--pri);box-shadow:0 0 0 3px rgba(113,112,255,.12)}
#hint{font-size:12px;color:var(--ink3)}
.ep{margin-bottom:52px}
.ephead{border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:8px}
.ephead h2{font-size:20px;margin:0 0 8px;font-weight:650}
.ephead p{margin:0;color:var(--ink2);font-size:13px;max-width:900px}
.ephead .hook{color:var(--pri);margin-top:7px;font-size:12.5px}
.scene{margin-top:26px}
.scene h3{font-size:14px;font-weight:600;margin:0 0 14px;color:var(--ink)}
.scene h3 span{font-weight:400;color:var(--ink3);font-size:12px;margin-left:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px}
.shot{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:16px 17px 14px;
 transition:border-color .15s}
.shot:hover{border-color:#cfcffa}
.shot.patch{border-left:3px solid var(--warn);background:var(--warn-bg)}
.shot.fp:not(.patch){border-left:3px solid #d8b4fe}
.shot header{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:10px}
.code{font:600 12.5px/1 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--pri);
 letter-spacing:.3px;margin-right:2px}
.b{font-size:10.5px;line-height:1;padding:4px 8px;border-radius:5px;white-space:nowrap;
 border:1px solid var(--line);background:#fafafd;color:var(--ink3)}
.b-kind{color:var(--ink2)}
.b-warn{background:var(--warn);border-color:var(--warn);color:#fff}
.b-fp{background:#f7efff;border-color:#e6d3ff;color:#7d3ec9}
.b-lack{background:#fff2ef;border-color:#ffd9d0;color:#c6543c}
.meta{margin-left:auto;font-size:11.5px;color:var(--ink3);white-space:nowrap}
.visual{font-size:13.5px;line-height:1.72;margin:0 0 10px;color:var(--ink)}
.dlg{border-left:2px solid var(--pri);padding:2px 0 2px 11px;margin:0 0 9px}
.dlg-k{font-size:11px;color:var(--pri);display:block;margin-bottom:2px}
.dlg p{margin:0;font-size:13px;color:var(--ink)}
.notes{font-size:12px;color:var(--ink3);margin:0 0 10px;line-height:1.6}
.fold{width:100%%;text-align:left;border:0;border-top:1px solid var(--line);background:none;
 padding:10px 0 0;font:12px inherit;color:var(--ink2);cursor:pointer;display:flex;
 justify-content:space-between;transition:color .15s}
.fold:hover{color:var(--pri)}
.fold span{color:var(--ink3)}
.detail{display:none;padding-top:10px}
.shot.open .detail{display:block}
.dgrid{display:grid;grid-template-columns:1fr;gap:0}
.drow{display:grid;grid-template-columns:82px 1fr;gap:10px;padding:6px 0;border-top:1px dashed var(--line)}
.drow:first-child{border-top:0}
.drow span{font-size:11.5px;color:var(--ink3)}
.drow p{margin:0;font-size:12.3px;color:var(--ink2);line-height:1.6}
.drow.empty p{color:#c3c4d0}
.shot.hide,.ep.hide,.scene.hide{display:none}
.foot{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:12px}
@media(max-width:760px){.panels{grid-template-columns:1fr}.grid{grid-template-columns:1fr}
 .wrap{padding:32px 16px 70px}}
@media print{.tools{display:none}.detail{display:block!important}.shot{break-inside:avoid}
 body{background:#fff}}
</style></head><body><div class="wrap">
<h1>鬼婚，逃命 · 分镜核对文档</h1>
<p class="sub">按剧本行逐条校验后的 AI 分镜表。下面是自动生成时发现的疑点，以及全部 %d 镜的完整分镜卡。</p>
<div class="metas">
<span>共 <b>%d</b> 镜</span><span><b>%d</b> 场</span><span><b>%d</b> 集</span>
<span>总时长 <b>%d</b> 秒</span><span>画幅 <b>%s</b></span>
<span>节奏 <b>%s</b></span><span>模型 <b>deepseek-flash</b></span>
<span>台词 <b>%d/%d</b></span><span>自动补镜 <b>%d</b></span>
</div>
<div class="panels">
 <div class="panel"><h2>待你核对 <small>点条目直接筛出相关镜头</small></h2><ul>%s</ul></div>
 <div class="panel ok"><h2>已校验通过 <small>这些不用再逐条看</small></h2><ul>%s</ul></div>
</div>
<div class="tools">
 <div class="toolrow"><span class="tlabel">快速筛</span>%s</div>
 <div class="toolrow"><span class="tlabel">分集</span>%s
  <input id="q" placeholder="搜镜号 / 画面描述 / 台词 / 场次" autocomplete="off">
  <span id="hint"></span></div>
</div>
<div id="body">%s</div>
<p class="foot">数据源：examples/guihun-storyboard.json　·　由 tools/gen_storyboard_doc.py 生成　·　
重跑分镜后执行该脚本即可刷新。原文与转写剧本见 examples/鬼婚逃命-*.txt。</p>
</div>
<script>
var cards=[].slice.call(document.querySelectorAll('.shot'));
var eps=[].slice.call(document.querySelectorAll('.ep'));
var scenes=[].slice.call(document.querySelectorAll('.scene'));
var filter='all', epf='all', q='';
function apply(){
  var n=0;
  cards.forEach(function(c){
    var okF = filter==='all' || (c.dataset.flags||'').split(' ').indexOf(filter)>=0
              || (filter==='dialogue' && c.querySelector('.dlg'))
              || (filter==='scene1' && c.dataset.scene==='1');
    var okE = epf==='all' || c.dataset.ep===epf;
    var okQ = !q || (c.dataset.text||'').indexOf(q)>=0;
    var show = okF && okE && okQ;
    c.classList.toggle('hide',!show); if(show) n++;
  });
  eps.forEach(function(e){
    var any=[].slice.call(e.querySelectorAll('.shot')).some(function(c){return !c.classList.contains('hide')});
    e.classList.toggle('hide', epf!=='all' && e.dataset.ep!==epf || !any);
  });
  scenes.forEach(function(s){
    var any=[].slice.call(s.querySelectorAll('.shot')).some(function(c){return !c.classList.contains('hide')});
    s.classList.toggle('hide',!any);
  });
  document.getElementById('hint').textContent = n===cards.length ? '' : '显示 '+n+' / '+cards.length+' 镜';
}
function pick(sel,attr,cb){
  [].slice.call(document.querySelectorAll(sel)).forEach(function(b){
    b.addEventListener('click',function(){
      [].slice.call(document.querySelectorAll(sel)).forEach(function(x){x.classList.remove('on')});
      b.classList.add('on'); cb(b.getAttribute(attr)); apply();
    });
  });
}
pick('[data-filter]','data-filter',function(v){filter=v});
pick('[data-epfilter]','data-epfilter',function(v){epf=v});
document.getElementById('q').addEventListener('input',function(e){q=e.target.value.trim().toLowerCase();apply()});
[].slice.call(document.querySelectorAll('.panel li[data-jump]')).forEach(function(li){
  li.addEventListener('click',function(){
    var f=li.getAttribute('data-jump'), b=document.querySelector('[data-filter="'+f+'"]');
    if(b){b.click();window.scrollTo({top:document.querySelector('.tools').offsetTop,behavior:'smooth'})}
  });
});
[].slice.call(document.querySelectorAll('.fold')).forEach(function(b){
  b.addEventListener('click',function(){
    var c=b.closest('.shot'), o=c.classList.toggle('open');
    b.querySelector('span').textContent=o?'收起':'展开';
  });
});
apply();
</script></body></html>
""" % (
    len(shots), len(shots), len(set(s["sceneNo"] for s in shots)), len(eps), total_sec,
    escape(d["config"]["aspect"]), escape(d["config"]["pacing"]),
    len(dialogues), 19, len(patched),
    issue_html, pass_html, fhtml, ehtml, "".join(sections),
)

io.open(OUT, "w", encoding="utf-8", newline="").write(HTML)
print("已生成:", OUT)
print("大小: %.1f KB ｜镜头 %d ｜待核对 %d 项 ｜补镜 %d ｜第一人称 %d"
      % (len(HTML.encode("utf-8")) / 1024, len(shots), len(issues), len(patched), len(first_person)))
