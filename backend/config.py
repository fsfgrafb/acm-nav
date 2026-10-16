"""配置即页面：区域与卡片使用同一套模型。"""

import ipaddress
import logging
import re
import tomlkit
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def local_path(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    # 同时拦截越界路径和指向目录外的符号链接。
    if not name or "\\" in name or ":" in name or not target.is_relative_to(root.resolve()):
        raise ValueError(f"非法相对路径：{name}")
    return target


def frontend_root(root: Path) -> Path:
    development_build = root / "frontend/dist"
    return development_build if development_build.is_dir() else root / "frontend"


def static_root(root: Path) -> Path:
    deployed_static = root / "static"
    return deployed_static if deployed_static.is_dir() else frontend_root(root)


def reorder_table(table, fields: tuple[str, ...]):
    """Create a TOML table with its known fields in a stable order."""
    ordered = tomlkit.table()
    for field in fields:
        if field in table:
            ordered.add(field, table[field])
    return ordered


def format_document(document):
    """Format the supported configuration schema in a deterministic field order."""
    formatted = tomlkit.document()
    for field in ("server", "appearance", "admin"):
        if field in document:
            formatted.add(field, document[field])

    sections = tomlkit.aot()
    for section in document.get("sections", []):
        ordered_section = reorder_table(section, ("title", "visibility", "width", "columns"))
        items = tomlkit.aot()
        for item in section.get("items", []):
            items.append(
                reorder_table(
                    item, ("name", "type", "url", "uri", "description", "content")
                )
            )
        if items:
            ordered_section.add("items", items)
        sections.append(ordered_section)
    if sections:
        formatted.add("sections", sections)
    return formatted


def leading_comments(content: str) -> str:
    """Keep the file header while rebuilding the schema tables."""
    match = re.match(r"(?:(?:[ \t]*#.*)?\r?\n|[ \t]*\r?\n)*", content)
    return match.group(0) if match else ""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Server(Model):
    host: str = "0.0.0.0"
    port: int = Field(default=80, ge=1, le=65535)


class Appearance(Model):
    title: str = "苏州工学院 ACM 集训队导航"
    kicker: str = "SZUT ACM Team"
    description: str = "校内服务与集训队信息"


class Admin(Model):
    ips: list[str] = Field(default_factory=lambda: ["127.0.0.1"])

    @field_validator("ips")
    @classmethod
    def valid_ips(cls, values):
        try:
            return [str(ipaddress.ip_address(value)) for value in values]
        except ValueError as exc:
            raise ValueError(f"非法设备 IP：{exc}") from exc


class Item(Model):
    name: str = Field(min_length=1)
    uri: str = ""
    description: str = ""
    type: Literal["link", "info", "resource"] = "link"
    url: str = ""
    content: str = ""

    @model_validator(mode="before")
    @classmethod
    def migrate_icon(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            old_icon = values.pop("icon", "")
            values.setdefault("uri", old_icon)
            if values.get("type") == "info" and not values.get("uri"):
                values["uri"] = "info.svg"
        return values

    @model_validator(mode="after")
    def check_content(self):
        parsed = urlsplit(self.url)
        http_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        resource_url = (
            bool(self.url)
            and not parsed.scheme
            and not parsed.netloc
            and "\\" not in self.url
            and all(part not in {"", ".", ".."} for part in parsed.path.split("/"))
        ) or (self.url.startswith("/resources/") and len(self.url) > len("/resources/"))
        if self.type == "link":
            if not http_url:
                raise ValueError("链接必须为有效的 HTTP(S) 地址")
        elif self.type == "resource" and not (http_url or resource_url):
            raise ValueError("资源必须使用 HTTP(S) 地址、资源文件名或 /resources/ 路径")
        elif self.type == "info" and self.url:
            if not (http_url or resource_url):
                raise ValueError("公告文件必须使用 HTTP(S) 地址、资源文件名或 /resources/ 路径")
            if Path(parsed.path).suffix.lower() not in {".md", ".markdown", ".txt"}:
                raise ValueError("公告文件必须是 Markdown 或 TXT 文件")
        return self

    @field_validator("uri")
    @classmethod
    def service_icon(cls, value):
        if not value:
            return value
        if value.startswith("/icons/services/"):
            name = value.removeprefix("/icons/services/")
            if name and all(part not in {"", ".", ".."} for part in name.split("/")):
                return value
        elif value and "/" not in value and "\\" not in value and ":" not in value:
            return value
        raise ValueError("图标必须是 services 下的文件名或 /icons/services/ 路径")


class Section(Model):
    title: str
    width: int = Field(default=2, ge=1, le=12)
    columns: int = Field(default=1, ge=1, le=6)
    visibility: Literal["public", "admin"] = "public"
    items: list[Item] = Field(default_factory=list)

class Config(Model):
    server: Server = Field(default_factory=Server)
    appearance: Appearance = Field(default_factory=Appearance)
    admin: Admin = Field(default_factory=Admin)
    sections: list[Section] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_section_titles(self):
        if len({section.title for section in self.sections}) != len(self.sections):
            raise ValueError("区域 title 不能重复")
        return self

def ensure_config(path: Path):
    if path.exists():
        return
    template = Path(__file__).with_name("default.toml").read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 独占创建，不覆盖部署机器上的配置。
        with path.open("x", encoding="utf-8") as file:
            file.write(template)
    except FileExistsError:
        return
    logging.getLogger("uvicorn.error").info("配置文件不存在，已创建默认配置：%s", path)


class IconLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.base = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "base" and self.base is None and attributes.get("href"):
            self.base = attributes["href"]
        if tag != "link" or self.href:
            return
        if "icon" in (attributes.get("rel") or "").lower().split() and attributes.get("href"):
            self.href = attributes["href"]


def download_icon(url: str, name: str, directory: Path) -> str | None:
    if any(char in name for char in '<>:"/\\|?*') or name in {"", ".", ".."}:
        raise ValueError("自动下载图标时，卡片名称不能包含文件名保留字符")
    request = Request(url, headers={"User-Agent": "acm-nav/1.0"})
    log = logging.getLogger("uvicorn.error")
    final_url = url
    parser = IconLinkParser()
    try:
        with urlopen(request, timeout=5) as response:
            page = response.read(512 * 1024)
            content_type = response.headers.get_content_type()
            final_url = response.url
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser.feed(page.decode("utf-8", errors="ignore"))
    except (OSError, ValueError) as exc:
        log.warning("图标网页读取失败 [%s] %s：%s", name, url, exc)
    candidates = []
    if parser.href:
        candidates.append(urljoin(urljoin(final_url, parser.base or ""), parser.href))
    candidates.append(urljoin(final_url, "/favicon.ico"))
    for icon_url in dict.fromkeys(candidates):
        if urlsplit(icon_url).scheme not in {"http", "https"}:
            continue
        try:
            with urlopen(Request(icon_url, headers={"User-Agent": "acm-nav/1.0"}), timeout=5) as response:
                data = response.read(2 * 1024 * 1024 + 1)
                content_type = response.headers.get_content_type()
                image_url = response.url
            # Cockpit 的 /favicon.ico 可能实际是 PNG，且标记为 text/plain。
            # 优先识别二进制图片签名，避免依赖错误的 MIME 和扩展名。
            for signature, detected_type in (
                (b"\x89PNG\r\n\x1a\n", "image/png"),
                (b"\x00\x00\x01\x00", "image/x-icon"),
                (b"\xff\xd8\xff", "image/jpeg"),
                (b"GIF87a", "image/gif"),
                (b"GIF89a", "image/gif"),
            ):
                if data.startswith(signature):
                    content_type = detected_type
                    break
            if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
                content_type = "image/webp"
            elif data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
                content_type = "image/avif"
            elif re.search(rb"<svg(?:\s|>)", data[:4096]):
                content_type = "image/svg+xml"
            if not data or len(data) > 2 * 1024 * 1024 or not content_type.startswith("image/"):
                raise ValueError(f"无效图标响应：{content_type}，{len(data)} 字节")
            suffix = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico"}.get(content_type)
            if suffix is None:
                suffix = Path(urlsplit(image_url).path).suffix.lower()
                suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".ico"
            filename = name + suffix
            directory.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_bytes(data)
        except (OSError, ValueError) as exc:
            log.warning("图标下载失败 [%s] %s：%s", name, icon_url, exc)
            continue
        log.info("图标下载成功 [%s]：%s", name, filename)
        return filename
    return None


def read_config(path: Path, root: Path | None = None) -> Config:
    original = path.read_text(encoding="utf-8-sig")
    document = tomlkit.parse(original)
    for section in document.get("sections", []):
        section.setdefault("width", 2)
        section.setdefault("columns", 1)
        for item in section.get("items", []):
            # 兼容已有部署，旧 icon 字段自动迁移到 uri。
            if "icon" in item:
                old_icon = item.pop("icon")
                item.setdefault("uri", old_icon)
            match = re.fullmatch(r"\[[^]]*\]\((https?://[^)]+)\)", item.get("url") or "")
            if match:
                item["url"] = match.group(1)
    result = Config.model_validate(document.unwrap())
    for section, validated_section in zip(document.get("sections", []), result.sections):
        for item, validated_item in zip(section.get("items", []), validated_section.items):
            if validated_item.type == "info" and not item.get("uri"):
                item["uri"] = validated_item.uri
    normalized = leading_comments(original) + tomlkit.dumps(format_document(document))
    if normalized != original:
        if path.read_text(encoding="utf-8-sig") != original:
            raise ValueError("配置正在保存，稍后重试")
        path.write_text(normalized, encoding="utf-8")
    return result


def collect_icon_updates(path: Path, root: Path) -> tuple[str, list]:
    """只做网络和图片写入；配置在事件循环中核对版本后提交。"""
    original = path.read_text(encoding="utf-8-sig")
    config = Config.model_validate(tomlkit.parse(original).unwrap())
    jobs = []
    for section_index, section in enumerate(config.sections):
        for item_index, item in enumerate(section.items):
            if item.type == "link" and (not item.uri or Path(item.uri).stem == item.name):
                jobs.append((section_index, item_index, item))

    def fetch(job):
        section_index, item_index, item = job
        try:
            filename = download_icon(item.url, item.name, static_root(root) / "icons/services")
        except (OSError, ValueError) as exc:
            logging.getLogger("uvicorn.error").warning("图标抓取失败 [%s]：%s", item.name, exc)
            filename = None
        return section_index, item_index, filename

    # 相同名称落到同一文件，按顺序抓取，避免并发覆盖导致内容不确定。
    names = [item.name for _, _, item in jobs]
    with ThreadPoolExecutor(max_workers=4 if len(names) == len(set(names)) else 1) as pool:
        return original, list(pool.map(fetch, jobs))


def apply_icon_updates(path: Path, original: str, updates: list) -> str | None:
    if path.read_text(encoding="utf-8-sig") != original:
        return None  # 抓取期间有新编辑，交给下一轮，绝不覆盖用户配置。
    document = tomlkit.parse(original)
    for section_index, item_index, filename in updates:
        item = document["sections"][section_index]["items"][item_index]
        if filename:
            item["uri"] = filename
        else:
            item.pop("uri", None)  # 失败使用 link.svg，旧自动图标不再引用。
    content = leading_comments(original) + tomlkit.dumps(format_document(document))
    if content != original:
        path.write_text(content, encoding="utf-8")
    return content


def load_site(path: Path, root: Path) -> dict:
    return read_config(path, root).model_dump(exclude={"server"})
