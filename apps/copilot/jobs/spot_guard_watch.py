"""K3s 内 Spot Guard 巡检 · 发 126 邮件（CronJob）

集群内运行：K8s 可达性 + 阿里云 ECS 云真值 + SMTP。
整集群 ECS 被释放时 CronJob 无法执行，须保留本机 cron 或外部探活作补充。

[Ref: diting-doc/03_/_共享规约/31_Spot计费感知与巡检规约.md]
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import httpx
import yaml


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _load_prefs() -> dict[str, Any]:
    path = os.getenv("SPOT_GUARD_PREFS_FILE", "/config/spot-billing-prefs.yaml")
    if Path(path).is_file():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {}


def _aliyun_sign(params: dict[str, str], secret: str, method: str = "GET") -> str:
    import hmac
    import hashlib
    import base64

    sorted_params = sorted(params.items())
    canonical = "&".join(f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted_params)
    string_to_sign = f"{method}&{quote('/', safe='~')}&{quote(canonical, safe='~')}"
    digest = hmac.new((secret + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _aliyun_rpc(
    *,
    action: str,
    region: str,
    access_key: str,
    secret_key: str,
    extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "Action": action,
        "Format": "JSON",
        "Version": "2014-05-26",
        "AccessKeyId": access_key,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "RegionId": region,
    }
    if extra:
        params.update(extra)
    params["Signature"] = _aliyun_sign(params, secret_key)
    url = f"https://ecs.{region}.aliyuncs.com/?{urlencode(params)}"
    with urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _find_instance(region: str, name_substr: str, ak: str, sk: str) -> dict[str, Any] | None:
    try:
        data = _aliyun_rpc(
            action="DescribeInstances",
            region=region,
            access_key=ak,
            secret_key=sk,
            extra={"PageSize": "100"},
        )
    except Exception:
        return None
    for inst in data.get("Instances", {}).get("Instance") or []:
        name = inst.get("InstanceName") or ""
        if name_substr in name:
            return inst
    return None


def _spot_available(region: str, instance_type: str, ak: str, sk: str) -> bool:
    try:
        data = _aliyun_rpc(
            action="DescribeAvailableResource",
            region=region,
            access_key=ak,
            secret_key=sk,
            extra={
                "DestinationResource": "InstanceType",
                "InstanceType": instance_type,
                "SpotStrategy": "SpotAsPriceGo",
            },
        )
    except Exception:
        return False
    for zone in data.get("AvailableZones", {}).get("AvailableZone") or []:
        for ar in zone.get("AvailableResources", {}).get("AvailableResource") or []:
            for sr in ar.get("SupportedResources", {}).get("SupportedResource") or []:
                if sr.get("Status") == "Available":
                    return True
    return False


def _k8s_ok() -> bool:
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not Path(token_path).is_file():
        return False
    token = Path(token_path).read_text(encoding="utf-8").strip()
    host = os.getenv("KUBERNETES_SERVICE_HOST", "")
    port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    if not host:
        return False
    url = f"https://{host}:{port}/readyz"
    try:
        with httpx.Client(verify=False, timeout=10.0) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {token}"})
            return r.status_code == 200
    except Exception:
        return False


def _proxy_ok(host: str, port: int, user: str, password: str) -> bool:
    if not host:
        return False
    proxy_url = f"http://{user}:{password}@{host}:{port}"
    try:
        with httpx.Client(proxy=proxy_url, timeout=8.0) as client:
            r = client.get("http://connectivitycheck.gstatic.com/generate_204")
            return r.status_code in (204, 200)
    except Exception:
        try:
            with httpx.Client(proxy=proxy_url, timeout=8.0) as client:
                r = client.get("https://api.anthropic.com/", follow_redirects=True)
                return r.status_code < 500
        except Exception:
            return False


def _email_to_addr(prefs: dict[str, Any]) -> str:
    email_cfg = prefs.get("watch_email") or {}
    return (
        os.getenv("SPOT_WATCH_EMAIL_TO")
        or os.getenv("SPOT_GUARD_EMAIL_TO")
        or str(email_cfg.get("to") or "")
        or os.getenv("COPILOT_SMTP_USERNAME", "")
    )


def _send_email(subject: str, text: str, html: str, prefs: dict[str, Any]) -> bool:
    host = os.getenv("COPILOT_SMTP_HOST", "smtp.126.com")
    port = int(os.getenv("COPILOT_SMTP_PORT", "465"))
    use_ssl = os.getenv("COPILOT_SMTP_USE_SSL", "true").lower() in ("1", "true", "yes")
    username = os.getenv("COPILOT_SMTP_USERNAME", "")
    password = os.getenv("COPILOT_SMTP_PASSWORD", "")
    sender = os.getenv("COPILOT_SMTP_FROM") or username
    to_addr = _email_to_addr(prefs)
    if not username or not password or not to_addr:
        print("⚠️  [spot-guard-incluster] 缺 SMTP 凭证或收件地址", file=sys.stderr)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(username, password)
                smtp.send_message(msg)
        print(f"✅ [spot-guard-incluster] 邮件已发送至 {to_addr}")
        return True
    except Exception as exc:
        print(f"❌ [spot-guard-incluster] 发信失败: {exc!r}", file=sys.stderr)
        return False


def _conclusion_emoji(code: str) -> str:
    return {
        "HEALTHY": "✅",
        "PREEMPTED_LIKELY": "⚠️",
        "UNEXPECTED_RELEASE": "❌",
        "SPOT_OPPORTUNITY": "💡",
        "BALANCE_BLOCK": "💰",
    }.get(code, "ℹ️")


def run() -> int:
    prefs = _load_prefs()
    email_cfg = prefs.get("watch_email") or {}
    if email_cfg.get("enabled") is False:
        print("ℹ️  watch_email.enabled=false · 跳过")
        return 0

    ak = os.getenv("ALICLOUD_ACCESS_KEY") or os.getenv("ALIYUN_AK", "")
    sk = os.getenv("ALICLOUD_SECRET_KEY") or os.getenv("ALIYUN_SK", "")
    if not ak or not sk:
        print("❌ 缺 ALICLOUD_ACCESS_KEY/SECRET", file=sys.stderr)
        return 1

    stacks = prefs.get("stacks") or {}
    proxy = stacks.get("proxy") or {}
    base = stacks.get("base") or {}

    proxy_region = proxy.get("region", "ap-southeast-1")
    base_region = base.get("region", "cn-hongkong")
    proxy_env = proxy.get("env", "sg-proxy")
    base_env = base.get("env", "prod")

    k8s_ok = _k8s_ok()
    proxy_inst = _find_instance(proxy_region, f"-proxy-{proxy_env}", ak, sk)
    base_inst = _find_instance(base_region, f"-base-{base_env}", ak, sk)

    proxy_host = os.getenv("SPOT_GUARD_PROXY_HOST", "")
    proxy_port = int(os.getenv("SPOT_GUARD_PROXY_PORT", "3128"))
    proxy_user = os.getenv("SPOT_GUARD_PROXY_USER", "ditingproxy")
    proxy_pass = os.getenv("SPOT_GUARD_PROXY_PASSWORD") or os.getenv("ANTHROPIC_PROXY_PASSWORD", "")
    if proxy_inst and not proxy_host:
        proxy_host = (proxy_inst.get("EipAddress") or {}).get("IpAddress") or ""

    proxy_ok = _proxy_ok(proxy_host, proxy_port, proxy_user, proxy_pass) if proxy_host else bool(proxy_inst)

    conclusion = "HEALTHY"
    detail = f"k8s={k8s_ok} proxy_cloud={bool(proxy_inst)} base_cloud={bool(base_inst)} proxy_ok={proxy_ok}"
    action = ""

    if k8s_ok and not base_inst:
        conclusion = "UNEXPECTED_RELEASE"
        detail = "K8s 可达但香港 base ECS 云上不存在"
        action = "make deploy diting prod（本机）"
    elif k8s_ok and not proxy_ok and not proxy_inst:
        if not _spot_available(proxy_region, proxy.get("instance_type", ""), ak, sk):
            conclusion = "PREEMPTED_LIKELY"
            detail = "proxy 不可用且 Spot 无货 · 疑似抢占"
            action = "make redeploy-prod-ondemand-fallback（本机）"
        else:
            conclusion = "UNEXPECTED_RELEASE"
            detail = "proxy 应可用但云上无实例"
            action = "make deploy diting prod（本机）"
    elif k8s_ok and base_inst and _spot_available(
        base_region, base.get("instance_type", ""), ak, sk
    ):
        conclusion = "SPOT_OPPORTUNITY"
        detail = "集群运行中 · 香港 Spot 有货 · 可切换竞价"
        action = "make switch-stack-billing STACK=base BILLING=spot INTERACTIVE=1（本机）"

    send_healthy = email_cfg.get("send_on_healthy", True)
    if conclusion == "HEALTHY" and not send_healthy:
        print(f"HEALTHY · {detail}")
        return 0

    emoji = _conclusion_emoji(conclusion)
    now = _utc_now()
    subject = f"[Diting Spot Guard · 集群内] {emoji} {conclusion} · {now}"
    text = (
        f"Diting Spot Guard（K3s CronJob 集群内巡检）\n\n"
        f"结论: {conclusion}\n详情: {detail}\n建议: {action or '无'}\n时间: {now}\n\n"
        f"说明: 整集群 ECS 释放时本 CronJob 无法运行，请保留本机 make cluster-spot-watch CRON=1 作补充。\n"
    )
    html = f"<html><body><h2>{emoji} {conclusion}</h2><p>{detail}</p><p>{action or '无'}</p><p>{now}</p></body></html>"

    print(f"结论={conclusion} · {detail}")
    ok = _send_email(subject, text, html, prefs)
    if conclusion != "HEALTHY":
        return 2 if not ok else 2
    return 0 if ok else 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
