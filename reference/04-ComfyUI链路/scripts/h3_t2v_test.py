"""提交 MiniMax H3 t2v 到本地 ComfyUI 并等待结果。用于验证链路，不是最终交付。"""
import io
import json
import sys
import time
import urllib.request
import uuid

HOST = "http://127.0.0.1:8188"


def post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(HOST + path, timeout=30) as r:
        return json.loads(r.read())


def build(prompt, width, height, length, steps, seed=1):
    return {
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "13": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": ["6", 0], "conditioning": ["104", 0]}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["15", 0], "guider": ["16", 0], "sampler": ["17", 0], "sigmas": ["9", 0], "latent_image": ["104", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["23", 0], "fps": 24}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": "toonflow/h3_t2v", "format": "auto", "codec": "auto"}},
    }


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "a red fox running through snow, cinematic"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 512
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 896
    length = int(sys.argv[4]) if len(sys.argv) > 4 else 56
    steps = int(sys.argv[5]) if len(sys.argv) > 5 else 20

    client_id = str(uuid.uuid4())
    try:
        res = post("/prompt", {"prompt": build(prompt, width, height, length, steps), "client_id": client_id})
    except urllib.error.HTTPError as e:
        print("提交失败:", e.code)
        print(e.read().decode("utf-8", "ignore")[:3000])
        return 1
    pid = res["prompt_id"]
    print("已提交 prompt_id =", pid, "节点数 =", len(res.get("prompt", {})))
    start = time.time()
    while True:
        time.sleep(5)
        hist = get("/history/" + pid)
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            print("状态:", status.get("status_str"), "完成:", status.get("completed"))
            if status.get("status_str") == "error":
                for m in status.get("messages", []):
                    if m[0] == "execution_error":
                        print(json.dumps(m[1], ensure_ascii=False)[:2000])
                return 1
            outs = entry.get("outputs", {})
            print("输出:", json.dumps(outs, ensure_ascii=False)[:1500])
            print("耗时: %.1f 秒" % (time.time() - start))
            return 0
        el = time.time() - start
        if el > 1800:
            print("超时")
            return 1
        if int(el) % 30 < 5:
            q = get("/queue")
            print("  ...%.0fs 运行中=%d 排队=%d" % (el, len(q.get("queue_running", [])), len(q.get("queue_pending", []))))


if __name__ == "__main__":
    sys.exit(main())
