"""SSE 事件流：把解析任务的增量事件推给前端。

【为什么留在标准库实现里】
SSE 在 FastAPI 下会换成 StreamingResponse / EventSourceResponse，
但这 39 行涉及「心跳、断线续传、收尾关连接」三个细节，逐字搬过来最安全。
现在独立成函数，Step C 只需换外层包装，内部逻辑不动。

【为什么不能改成普通 json 响应】
前端靠 EventSource 长连接接进度；一旦返回完整 JSON，界面就只剩「转圈到结束」。
"""

import json
import time

from app.services.parse_task import PARSE_TASKS, parse_task_wait
from app.web.responses import json_response, query_dict


def parse_stream(h):
    """按 seq 增量推事件，任务收尾后关连接；前端断线用 since 续传。"""
    q = query_dict(h)
    tid = q.get("id", "")
    task = PARSE_TASKS.get(tid)
    if not task:
        return json_response(h, {"detail": "任务不存在或已过期"}, 404)
    try:
        since = int(q.get("since") or h.headers.get("Last-Event-ID") or 0)
    except (TypeError, ValueError):
        since = 0
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache, no-transform")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    h.close_connection = True
    h.wfile.flush()
    last_ping = time.time()
    try:
        while True:
            events, over = parse_task_wait(task, since, 2.0)
            for ev in events:
                since = ev["seq"]
                h.wfile.write(("id: %d\ndata: %s\n\n" % (
                    ev["seq"], json.dumps(ev, ensure_ascii=False))).encode("utf-8"))
            if events:
                h.wfile.flush()
                last_ping = time.time()
            elif time.time() - last_ping >= 8:
                h.wfile.write(b": ping\n\n")     # 心跳，防止中间层掐掉空闲连接
                h.wfile.flush()
                last_ping = time.time()
            if over and not events:
                h.wfile.write(b": end\n\n")
                h.wfile.flush()
                break
    except (BrokenPipeError, ConnectionResetError, OSError):
        return
