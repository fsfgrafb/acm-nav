"""文件快照 + SSE；访客权限在服务端过滤。"""

import asyncio
import copy
import hashlib
import ipaddress
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import Server, ensure_config, load_site, local_path, read_config

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("uvicorn.error")
NO_CACHE = {"Cache-Control": "no-store"}


def fingerprint(paths: list[Path]) -> tuple:
    # 只读取元数据，大型下载文件也不会反复读入内存。
    entries = []
    for root in paths:
        for path in [root] if not root.is_dir() else root.rglob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    entries.append(
                        (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    )
            except OSError:
                pass  # 上传或替换中的文件留待下一轮。
    return tuple(sorted(entries))


class LiveSite:
    def __init__(self, root: Path, config: Path):
        self.root, self.config = root, config
        self.site = None
        self.error = None
        self.revision = 0
        self.build = ""
        self.changed = asyncio.Condition()

    def refresh(self):
        try:
            self.site = load_site(self.config, self.root)
            self.error = None
        except (ValueError, OSError) as exc:
            # 错误配置不会替换上一份有效内容。
            self.error = str(exc)
            log.warning("配置更新未应用：%s", exc)
        self.revision = time.time_ns()
        output = self.root / "frontend/static"
        self.build = hashlib.sha256(
            repr(
                fingerprint(
                    [
                        output / "index.html",
                        *sorted((output / "assets").rglob("*.js")),
                    ]
                )
            ).encode()
        ).hexdigest()[:16]

    def payload(self, admin=False, current_ip=None):
        site = copy.deepcopy(self.site)
        if site:
            site.pop("admin")  # 名单始终留在服务端。
            site["sections"] = [
                section
                for section in site["sections"]
                if admin or section["visibility"] == "public"
            ]
            # 管理员区域按配置顺序集中在页面底部。
            site["sections"].sort(key=lambda section: section["visibility"] == "admin")
        return {
            "revision": str(self.revision),
            "site": site,
            "stale": bool(self.error),
            "build": self.build,
            "is_admin": admin,
            # 只返回当前请求的连接 IP，管理员名单本身不下发。
            "current_ip": current_ip,
        }

    async def watch(self):
        paths = [self.config, self.root / "frontend/static"]
        previous = await asyncio.to_thread(fingerprint, paths)
        self.refresh()
        while True:
            await asyncio.sleep(0.5)
            current = await asyncio.to_thread(fingerprint, paths)
            if current == previous:
                continue
            # 等到文件连续两次稳定，再发布；兼容编辑器原子保存。
            await asyncio.sleep(0.2)
            stable = await asyncio.to_thread(fingerprint, paths)
            if current != stable:
                continue
            previous = stable
            await asyncio.to_thread(self.refresh)
            async with self.changed:
                self.changed.notify_all()


def create_app(root: Path = ROOT, config: Path | None = None) -> FastAPI:
    config = (
        config
        or Path(os.environ.get("NAVIGATOR_CONFIG", root / "config.toml")).resolve()
    )
    live = LiveSite(root, config)

    @asynccontextmanager
    async def lifespan(app):
        ensure_config(config)
        live.refresh()
        watcher = asyncio.create_task(live.watch())
        yield
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.live = live

    def request_ip(request: Request):
        if not request.client:
            return None
        # proxy_headers=False，始终使用与后端直接建连的对端 IP。
        try:
            return str(ipaddress.ip_address(request.client.host))
        except ValueError:
            return None

    async def payload(request: Request):
        ip = request_ip(request)
        admin = bool(ip and live.site and ip in live.site["admin"]["ips"])
        return live.payload(admin, ip)

    @app.get("/api/site")
    async def site(request: Request):
        return JSONResponse(await payload(request), headers=NO_CACHE)

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            revision = None
            while True:
                # 先检查版本再等待，避免检查和订阅之间漏掉更新。
                async with live.changed:
                    if revision == live.revision:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(live.changed.wait(), 15)
                    revision = live.revision
                # 心跳时也重新检查权限，名单移除无需重新打开网页。
                yield (
                    "data: "
                    + json.dumps(await payload(request), ensure_ascii=False)
                    + "\n\n"
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={**NO_CACHE, "X-Accel-Buffering": "no"},
        )

    def file(directory: Path, name: str):
        try:
            path = local_path(directory, name)
        except ValueError:
            raise HTTPException(404) from None
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path, headers={**NO_CACHE, "X-Content-Type-Options": "nosniff"}
        )

    @app.get("/static/icons/{name:path}")
    async def icon(name: str):
        return file(root / "frontend/static/icons", name)

    @app.get("/site.css")
    async def stylesheet():
        return file(root / "frontend/static", "site.css")

    @app.get("/assets/{name:path}")
    async def asset(name: str):
        return file(root / "frontend/static/assets", name)

    @app.get("/")
    async def index():
        return file(root / "frontend/static", "index.html")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config_path = Path(os.environ.get("NAVIGATOR_CONFIG", ROOT / "config.toml"))
    ensure_config(config_path)
    try:
        settings = read_config(config_path).server
    except (ValueError, OSError):
        # 首次配置损坏时仍启动，修正后自动恢复。
        settings = Server()
    uvicorn.run(
        "backend.main:app", host=settings.host, port=settings.port, proxy_headers=False
    )
