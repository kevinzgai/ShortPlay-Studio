"""把 ComfyUI UI 格式工作流(含 subgraph)转成 /prompt API 格式。

用法:
  py scripts/convert_comfy.py <workflow.json> [--out api.json] [--sg 0]
输出一份可直接 POST /prompt 的 {"prompt": {...}} 结构，并打印每个节点摘要。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OI_PATH = os.path.join(HERE, "comfy_object_info_full.json")

CONTROL = {"fixed", "increment", "decrement", "randomize"}
COMPLEX = {
    "IMAGE", "LATENT", "CLIP", "VAE", "MODEL", "CONDITIONING", "AUDIO", "VIDEO",
    "SIGMAS", "NOISE", "GUIDER", "SAMPLER", "MASK", "CLIP_VISION", "UPSCALE_MODEL",
    "CONTROL_NET", "STYLE_MODEL", "GLIGEN", "PHOTOMAKER", "SEGS", "WAV",
}


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def widget_specs(node_type, oi):
    """按 ComfyUI 声明顺序返回 [(name, is_widget)]。"""
    spec = oi.get(node_type, {}).get("input", {})
    out = []
    for group in ("required", "optional"):
        for name, cfg in (spec.get(group) or {}).items():
            t = cfg[0] if isinstance(cfg, (list, tuple)) else cfg
            is_complex = isinstance(t, str) and t in COMPLEX
            out.append((name, not is_complex))
    return out


def consume_widgets(node_type, values, oi):
    """把 widgets_values 线性映射到 widget 名，跳过 control_after_generate 标记。"""
    specs = [(n, w) for n, w in widget_specs(node_type, oi) if w]
    result = {}
    vi = 0
    for name, _ in specs:
        if vi >= len(values):
            break
        result[name] = values[vi]
        vi += 1
        if vi < len(values) and isinstance(values[vi], str) and values[vi] in CONTROL:
            vi += 1
    # 兜底：节点未在 object_info 中登记时，按位置编号
    if not specs:
        for i, v in enumerate(values):
            result["w%d" % i] = v
    return result


def convert(wf, sg_index=0, external=None):
    external = external or {}
    sg = wf["definitions"]["subgraphs"][sg_index]
    nodes = {n["id"]: n for n in sg["nodes"]}
    links = {l["id"]: l for l in sg["links"]}
    sub_in = sg["inputs"]
    oi = load_json(OI_PATH)

    prompt = {}
    for nid, node in sorted(nodes.items()):
        ntype = node["type"]
        if node.get("mode") == 4:
            raise SystemExit("节点 %s(%s) 处于 bypass 模式，需要先在工作流里启用" % (nid, ntype))
        if node.get("mode") == 2:
            continue
        inputs = {}
        for name, value in consume_widgets(ntype, node.get("widgets_values") or [], oi).items():
            inputs[name] = value
        for slot, inp in enumerate(node.get("inputs") or []):
            if inp.get("link") is None:
                continue
            link = links[inp["link"]]
            origin = link["origin_id"]
            if origin == -10:
                key = sub_in[link["origin_slot"]]["name"]
                if key in external:
                    inputs[inp["name"]] = external[key]
                # 未注入时保留节点自身 widgets_values 的默认值，不丢参数
            else:
                inputs[inp["name"]] = [str(origin), link["origin_slot"]]
        prompt[str(nid)] = {"class_type": ntype, "inputs": inputs,
                            "_meta": {"title": node.get("title") or ntype}}
    return sg, prompt


def main():
    wf_path = sys.argv[1]
    wf = load_json(wf_path)
    sg_index = 0
    if "--sg" in sys.argv:
        sg_index = int(sys.argv[sys.argv.index("--sg") + 1])
    sg, prompt = convert(wf, sg_index)

    for nid, item in sorted(prompt.items(), key=lambda kv: int(kv[0])):
        brief = {}
        for k, v in item["inputs"].items():
            if isinstance(v, list):
                brief[k] = "->%s[%s]" % (v[0], v[1])
            else:
                s = str(v)
                brief[k] = s[:40] + ("..." if len(s) > 40 else "")
        print("%-4s %-28s %s" % (nid, item["class_type"], json.dumps(brief, ensure_ascii=False)))

    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump({"prompt": prompt}, f, ensure_ascii=False, indent=1)
        print("written:", out)


if __name__ == "__main__":
    main()
