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
"""

import threading
import os, sys, time, tempfile, requests, subprocess, signal
from loguru import logger
from hardware import get_leds

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
from config import SERVER_URL, AGENT_KEY, PRINTER_MAC, POLL_INTERVAL

# Global flag to prevent keep-alive pings during active print jobs
PRINT_JOB_ACTIVE = False

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

class PrinterKeepAlive(threading.Thread):
    def __init__(self, mac_address, interval=90):
        super().__init__()
        self.mac_address = mac_address
        self.interval = interval
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        logger.info("Background printer keep-alive thread started.")
        while not self.stop_event.is_set():
            for _ in range(self.interval):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

            if PRINT_JOB_ACTIVE:
                logger.debug("Print job active; skipping keep-alive ping.")
                continue

            if os.path.exists('/home/wowbox_milab/.wowbox_demo_mode'):
                continue

            try:
                manage_bluetooth(connect=True)
                printer = create_printer()
                printer.connect(self.mac_address)
                printer.set_setting(10)
                printer.get_status()
                logger.info("Sent keep-awake status ping to Canon Ivy 2.")
                printer.disconnect()
            except Exception as e:
                logger.debug(f"Keep-awake ping skipped (printer offline): {e}")
            finally:
                if not PRINT_JOB_ACTIVE:
                    manage_bluetooth(connect=False)

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
            logger.info("Initializing Bluetooth...")
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

def handle_print_job(job_id, filename, audio_filename=None):
    global PRINT_JOB_ACTIVE
    PRINT_JOB_ACTIVE = True

    temp_path = None
    temp_audio_path = None
    print_done = [False]
    bg_error = [False]

    def connect_printer_bg():
        if os.path.exists('/home/wowbox_milab/.wowbox_demo_mode'):
            logger.info("DEMO MODE ACTIVE: Bypassing Bluetooth printing.")
            return

        while True:
            if bg_error[0] or print_done[0]: return
            try:
                manage_bluetooth(connect=True)
                p = create_printer()
                p.connect(PRINTER_MAC)

                logger.info("Background: Connected! Transferring data...")
                p.print(temp_path)
                p.disconnect()

                requests.post(f"{SERVER_URL}/api/agent/status", headers={"X-Agent-Key": AGENT_KEY}, json={"id": job_id, "status": "completed"}, timeout=10)
                print_done[0] = True
                break
            except BaseException as e:
                err_name = type(e).__name__
                logger.warning(f"Background Printer Issue ({err_name}). Retrying in 20s...")
                manage_bluetooth(connect=False)
                for _ in range(40):
                    if bg_error[0] or print_done[0]: return
                    time.sleep(0.5)

    try:
        get_leds().start_heartbeat()

        logger.info(f"Downloading image: {filename}")
        res = requests.get(f"{SERVER_URL}/api/agent/download/{filename}", headers={"X-Agent-Key": AGENT_KEY}, timeout=60)
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
        get_leds().wait_for_button(timeout=600)

        # -------------------------------------------------------------
        # THE MAGIC 8 SECONDS OF LIGHTS HAPPENS RIGHT AFTER THIS LINE!
        # -------------------------------------------------------------
        logger.info("Button pressed! Fast-pulse starting...")
        get_leds().start_printing_animation()

        audio_proc = None
        if temp_audio_path:
            try:
                wav_path = temp_audio_path + ".wav"
                subprocess.run(["ffmpeg", "-y", "-i", temp_audio_path, "-filter:a", "volume=3.0", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                audio_proc = subprocess.Popen(["sudo", "-u", "wowbox_milab", "env", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", "pw-play", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        # Wait for the background thread to finish printing
        if os.path.exists('/home/wowbox_milab/.wowbox_demo_mode'):
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
                
            requests.post(f"{SERVER_URL}/api/agent/status", headers={"X-Agent-Key": AGENT_KEY}, json={"id": job_id, "status": "completed"}, timeout=10)
        else:
            while not print_done[0]:
                if bg_error[0]: break
                time.sleep(1)

    finally:
        bg_error[0] = True # Tell bg thread to stop
        get_leds().off()
        manage_bluetooth(connect=False)

        PRINT_JOB_ACTIVE = False

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

def main():
    logger.info("=" * 50)
    logger.info("  WOWBOX Agent v3.3 (Resilience Update)")
    logger.info("=" * 50)
    get_leds().off()

    keep_alive = PrinterKeepAlive(PRINTER_MAC)
    keep_alive.start()

    speaker_keep_alive = SpeakerKeepAlive(interval=60)
    speaker_keep_alive.start()

    while True:
        try:
            res = requests.get(f"{SERVER_URL}/api/agent/next", headers={"X-Agent-Key": AGENT_KEY}, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if data.get("has_job"):
                    handle_print_job(data["id"], data["filename"], data.get("audio_filename"))
            time.sleep(POLL_INTERVAL)
        except BaseException as e:
            logger.exception("FATAL CRASH!")
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
