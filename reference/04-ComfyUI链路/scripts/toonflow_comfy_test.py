"""Toonflow 本地 ComfyUI 链路实测：Flux 出图 + H3 出视频。
使用与 data/providers/comfyuiFlux.ts、comfyuiH3.ts 相同的工作流结构，
验证 Toonflow 里配置的模型名和 ComfyUI 实际可用性。
"""
import json
import random
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8188"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def flux_workflow(prompt, width, height, steps=4, guidance=0, seed=0, prefix="tf_test"):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "flux", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": guidance}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": steps, "denoise": 1}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["9", 0], "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefix}},
    }


def align_frames(duration):
    """帧数对齐 MiniMax H3 的 17k+5 网格。"""
    frames = max(5, round(duration * 24))
    while frames % 17 != 5:
        frames += 1
    return frames


def h3_workflow(prompt, width, height, length, steps=20, sampler="res_multistep", seed=0, prefix="tf_h3_test"):
    return {
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "13": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": ["6", 0], "conditioning": ["104", 0]}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["15", 0], "guider": ["16", 0], "sampler": ["17", 0], "sigmas": ["9", 0], "latent_image": ["104", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["23", 0], "fps": 24}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    }


def submit_and_wait(wf, label, timeout_s=900):
    t0 = time.time()
    res = post("/prompt", {"prompt": wf, "client_id": "toonflow-tf-test"})
    pid = res.get("prompt_id")
    if not pid:
        print(f"[{label}] 提交失败:", json.dumps(res, ensure_ascii=False)[:600])
        return None
    print(f"[{label}] 已提交 prompt_id={pid}")
    while time.time() - t0 < timeout_s:
        time.sleep(3)
        try:
            h = get(f"/history/{pid}")
        except Exception as e:
            print(f"[{label}] 轮询异常: {e}")
            continue
        if pid in h:
            item = h[pid]
            status = item.get("status", {})
            outs = item.get("outputs", {})
            files = []
            for node_out in outs.values():
                for key in ("images", "gifs", "videos"):
                    for f in node_out.get(key, []) or []:
                        files.append(f)
            print(f"[{label}] 完成 state={status.get('status_str')} 耗时={time.time()-t0:.1f}s")
            for f in files:
                print("   ->", f.get("filename"), f.get("subfolder") or "", f.get("type"))
            if not files:
                print("   无输出文件，status:", json.dumps(status, ensure_ascii=False)[:500])
            return files
    print(f"[{label}] 超时 {timeout_s}s")
    return None


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "flux"
    if what == "flux":
        # 与 Toonflow 9:16 竖屏、1K 档位一致：短边 768，按 9:16 换算并对齐 16
        w, h = 768, 1360
        wf = flux_workflow(
            "3D realistic animation still, vertical portrait, cold cyan night tones, "
            "an old southern Chinese village dirt road at night, fog to the knees, "
            "a young man in a grey worn jacket standing with his back to camera",
            w, h, steps=4, guidance=0, seed=random.randint(1, 10**12), prefix="tf_flux_test",
        )
        submit_and_wait(wf, "FLUX 4step 768x1360")
    elif what == "h3":
        # 2 秒 480P 竖屏：短视频冒烟测试，验证 H3 链路 + 音轨
        length = align_frames(2)
        w, h = 480, 864
        wf = h3_workflow(
            "3D 写实动画，竖屏，冷青夜调，低雾，中式民俗恐怖。上世纪八九十年代南方山村土路，"
            "一个穿灰黑工装夹克的年轻男子背对镜头站在雾里，镜头极缓慢向前推进，纸钱被风掀起，"
            "声音：夜风、纸钱翻动；无对白、无配乐。",
            w, h, length, steps=20, seed=random.randint(1, 10**12), prefix="tf_h3_test",
        )
        print(f"[H3] {w}x{h} length={length} 帧 ({length/24:.2f}s) steps=20")
        submit_and_wait(wf, "H3 20step 480x864", timeout_s=1500)
    else:
        print("unknown target")
