"""
WOWBOX diagnostics - everything the Status page needs to know about the box.

* Safe logging  : secrets are masked and tracebacks never print variable values.
* Remote logs   : INFO+ log lines are buffered here and shipped to the server
                  with the heartbeat (kept while offline, sent when back online).
* Health state  : network, printer, speaker and system health, collected without
                  touching the printer or interrupting a print job.
"""

import copy
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import timezone

from loguru import logger

AGENT_VERSION = "3.4"
STARTED = time.time()
AUDIO_USER = "wowbox_milab"

_lock = threading.Lock()
_secrets = []

# Shared, thread-safe view of what the agent is doing right now.
STATE = {
    "stage": "idle",
    "stage_detail": "Waiting for photos",
    "job_id": None,
    "last_error": None,
    "server_ok": None,          # None = not polled yet
    "last_poll_ok": None,
    "last_poll_error": None,
    "printer": {"reachable": None, "battery": None, "cover_open": None, "no_paper": None,
                "wrong_sheet": None, "error": None, "checked_at": None, "reachable_at": None},
    "speaker": {"last_test_ok": None, "last_test_at": None},
}


# ─── Safe logging ─────────────────────────────────────────────────────────────

def mask(text):
    text = str(text)
    for secret in _secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class RemoteLogBuffer:
    """Keeps the most recent log lines until the server has acknowledged them."""

    def __init__(self, maxlen=500):
        self._items = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, entry):
        with self._lock:
            self._items.append(entry)

    def peek(self, n=100):
        with self._lock:
            return list(self._items)[:n]

    def drop(self, n):
        with self._lock:
            for _ in range(min(n, len(self._items))):
                self._items.popleft()


REMOTE_LOGS = RemoteLogBuffer()


def _remote_sink(message):
    record = message.record
    text = mask(record["message"])
    exc = record["exception"]
    if exc is not None and exc.type is not None:
        text += f" [{exc.type.__name__}: {mask(exc.value)}]"
    REMOTE_LOGS.add({
        "ts": record["time"].astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        "level": record["level"].name.lower(),
        "message": text,
    })


def setup_logging(*secrets):
    """Replace loguru's defaults: no variable dumps (diagnose=False) and masked secrets."""
    _secrets.extend(s for s in secrets if s)
    logger.remove()
    logger.configure(patcher=lambda record: record.update(message=mask(record["message"])))
    logger.add(sys.stderr, level="DEBUG", backtrace=False, diagnose=False)
    logger.add(_remote_sink, level="INFO", backtrace=False, diagnose=False)


# ─── State updates (called by the agent) ──────────────────────────────────────

def set_stage(stage, detail="", job_id=None):
    with _lock:
        STATE["stage"] = stage
        STATE["stage_detail"] = detail
        STATE["job_id"] = job_id


def set_error(text):
    with _lock:
        STATE["last_error"] = {"message": mask(text), "at": time.time()}


def poll_result(ok, error=None):
    """Returns True if the server-reachable state changed (so the caller can log it once)."""
    with _lock:
        changed = STATE["server_ok"] is not ok
        STATE["server_ok"] = ok
        if ok:
            STATE["last_poll_ok"] = time.time()
            STATE["last_poll_error"] = None
        else:
            STATE["last_poll_error"] = mask(error) if error else None
        return changed


def set_printer(**fields):
    with _lock:
        printer = STATE["printer"]
        printer.update(fields)
        printer["checked_at"] = time.time()
        if fields.get("reachable"):
            printer["reachable_at"] = time.time()


def set_speaker_test(ok):
    with _lock:
        STATE["speaker"]["last_test_ok"] = ok
        STATE["speaker"]["last_test_at"] = time.time()


def printer_reachable():
    with _lock:
        return STATE["printer"]["reachable"]


# ─── Collectors ───────────────────────────────────────────────────────────────

def _run(cmd, timeout=4):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout.strip() if res.returncode == 0 else None
    except Exception:
        return None


def as_audio_user(cmd):
    """Run a command inside the desktop user's PipeWire session (audio lives there)."""
    return ["sudo", "-u", AUDIO_USER, "env", "XDG_RUNTIME_DIR=/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"] + cmd


def _network():
    ssid = signal = None
    out = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])
    if out:
        for line in out.splitlines():
            parts = line.split(":")
            if parts and parts[0] == "yes" and len(parts) >= 3:
                ssid, signal = parts[1], int(parts[-1]) if parts[-1].isdigit() else None
                break
    if ssid is None:
        ssid = _run(["iwgetid", "-r"]) or None
    ips = (_run(["hostname", "-I"]) or "").split()
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        internet = True
    except OSError:
        internet = False
    return {"ssid": ssid, "signal": signal, "ip": ips[0] if ips else None, "internet": internet}


_speaker_cache = {"at": 0, "value": None}


def _speaker():
    """Audio output health (cached 60s; querying PipeWire logs a sudo line each time)."""
    if time.time() - _speaker_cache["at"] < 60 and _speaker_cache["value"]:
        return _speaker_cache["value"]
    info = {"available": False, "sink": None, "volume": None, "muted": None}
    vol = _run(as_audio_user(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
    if vol and "Volume:" in vol:
        info["available"] = True
        try:
            info["volume"] = int(round(float(vol.split()[1]) * 100))
        except (IndexError, ValueError):
            pass
        info["muted"] = "[MUTED]" in vol
        inspect = _run(as_audio_user(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])) or ""
        for line in inspect.splitlines():
            if "node.description" in line:
                info["sink"] = line.split("=", 1)[1].strip().strip('"')
                break
    _speaker_cache.update(at=time.time(), value=info)
    return info


_bt_cache = {"at": 0, "value": None}


def _bluetooth_adapter_up():
    if time.time() - _bt_cache["at"] < 30 and _bt_cache["value"] is not None:
        return _bt_cache["value"]
    out = _run(["hciconfig", "hci0"])
    up = bool(out and "UP RUNNING" in out)
    _bt_cache.update(at=time.time(), value=up)
    return up


def _system():
    info = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            info["cpu_temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        info["cpu_temp"] = None
    try:
        info["load"] = round(os.getloadavg()[0], 2)
    except Exception:
        info["load"] = None
    try:
        info["disk_free_mb"] = int(shutil.disk_usage("/").free / 1024 / 1024)
    except Exception:
        info["disk_free_mb"] = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    info["mem_free_mb"] = int(line.split()[1]) // 1024
                    break
    except Exception:
        info["mem_free_mb"] = None
    return info


def _ago(ts):
    return None if ts is None else int(time.time() - ts)


def build_status(printer_mac, demo_mode, job_active):
    with _lock:
        st = copy.deepcopy(STATE)

    network = _network()
    network.update({
        "server_reachable": st["server_ok"],
        "last_poll_ago_s": _ago(st["last_poll_ok"]),
        "last_poll_error": st["last_poll_error"],
    })

    printer = st["printer"]
    printer.update({
        "mac": printer_mac,
        "adapter_up": _bluetooth_adapter_up(),
        "checked_ago_s": _ago(printer.pop("checked_at")),
        "reachable_ago_s": _ago(printer.pop("reachable_at")),
    })

    speaker = _speaker()
    speaker = dict(speaker, last_test_ok=st["speaker"]["last_test_ok"],
                   last_test_ago_s=_ago(st["speaker"]["last_test_at"]))

    last_error = st["last_error"]
    if last_error:
        last_error = {"message": last_error["message"], "ago_s": _ago(last_error["at"])}

    return {
        "version": AGENT_VERSION,
        "uptime_s": int(time.time() - STARTED),
        "stage": st["stage"],
        "stage_detail": st["stage_detail"],
        "job_id": st["job_id"],
        "job_active": job_active,
        "demo_mode": demo_mode,
        "network": network,
        "printer": printer,
        "speaker": speaker,
        "system": _system(),
        "last_error": last_error,
    }


def invalidate_speaker():
    """Forget the cached speaker info so the next heartbeat reports the new volume."""
    _speaker_cache["at"] = 0
