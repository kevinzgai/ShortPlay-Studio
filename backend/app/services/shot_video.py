"""分镜镜头 → 视频（走本地网关 /v1/videos，i2v 为主）。

链路：镜头没有首帧图时，先按 framePrompt 文生一张与视频档位同尺寸的首帧
落 examples/assets/，再以首帧为 image 提交 i2v——保证画面与分镜一致；
首帧失败自动降级 t2v（纯文字生视频）。任务状态进程内保存（同 COMFY_JOBS
口径，只留最近 10 个），产物 mp4 落 backend/outputs/video/ 由 studio 自托管。

网关侧是单线程队列：切换模型有 40–90 秒静默期，stage 会显示「加载模型」。
"""

import json
import re
import random
import threading
import time

from app.paths import ROOT
from app.services import gateway
from app.services.comfy import ASSET_IMG_DIR, ASSET_IMG_NAME, sync_image

VIDEO_DIR = ROOT / "outputs" / "video"
VIDEO_NAME = re.compile(r"^[A-Za-z0-9_.\-]+\.(mp4|webm|mkv|mov)$")

# 档位 → 首帧画幅（宽高都是 16 的倍数，网关出图约束；视频本身 32 的倍数由档位决定）
QUALITY = {"fast": (864, 480), "standard": (1024, 576), "high": (1344, 768)}
DURATION = ("5s", "8s", "10s")

VIDEO_JOBS = {}
VIDEO_LOCK = threading.Lock()
VIDEO_SEQ = [0]

_POLL_INTERVAL = 3.0
_POLL_DEADLINE = 1800  # 网关排队 + 模型切换 + 生成，30 分钟封顶

_DONE_SET = ("succeeded", "completed", "done", "success")
_BAD_SET = ("failed", "error", "cancelled", "canceled", "interrupted")


def _safe_name(stem):
    return re.sub(r"[^A-Za-z0-9_\-]", "", stem or "shot")[:32] or "shot"


def video_start(shot_id, body):
    """提交一个镜头视频任务，立即返回 jobId；后台线程负责首帧 → i2v → 轮询。"""
    if not isinstance(body, dict):
        raise ValueError("请求体要是 JSON 对象")
    motion = str(body.get("motionPrompt") or body.get("prompt") or "").strip()[:32000]
    if not motion:
        raise ValueError("motionPrompt 不能为空")
    frame_prompt = str(body.get("framePrompt") or "").strip()[:4000] or motion[:4000]
    quality = body.get("quality") if body.get("quality") in QUALITY else "standard"
    duration = body.get("duration") if body.get("duration") in DURATION else "5s"
    frame = str(body.get("frameFile") or "").strip()  # 已有首帧（examples/assets/ 名）
    seed = body.get("seed")
    if seed is None:
        seed = random.randint(1, 2 ** 31 - 1)
    elif isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed 必须是整数")

    with VIDEO_LOCK:
        VIDEO_SEQ[0] += 1
        jid = "v%d_%d" % (int(time.time()), VIDEO_SEQ[0])
        job = {"id": jid, "shotId": str(shot_id or "")[:80], "status": "queued",
               "stage": "排队中", "progress": 0, "quality": quality,
               "duration": duration, "frameFile": "", "file": "", "url": "",
               "error": "", "seed": seed, "gwJobId": "",
               "startedAt": time.time(), "finishedAt": 0}
        VIDEO_JOBS[jid] = job
        if len(VIDEO_JOBS) > 10:
            for old in sorted(VIDEO_JOBS, key=lambda k: VIDEO_JOBS[k]["startedAt"])[:-10]:
                VIDEO_JOBS.pop(old, None)
    threading.Thread(target=_worker, args=(jid, frame_prompt, motion, quality,
                                           duration, seed, frame), daemon=True).start()
    return {"jobId": jid, "status": "queued", "quality": quality, "duration": duration}


def _worker(jid, frame_prompt, motion, quality, duration, seed, frame):
    job = VIDEO_JOBS.get(jid)
    try:
        job["status"], job["stage"] = "running", "出首帧"
        if not frame:
            w, h = QUALITY[quality]
            r = sync_image({"prompt": frame_prompt, "width": w, "height": h,
                            "steps": 6, "seed": seed})
            frame = r["filename"]
            job["frameFile"] = "examples/assets/" + frame
        name = str(frame).split("/")[-1]
        if not ASSET_IMG_NAME.match(name):
            raise ValueError("首帧文件名不合法：%s" % name[:60])
        path = ASSET_IMG_DIR / name
        if not path.is_file():
            raise ValueError("首帧不在本地：%s" % name[:60])

        job["stage"] = "提交视频"
        info = gateway.gw_video_start("i2v", motion, image_bytes=path.read_bytes(),
                                      quality=quality, duration=duration, seed=seed)
        gwid = gateway.gw_job_id(info)
        job["gwJobId"] = gwid

        deadline = time.time() + _POLL_DEADLINE
        while time.time() < deadline:
            time.sleep(_POLL_INTERVAL)
            if job.get("status") == "cancelled":
                return
            try:
                j = gateway.gw_job(gwid)
            except Exception:
                continue  # 轮询瞬断不致命，下一拍再试
            job["status"] = str(j.get("status") or "running")
            job["stage"] = str(j.get("stage") or "")
            try:
                job["progress"] = int(j.get("progress") or 0)
            except (TypeError, ValueError):
                pass
            st = job["status"].lower()
            if st in _DONE_SET:
                _finish(jid, gwid, j)
                return
            if st in _BAD_SET:
                job["status"] = "failed"
                job["error"] = str(j.get("error") or j.get("status_msg")
                                   or job["stage"] or "网关任务失败")[:220]
                return
        job["status"], job["error"] = "failed", "等待视频超时（%d 秒）" % _POLL_DEADLINE
    except Exception as exc:
        if job:
            job["status"] = "failed"
            job["error"] = str(exc)[:220]
    finally:
        if job:
            job["finishedAt"] = time.time()
            if job.get("status") == "running":
                job["status"] = "failed"


def _finish(jid, gwid, gw_job):
    """从网关任务的产物列表里取视频文件，下载落盘并换成 studio 自己的 URL。"""
    job = VIDEO_JOBS[jid]
    files = gw_job.get("files") or gw_job.get("outputs") or []
    vname = ""
    for f in files:
        n = f.get("name") or f.get("filename") if isinstance(f, dict) else str(f)
        if n and VIDEO_NAME.search(str(n)):
            vname = str(n)
            break
    if not vname:
        raise RuntimeError("网关任务完成但没有视频产物：%s" % str(files)[:160])
    data = gateway.gw_job_file_bytes(gwid, vname)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    fname = "%s_%s" % (_safe_name(jid), vname.rsplit("/", 1)[-1])
    if not VIDEO_NAME.match(fname):
        raise ValueError("产物文件名不合法：%s" % fname[:80])
    (VIDEO_DIR / fname).write_bytes(data)
    job["file"] = fname
    job["url"] = "/v1/videos/file/" + fname
    job["status"], job["progress"] = "done", 100
    job["stage"] = "完成"


def video_job(jid):
    with VIDEO_LOCK:
        job = VIDEO_JOBS.get(str(jid or ""))
        snap = json.loads(json.dumps(job)) if job else None
    return snap
