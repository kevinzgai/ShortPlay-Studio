#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接用 ComfyUI API 跑一遍 Flux.1-schnell 文生图，验证四件模型齐全可用。"""
import json
import random
import time
import urllib.request

HOST = "http://127.0.0.1:8188"
PROMPT = "a cinematic still of a red paper lantern glowing in a rainy Shanghai alley at night, shallow depth of field, film grain"
W, H, STEPS, BATCH = 1024, 1024, 4, 1
SEED = random.randint(1, 2**31)


def wf():
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "flux", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": 0}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": W, "height": H, "batch_size": BATCH}},
        "6": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": STEPS, "denoise": 1}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["9", 0], "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "flux_test"}},
    }


body = json.dumps({"prompt": wf(), "client_id": "flux-test"}).encode()
req = urllib.request.Request(HOST + "/prompt", data=body, headers={"Content-Type": "application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=30) as r:
    pid = json.load(r)["prompt_id"]
print("已提交 prompt_id=%s seed=%s" % (pid, SEED), flush=True)

# 轮询历史
while True:
    time.sleep(3)
    try:
        with urllib.request.urlopen(HOST + "/history/" + pid, timeout=30) as r:
            hist = json.load(r)
    except Exception:
        continue
    if pid in hist:
        h = hist[pid]
        st = h.get("status", {})
        print("状态:", st.get("status_str"), "用时 %.1fs" % (time.time() - t0))
        if st.get("status_str") != "success":
            print(json.dumps(st, ensure_ascii=False)[:1500])
            break
        for node, out in h.get("outputs", {}).items():
            for im in out.get("images", []):
                print("图片:", im.get("filename"), im.get("subfolder"), im.get("type"))
        break
    if time.time() - t0 > 900:
        print("超时")
        break
