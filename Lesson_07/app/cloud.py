"""Safe direct-link downloads for the optional cloud import entry point."""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .config import AUDIO_LIMIT


def normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username:
        raise ValueError("Укажите публичную HTTPS-ссылку на скачивание видео.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("В ссылке указан некорректный порт.") from error
    if port not in (None, 443):
        raise ValueError("Ссылка должна использовать стандартный HTTPS-порт.")
    host = parsed.hostname.lower().rstrip(".")
    url_host = f"[{host}]" if ":" in host else host
    netloc = url_host if port is None else f"{url_host}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def resolve_share_url(value: str, yandex_href: str | None = None) -> str:
    """Turn supported public share pages into their provider download URLs."""
    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    if host == "drive.google.com":
        match = re.fullmatch(r"/file/d/([A-Za-z0-9_-]+)/[^/]+/?", parsed.path)
        if match:
            query = urlencode(
                {"id": match.group(1), "export": "download", "confirm": "t"}
            )
            return f"https://drive.usercontent.google.com/download?{query}"
    if host in {"disk.yandex.ru", "yadi.sk"} and yandex_href:
        return normalize_url(yandex_href)
    return normalized


def _is_yandex_share(url: str) -> bool:
    return (urlsplit(url).hostname or "") in {"disk.yandex.ru", "yadi.sk"}


def _require_public_host(url: str):
    host = urlsplit(url).hostname
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise ValueError("Не удалось найти сервер по указанной ссылке.") from error
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("Разрешены только публичные облачные HTTPS-ссылки.")


def _filename(response: httpx.Response, url: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    name = ""
    for part in disposition.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() in ("filename", "filename*"):
            name = value.strip(' \"').removeprefix("UTF-8''")
            break
    name = Path(unquote(name or urlsplit(url).path).split("/")[-1]).name
    suffix = Path(name).suffix.lower()
    if suffix not in (".webm", ".mp4"):
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        suffix = {"video/webm": ".webm", "video/mp4": ".mp4"}.get(content_type, "")
        if not suffix:
            raise ValueError(
                "Ссылка должна вести на файл WebM или MP4, а не на страницу просмотра."
            )
        name = (Path(name).stem or "Облачная запись") + suffix
    return name


def download(url: str, target_dir: Path) -> tuple[Path, str, str]:
    normalized = normalize_url(url)
    current = resolve_share_url(normalized)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with httpx.Client(
        timeout=httpx.Timeout(60, connect=15),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        if _is_yandex_share(normalized):
            resolver = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
            _require_public_host(resolver)
            response = client.get(
                resolver,
                params={"public_key": normalized},
                headers={"Accept": "application/json"},
            )
            if response.status_code >= 400:
                raise ValueError(
                    "Yandex Disk не выдал публичную ссылку на скачивание файла."
                )
            try:
                href = response.json()["href"]
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "Yandex Disk вернул некорректную ссылку на скачивание."
                ) from error
            current = resolve_share_url(normalized, href)
        for _ in range(4):
            _require_public_host(current)
            with client.stream(
                "GET",
                current,
                headers={"Accept": "video/webm,video/mp4,application/octet-stream"},
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Облачный сервис вернул перенаправление без адреса.")
                    current = normalize_url(urljoin(current, location))
                    continue
                if response.status_code in (401, 403):
                    raise ValueError(
                        "Сервис требует авторизацию. Скачайте файл из облака и загрузите его вручную."
                    )
                if response.status_code >= 400:
                    raise ValueError(f"Не удалось скачать файл из облака: HTTP {response.status_code}.")
                name = _filename(response, current)
                path = target_dir / ("incoming" + Path(name).suffix.lower())
                total = 0
                try:
                    with path.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            total += len(chunk)
                            if total > AUDIO_LIMIT:
                                raise ValueError("Видео превышает предел 500 МБ.")
                            output.write(chunk)
                    if not total:
                        raise ValueError("Облачный файл пуст.")
                    return path, name, normalized
                except BaseException:
                    path.unlink(missing_ok=True)
                    raise
    raise ValueError("Облачный сервис выполнил слишком много перенаправлений.")
