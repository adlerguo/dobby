import fnmatch
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import settings
from app.core.errors import ValidationError
from app.models import ComputerUseTarget

DENIED_SCHEMES = {"file", "ftp", "data", "javascript", "chrome", "chrome-extension"}
DENIED_HOSTS = {"localhost", "metadata.google.internal"}
DENIED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


@dataclass(frozen=True)
class UrlPolicyResult:
    allowed: bool
    code: str | None = None
    message: str | None = None
    host: str | None = None


def computer_use_enabled() -> bool:
    return bool(settings.computer_use_enabled)


def ensure_computer_use_enabled() -> None:
    if not computer_use_enabled():
        raise ValidationError(
            code="computer_use_disabled",
            message="浏览器操作模式当前由管理员关闭",
        )


def normalize_domain(domain: str) -> str:
    return domain.strip().lower().removeprefix("http://").removeprefix("https://").strip("/")


def validate_target(target: ComputerUseTarget) -> None:
    if not target.enabled:
        raise ValidationError(code="computer_use_target_disabled", message="目标系统未启用")
    if not target.allowed_domains:
        raise ValidationError(code="computer_use_target_no_domains", message="目标系统未配置允许域名")


def check_url_allowed(url: str, target: ComputerUseTarget) -> UrlPolicyResult:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not scheme or not host:
        return UrlPolicyResult(False, "invalid_url", "URL 格式无效", host or None)
    if scheme not in {"http", "https"} or scheme in DENIED_SCHEMES:
        return UrlPolicyResult(False, "computer_use_scheme_denied", "该 URL 协议不允许使用浏览器操作模式", host)
    host_result = check_host_safe(host)
    if not host_result.allowed:
        return host_result
    normalized_domains = {normalize_domain(domain) for domain in target.allowed_domains}
    if host not in normalized_domains:
        return UrlPolicyResult(False, "computer_use_domain_not_allowed", "目标域名不在白名单内", host)
    for pattern in target.denied_url_patterns or []:
        if pattern and fnmatch.fnmatch(url, pattern):
            return UrlPolicyResult(False, "computer_use_url_denied", "目标 URL 命中拒绝规则", host)
    allowed_patterns = [pattern for pattern in target.allowed_url_patterns or [] if pattern]
    if allowed_patterns and not any(fnmatch.fnmatch(url, pattern) for pattern in allowed_patterns):
        return UrlPolicyResult(False, "computer_use_url_not_allowed", "目标 URL 不在允许路径内", host)
    return UrlPolicyResult(True, host=host)


def check_host_safe(host: str) -> UrlPolicyResult:
    if host in DENIED_HOSTS:
        return UrlPolicyResult(False, "computer_use_host_denied", "该主机默认禁止访问", host)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return UrlPolicyResult(True, host=host)
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip in DENIED_IPS
    ):
        return UrlPolicyResult(False, "computer_use_ip_denied", "该网络地址默认禁止访问", host)
    return UrlPolicyResult(True, host=host)


def require_url_allowed(url: str, target: ComputerUseTarget) -> None:
    result = check_url_allowed(url, target)
    if not result.allowed:
        raise ValidationError(code=result.code or "computer_use_url_denied", message=result.message or "目标 URL 不允许访问")
