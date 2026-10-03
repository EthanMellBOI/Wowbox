import os
import termios
import tty
import queue
import threading
import time
import select

AUTO_DISCONNECT_TIMEOUT = 30

class ClientThread(threading.Thread):
    def __init__(self, receive_size=4096):
        super().__init__()
        self.daemon = True
        self.receive_size = receive_size
        self.fd = None
        self.alive = threading.Event()
        self.outbound_q = queue.Queue()
        self.inbound_q = queue.Queue()
        self.disconnect_timer = None

    def connect(self, mac, port):
        self.fd = os.open('/dev/rfcomm0', os.O_RDWR | os.O_NOCTTY)
        tty.setraw(self.fd)  # raw mode - ללא עיבוד tty
        self.alive.set()
        self.disconnect_timer = threading.Timer(AUTO_DISCONNECT_TIMEOUT, self.disconnect)
        self.disconnect_timer.daemon = True
        self.disconnect_timer.start()
        self.start()
        print("FakeSock connected to /dev/rfcomm0 (raw mode)")

    def run(self):
        while self.alive.is_set():
            # שלח הודעות
            try:
                message = self.outbound_q.get(True, 0.05)
                os.write(self.fd, message)
                time.sleep(0.02)
                if self.disconnect_timer:
                    self.disconnect_timer.cancel()
                self.disconnect_timer = threading.Timer(AUTO_DISCONNECT_TIMEOUT, self.disconnect)
                self.disconnect_timer.daemon = True
                self.disconnect_timer.start()
            except (queue.Empty, OSError):
                pass

            # קבל תגובות
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.05)
                if ready:
                    data = os.read(self.fd, self.receive_size)
                    if data:
                        self.inbound_q.put(data)
            except Exception:
                pass

    def disconnect(self, timeout=None):
        self.alive.clear()
        if self.disconnect_timer:
            self.disconnect_timer.cancel()
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            threading.Thread.join(self, timeout)
        except RuntimeError:
            pass
