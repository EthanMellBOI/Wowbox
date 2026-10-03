import os, sys, time, tempfile, requests, subprocess
from loguru import logger
from hardware import get_leds

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from config import SERVER_URL, AGENT_KEY, PRINTER_MAC, POLL_INTERVAL

def create_printer():
    from client import ClientThread
    from ivy2 import Ivy2Printer
    Ivy2Printer.client = ClientThread()
    return Ivy2Printer()

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
    except Exception as e:
        logger.error(f"Bluetooth error: {e}")

def handle_print_job(job_id, filename):
    temp_path = None
    try:
        # Start Heartbeat in background immediately
        logger.info("Starting background heartbeat notification...")
        get_leds().start_heartbeat()

        logger.info(f"Downloading image: {filename}")
        res = requests.get(f"{SERVER_URL}/api/agent/download/{filename}", headers={'X-Agent-Key': AGENT_KEY}, timeout=60)
        
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(temp_path, 'wb') as f:
            f.write(res.content)

        while True:
            try:
                manage_bluetooth(connect=True)
                p = create_printer()
                p.connect(PRINTER_MAC)
                logger.info("Connected! Transferring data (this takes ~1 min)...")
                p.print(temp_path)
                logger.success("Print complete!")
                p.disconnect()
                requests.post(f"{SERVER_URL}/api/agent/status", headers={'X-Agent-Key': AGENT_KEY}, json={'id': job_id, 'status': 'completed'}, timeout=10)
                break
            except Exception as e:
                if any(err in str(e) for err in ["Failed to open", "Connection", "Battery", "Host is down"]):
                    logger.warning("Printer offline. Retrying in 20s...")
                    time.sleep(20)
                else:
                    break
    finally:
        # Stop LEDs only after the entire process (or error) is finished
        get_leds().stop_heartbeat()
        manage_bluetooth(connect=False)
        if temp_path and os.path.exists(temp_path): os.remove(temp_path)

def main():
    logger.info("=" * 50)
    logger.info("  WOWBOX Agent Starting (Infinite Heartbeat Enabled)")
    logger.info("=" * 50)
    while True:
        try:
            res = requests.get(f"{SERVER_URL}/api/agent/next", headers={'X-Agent-Key': AGENT_KEY}, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if data.get('has_job'):
                    handle_print_job(data['id'], data['filename'])
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()
