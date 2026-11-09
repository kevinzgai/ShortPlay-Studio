#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用本地 ComfyUI Flux.1-schnell 真实生成分镜起始帧图。

骨架抄自 scripts/gen_flux_test.py（已跑通），工作流节点与模型名保持一致。
用法：python tools/gen_first_frame.py --indices 0,40
产物：examples/first-frames/<镜头编号>.png
"""
import argparse
import json
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "http://127.0.0.1:8188"
SRC = ROOT / "examples" / "guihun-first-frames.json"
OUT = ROOT / "examples" / "first-frames"


def workflow(prompt, w, h, seed):
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "clip_l.safetensors",
                         "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                         "type": "flux", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": 0}},
        "5": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 4, "denoise": 1}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["9", 0],
                          "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "sp_frame"}},
    }


def submit(prompt, w, h, seed):
    body = json.dumps({"prompt": workflow(prompt, w, h, seed),
                       "client_id": "shortplay-first-frame"}).encode()
    req = urllib.request.Request(HOST + "/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["prompt_id"]


def wait(pid, timeout=600):
    t0 = time.time()
    while True:
        time.sleep(2)
        try:
            with urllib.request.urlopen(HOST + "/history/" + pid, timeout=30) as r:
                hist = json.load(r)
        except Exception:
            if time.time() - t0 > timeout:
                raise RuntimeError("等待 ComfyUI 超时")
            continue
        if pid in hist:
            h = hist[pid]
            st = h.get("status", {})
            if st.get("status_str") != "success":
                raise RuntimeError("ComfyUI 生成失败：" + json.dumps(st, ensure_ascii=False)[:600])
            imgs = []
            for _node, out in h.get("outputs", {}).items():
                for im in out.get("images", []):
                    imgs.append(im)
            return imgs
        if time.time() - t0 > timeout:
            raise RuntimeError("等待 ComfyUI 超时")


def download(info, dest):
    q = urllib.parse.urlencode({"filename": info["filename"],
                                "subfolder": info.get("subfolder", ""),
                                "type": info.get("type", "output")})
    with urllib.request.urlopen(HOST + "/view?" + q, timeout=60) as r:
        dest.write_bytes(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="0,40", help="要出图的镜头下标，逗号分隔")
    ap.add_argument("--width", type=int, default=576)
    ap.add_argument("--height", type=int, default=1024)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(SRC.read_text(encoding="utf-8"))
    frames = data["frames"]
    done = []
    for raw in args.indices.split(","):
        i = int(raw.strip())
        if i < 0 or i >= len(frames):
            print("跳过越界下标 %d" % i, flush=True)
            continue
        f = frames[i]
        seed = random.randint(1, 2 ** 31)
        t0 = time.time()
        print("[%s] 提交 Flux，promptEn %d 字符，seed=%d ..." %
              (f["code"], len(f["promptEn"]), seed), flush=True)
        pid = submit(f["promptEn"], args.width, args.height, seed)
        imgs = wait(pid)
        if not imgs:
            print("[%s] 没有拿到图片" % f["code"], flush=True)
            continue
        dest = OUT / (f["code"] + ".png")
        download(imgs[0], dest)
        done.append({"code": f["code"], "file": str(dest), "bytes": dest.stat().st_size,
                     "seconds": round(time.time() - t0, 1), "seed": seed,
                     "promptEn": f["promptEn"], "refAssets": f["refAssets"]})
        print("[%s] 完成 %.1fs → %s (%d bytes)" %
              (f["code"], time.time() - t0, dest, dest.stat().st_size), flush=True)
    (OUT / "manifest.json").write_text(
        json.dumps({"source": "guihun-first-frames.json", "model": "flux1-schnell-fp8",
                    "width": args.width, "height": args.height, "items": done},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("共 %d 张，清单：%s" % (len(done), OUT / "manifest.json"), flush=True)


if __name__ == "__main__":
    main()
