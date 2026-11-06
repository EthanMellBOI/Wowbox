"""
WOWBOX Agent - Runs on the Raspberry Pi.
Polls the cloud server for new print jobs and sends them to the Canon Ivy 2 printer.

Usage:
    python agent.py

Environment variables (or edit config.py):
    WOWBOX_SERVER  - URL of the cloud server
    AGENT_KEY      - Secret key to authenticate with the server
    PRINTER_MAC    - Bluetooth MAC address of the printer
    POLL_INTERVAL  - Seconds between polls (default: 5)

Status page: every HEARTBEAT_INTERVAL seconds the agent reports its health and new
log lines to the server, so the box can be monitored (and basic actions triggered)
from the web app's /status page without SSH.
"""

import threading
import os, sys, time, tempfile, requests, subprocess, signal
from loguru import logger
from hardware import get_leds

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
from config import SERVER_URL, AGENT_KEY, PRINTER_MAC, POLL_INTERVAL

import diagnostics
# Masks the agent key and disables variable dumps in tracebacks (diagnose=False).
diagnostics.setup_logging(AGENT_KEY)

HEARTBEAT_INTERVAL = 10
DEMO_FILE = '/home/wowbox_milab/.wowbox_demo_mode'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Global flag to prevent keep-alive pings during active print jobs
PRINT_JOB_ACTIVE = False

# Only one Bluetooth conversation with the printer at a time (keep-alive vs. manual check)
PRINTER_LOCK = threading.Lock()

def create_printer():
    from client import ClientThread
    from ivy2 import Ivy2Printer
    Ivy2Printer.client = ClientThread()
    return Ivy2Printer()

def handle_exit(sig, frame):
    logger.info("Agent shutting down... clearing LEDs and Audio.")
    get_leds().off()
    os._exit(0)  # Forces instant clean restart and kills all zombie threads!

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def friendly_printer_error(e):
    """Turn low-level Bluetooth errors into something a human can act on."""
    text = f"{type(e).__name__}: {e}".strip(": ")
    if "rfcomm0" in text or "Host is down" in text or "Failed to open" in text or "Connection" in text:
        return "Printer not reachable - is it switched on, charged and close to the box?"
    if type(e).__name__ == "ReceiveTimeoutError":
        return "Printer connected but did not answer - try switching it off and on"
    return text

def probe_printer():
    """Briefly connect to the printer, read battery/paper/cover and publish it to the Status page.

    Doubles as the keep-awake ping. Returns False if another Bluetooth action is already running.
    """
    if not PRINTER_LOCK.acquire(blocking=False):
        return False
    try:
        was_reachable = diagnostics.printer_reachable()
        try:
            manage_bluetooth(connect=True)
            printer = create_printer()
            printer.connect(PRINTER_MAC)
            printer.set_setting(10)
            error_code, battery, _usb, cover_open, no_paper, wrong_sheet = printer.get_status()
            printer.disconnect()
            diagnostics.set_printer(reachable=True, battery=battery, cover_open=cover_open,
                                    no_paper=no_paper, wrong_sheet=wrong_sheet, error=None)
            logger.debug("Sent keep-awake status ping to Canon Ivy 2.")
            if was_reachable is not True:
                logger.info(f"Printer connected (battery {battery}%)")
            if no_paper:
                logger.warning("Printer is out of paper")
            if cover_open:
                logger.warning("Printer cover is open")
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            reason = friendly_printer_error(e)
            diagnostics.set_printer(reachable=False, error=reason)
            logger.debug(f"Keep-awake ping skipped (printer offline): {e}")
            if was_reachable is not False:
                logger.warning(f"Printer unreachable: {reason}")
        finally:
            if not PRINT_JOB_ACTIVE:
                manage_bluetooth(connect=False)
        return True
    finally:
        PRINTER_LOCK.release()

class PrinterKeepAlive(threading.Thread):
    def __init__(self, mac_address, interval=90):
        super().__init__()
        self.mac_address = mac_address
        self.interval = interval
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        logger.info("Background printer keep-alive thread started.")
        first = True
        while not self.stop_event.is_set():
            # First probe shortly after boot so the Status page is populated quickly
            for _ in range(15 if first else self.interval):
                if self.stop_event.is_set():
                    return
                time.sleep(1)
            first = False

            if PRINT_JOB_ACTIVE:
                logger.debug("Print job active; skipping keep-alive ping.")
                continue

            if os.path.exists(DEMO_FILE):
                continue

            probe_printer()

class SpeakerKeepAlive(threading.Thread):
    def __init__(self, interval=60):
        super().__init__()
        self.interval = interval
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        logger.info("Background speaker keep-alive thread started.")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        silence_path = os.path.join(script_dir, "silence.wav")
        while not self.stop_event.is_set():
            for _ in range(self.interval):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

            if PRINT_JOB_ACTIVE:
                continue

            try:
                subprocess.Popen(
                    ["sudo", "-u", "wowbox_milab", "env", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", "pw-play", silence_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

def manage_bluetooth(connect=True):
    try:
        if connect:
            logger.debug("Initializing Bluetooth...")
            subprocess.run(["hciconfig", "hci0", "sspmode", "0"], check=False)
            subprocess.run(["rfcomm", "release", "all"], check=False)
            subprocess.Popen(["rfcomm", "connect", "hci0", PRINTER_MAC, "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(20):
                if os.path.exists("/dev/rfcomm0"):
                    subprocess.run(["chmod", "666", "/dev/rfcomm0"], check=False)
                    return
                time.sleep(0.5)
        else:
            subprocess.run(["rfcomm", "release", "all"], check=False)
    except Exception:
        pass

def report_status(job_id, status, error=None):
    payload = {"id": job_id, "status": status}
    if error:
        payload["error"] = error
    requests.post(f"{SERVER_URL}/api/agent/status", headers={"X-Agent-Key": AGENT_KEY}, json=payload, timeout=10)

def handle_print_job(job_id, filename, audio_filename=None):
    global PRINT_JOB_ACTIVE
    PRINT_JOB_ACTIVE = True

    temp_path = None
    temp_audio_path = None
    print_done = [False]
    bg_error = [False]
    short_id = str(job_id)[:8]

    def connect_printer_bg():
        if os.path.exists(DEMO_FILE):
            logger.info("DEMO MODE ACTIVE: Bypassing Bluetooth printing.")
            return

        while True:
            if bg_error[0] or print_done[0]: return
            try:
                with PRINTER_LOCK:
                    manage_bluetooth(connect=True)
                    p = create_printer()
                    p.connect(PRINTER_MAC)

                    logger.info("Background: Connected! Transferring data...")
                    p.print(temp_path)
                    p.disconnect()

                diagnostics.set_printer(reachable=True, error=None)
                logger.success("Print complete - photo is out of the printer")
                report_status(job_id, "completed")
                print_done[0] = True
                break
            except BaseException as e:
                err_name = type(e).__name__
                reason = friendly_printer_error(e)
                diagnostics.set_printer(reachable=False, error=reason)
                logger.warning(f"Background Printer Issue ({err_name}): {reason} Retrying in 20s...")
                manage_bluetooth(connect=False)
                for _ in range(40):
                    if bg_error[0] or print_done[0]: return
                    time.sleep(0.5)

    try:
        logger.info(f"New photo received (job {short_id}) - starting notification lights and sound")
        diagnostics.set_stage("downloading", "Downloading the photo from the server...", job_id)
        get_leds().start_heartbeat()

        logger.info(f"Downloading image: {filename}")
        res = requests.get(f"{SERVER_URL}/api/agent/download/{filename}", headers={"X-Agent-Key": AGENT_KEY}, timeout=60)
        res.raise_for_status()
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(temp_path, "wb") as f:
            f.write(res.content)

        if audio_filename:
            logger.info(f"Downloading audio message: {audio_filename}")
            try:
                audio_res = requests.get(f"{SERVER_URL}/api/agent/download/{audio_filename}", headers={"X-Agent-Key": AGENT_KEY}, timeout=60)
                if audio_res.status_code == 200:
                    temp_audio_path = os.path.join(tempfile.gettempdir(), audio_filename)
                    with open(temp_audio_path, "wb") as f:
                        f.write(audio_res.content)
            except Exception as e:
                logger.error(f"Audio download failed: {e}")

        # Start printer connection in the background!
        bg_thread = threading.Thread(target=connect_printer_bg)
        bg_thread.daemon = True
        bg_thread.start()

        logger.info("Waiting for button press...")
        diagnostics.set_stage("waiting_for_button", "Photo is ready - waiting for someone to press the button", job_id)
        get_leds().wait_for_button(timeout=600)

        # -------------------------------------------------------------
        # THE MAGIC 8 SECONDS OF LIGHTS HAPPENS RIGHT AFTER THIS LINE!
        # -------------------------------------------------------------
        logger.info("Button pressed! Fast-pulse starting...")
        diagnostics.set_stage("printing", "Printing - the photo takes about a minute", job_id)
        get_leds().start_printing_animation()

        audio_proc = None
        if temp_audio_path:
            try:
                wav_path = temp_audio_path + ".wav"
                subprocess.run(["ffmpeg", "-y", "-i", temp_audio_path, "-filter:a", "volume=3.0", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                audio_proc = subprocess.Popen(["sudo", "-u", "wowbox_milab", "env", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", "pw-play", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info("Playing the sender's voice message")
            except Exception as e:
                logger.error(f"Could not play the voice message: {e}")

        # Wait for the background thread to finish printing
        if os.path.exists(DEMO_FILE):
            logger.info("DEMO MODE: Simulating printing animation...")

            start_time = time.time()
            if audio_proc:
                # Wait for the audio to finish playing (max 120 seconds safeguard)
                try:
                    audio_proc.wait(timeout=120)
                except Exception:
                    pass

            elapsed = time.time() - start_time
            if elapsed < 8:
                time.sleep(8 - elapsed)  # Ensure we always get at least 8 seconds of magic lights

            report_status(job_id, "completed")
            logger.info("Demo job finished")
        else:
            while not print_done[0]:
                if bg_error[0]: break
                time.sleep(1)

    except Exception as e:
        # Previously a failure here left the job stuck on "printing" forever with no explanation.
        logger.error(f"Job {short_id} failed: {type(e).__name__}: {e}")
        diagnostics.set_error(f"Job {short_id} failed: {type(e).__name__}: {e}")
        diagnostics.set_stage("error", f"Job failed: {e}", job_id)
        try:
            report_status(job_id, "failed", f"{type(e).__name__}: {e}")
        except Exception:
            pass

    finally:
        bg_error[0] = True # Tell bg thread to stop
        get_leds().off()
        manage_bluetooth(connect=False)

        PRINT_JOB_ACTIVE = False
        diagnostics.set_stage("idle", "Waiting for photos")

        if temp_audio_path:
            if os.path.exists(temp_audio_path):
                try: os.remove(temp_audio_path)
                except Exception: pass
            if os.path.exists(temp_audio_path + ".wav"):
                try: os.remove(temp_audio_path + ".wav")
                except Exception: pass
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass

# ─── Remote actions requested from the Status page ────────────────────────────

def test_speaker():
    if PRINT_JOB_ACTIVE:
        logger.warning("Speaker test skipped - a print job is in progress")
        return
    logger.info("Speaker test: playing a short sound...")
    wav = os.path.join(SCRIPT_DIR, "ringtone.wav")
    # 'timeout' stops the sound after 4s; exit code 124 just means "played until stopped"
    res = subprocess.run(["timeout", "-k", "1", "4"] + diagnostics.as_audio_user(["pw-play", wav]),
                         capture_output=True, text=True)
    ok = res.returncode in (0, 124)
    diagnostics.set_speaker_test(ok)
    if ok:
        logger.info("Speaker test: sound sent to the audio output (did you hear it? check cable, volume and speaker power)")
    else:
        logger.warning(f"Speaker test failed: {res.stderr.strip() or 'audio player error'}")

def test_lights():
    if PRINT_JOB_ACTIVE:
        logger.warning("Light test skipped - a print job is in progress")
        return
    logger.info("Light test: flashing red, green, blue")
    leds = get_leds()
    for r, g, b in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
        leds.set_color(r, g, b)
        time.sleep(0.6)
    leds.off()

def run_command(command):
    logger.info(f"Remote action received: {command}")
    if command == "restart_agent":
        logger.info("Restarting the agent service...")
        time.sleep(1)  # let the log line ship first
        subprocess.Popen(["systemctl", "restart", "wowbox-agent.service"], start_new_session=True)
    elif command == "test_speaker":
        threading.Thread(target=test_speaker, daemon=True).start()
    elif command == "test_lights":
        threading.Thread(target=test_lights, daemon=True).start()
    elif command == "check_printer":
        def check():
            if PRINT_JOB_ACTIVE:
                logger.warning("Printer check skipped - a print job is in progress")
            elif not probe_printer():
                logger.warning("Printer check skipped - Bluetooth is busy, try again in a moment")
        threading.Thread(target=check, daemon=True).start()
    else:
        logger.warning(f"Unknown remote action ignored: {command}")

class HeartbeatThread(threading.Thread):
    """Reports health + new log lines to the server and receives remote actions."""

    def __init__(self):
        super().__init__()
        self.daemon = True

    def run(self):
        offline_logged = False
        while True:
            batch = diagnostics.REMOTE_LOGS.peek(100)
            try:
                payload = {
                    "status": diagnostics.build_status(PRINTER_MAC, os.path.exists(DEMO_FILE), PRINT_JOB_ACTIVE),
                    "logs": batch,
                }
                res = requests.post(f"{SERVER_URL}/api/agent/heartbeat", headers={"X-Agent-Key": AGENT_KEY}, json=payload, timeout=10)
                res.raise_for_status()
                diagnostics.REMOTE_LOGS.drop(len(batch))
                offline_logged = False
                for command in res.json().get("commands", []):
                    run_command(command)
            except Exception as e:
                # Logs stay buffered and are delivered when the connection returns.
                if not offline_logged:
                    logger.debug(f"Heartbeat failed: {e}")
                    offline_logged = True
            time.sleep(HEARTBEAT_INTERVAL)

def main():
    logger.info("=" * 50)
    logger.info(f"  WOWBOX Agent v{diagnostics.AGENT_VERSION} (Diagnostics Update)")
    logger.info("=" * 50)
    get_leds().off()

    HeartbeatThread().start()

    keep_alive = PrinterKeepAlive(PRINTER_MAC)
    keep_alive.start()

    speaker_keep_alive = SpeakerKeepAlive(interval=60)
    speaker_keep_alive.start()

    while True:
        try:
            res = requests.get(f"{SERVER_URL}/api/agent/next", headers={"X-Agent-Key": AGENT_KEY}, timeout=15)
            if diagnostics.poll_result(res.status_code == 200, f"Server answered HTTP {res.status_code}"):
                if res.status_code == 200:
                    logger.info("Connected to the WOWBOX server")
                else:
                    logger.warning(f"Server answered HTTP {res.status_code} - check the agent key / server URL")
            if res.status_code == 200:
                data = res.json()
                if data.get("has_job"):
                    handle_print_job(data["id"], data["filename"], data.get("audio_filename"))
            time.sleep(POLL_INTERVAL)
        except requests.RequestException as e:
            # Expected when the hotspot/Wi-Fi drops: log once, not every few seconds.
            if diagnostics.poll_result(False, f"{type(e).__name__}"):
                logger.warning(f"Cannot reach the server ({type(e).__name__}) - check the Wi-Fi / hotspot. Will keep retrying.")
            time.sleep(POLL_INTERVAL)
        except BaseException as e:
            logger.exception("FATAL CRASH!")
            diagnostics.set_error(f"Unexpected error: {type(e).__name__}: {e}")
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
