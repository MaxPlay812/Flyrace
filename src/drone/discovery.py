"""ROS topic/service discovery via XML-RPC master API (no rospy needed)."""

from __future__ import annotations
import os
from typing import Dict, List, Optional

from utils.debug_log import log


def discover_ros_info(master_uri: str = "") -> Dict:
    """Query rosmaster for all publishers, subscribers and services.

    Returns:
        ok          — True if master responded
        topics      — sorted list of all topic names
        services    — sorted list of all service names
        clover_ns   — namespace where get_telemetry was found, or None
        error       — error string if ok=False
        uri         — master URI used
    """
    uri = master_uri or os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
    result: Dict = {
        "topics": [],
        "services": [],
        "clover_ns": None,
        "ok": False,
        "error": "",
        "uri": uri,
    }
    try:
        import xmlrpc.client

        code, msg, state = xmlrpc.client.ServerProxy(uri).getSystemState("/discovery")
        if code != 1:
            result["error"] = f"rosmaster: код {code} — {msg}"
            return result
        publishers, subscribers, services = state
        result["topics"] = sorted({t for t, _ in (publishers + subscribers)})
        result["services"] = sorted({s for s, _ in services})
        result["clover_ns"] = _clover_ns(result["services"])
        result["ok"] = True
        log.debug(
            f"discovery: {len(result['topics'])} топиков, "
            f"{len(result['services'])} сервисов, "
            f"ns={result['clover_ns']!r}"
        )
    except Exception as e:
        result["error"] = str(e)
        log.warning(f"discover_ros_info: {e}")
    return result


def _clover_ns(services: List[str]) -> Optional[str]:
    for svc in services:
        if svc.endswith("/get_telemetry"):
            return svc.rsplit("/get_telemetry", 1)[0] or "/"
    return None


def format_ros_report(info: Dict) -> str:
    if not info["ok"]:
        return (
            f"Rosmaster ({info['uri']}) не ответил.\n"
            f"Ошибка: {info['error']}\n\n"
            "Проверьте:\n"
            "  • Подключены к WiFi дрона?\n"
            "  • rosmaster запущен? (шаги 1-3 в Диагностике)\n"
            "  • ROS_MASTER_URI задан верно?"
        )

    lines = [f"ROS Master: {info['uri']}"]
    ns = info["clover_ns"]
    if ns:
        mark = "✓" if ns == "/clover" else "⚠ НЕ /clover!"
        lines.append(f"Clover неймспейс: {ns}  {mark}")
    else:
        lines.append("⚠ clover/get_telemetry НЕ найден ни в одном неймспейсе")

    clover = [
        s
        for s in info["services"]
        if any(
            k in s
            for k in (
                "clover",
                "get_telemetry",
                "navigate",
                "land",
                "set_velocity",
                "aruco",
            )
        )
    ]
    other = [s for s in info["services"] if s not in clover]

    lines.append(f"\nClover-сервисы ({len(clover)}):")
    lines += [f"  {s}" for s in clover[:25]]

    lines.append(f"\nДругие сервисы ({len(other)}):")
    lines += [f"  {s}" for s in other[:20]]
    if len(other) > 20:
        lines.append(f"  … и ещё {len(other) - 20}")

    cam_topics = [
        t for t in info["topics"] if any(k in t for k in ("camera", "image", "video"))
    ]
    lines.append(f"\nТопики камеры ({len(cam_topics)}):")
    lines += [f"  {t}" for t in cam_topics[:10]]

    lines.append(
        f"\nВсего: {len(info['topics'])} топиков, {len(info['services'])} сервисов"
    )
    return "\n".join(lines)
