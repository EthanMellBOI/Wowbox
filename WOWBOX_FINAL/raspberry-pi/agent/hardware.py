import time
import threading
import os
import subprocess
import math
import random
from rpi_ws281x import PixelStrip, Color
from gpiozero import Button

# ---> WE CHANGED THE PIN TO 10 HERE <---
LED_COUNT = 12
LED_PIN = 10
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 255
LED_INVERT = False
LED_CHANNEL = 0
BUTTON_PIN = 17

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class LEDController:
    def __init__(self):
        self.strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        self.strip.begin()
        self.stop_event = threading.Event()
        self.thread = None
        self.animation_mode = None

        # Added hold_time=5 for the quick service restart functionality!
        self.button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.1, hold_time=5)
        self.button.when_held = self.restart_service

        # --- DEMO MODE TRIPLE CLICK ---
        self.button.when_pressed = self._on_press
        self.click_count = 0
        self.last_click_time = 0
        self.is_waiting = False
        # ------------------------------

        self._audio_timer = None
        self.off()

    def _on_press(self):
        # Do not toggle demo mode if we are actively waiting for a user to open a photo.
        # This prevents a client from accidentally changing modes if they double/triple click!
        if getattr(self, 'is_waiting', False):
            return
            
        now = time.time()
        # INCREASED FROM 0.8s to 2.5s
        # You now have a very relaxed 2.5 seconds between clicks!
        if now - self.last_click_time > 2.5:
            self.click_count = 0
            
        self.click_count += 1
        self.last_click_time = now
        
        if self.click_count == 3:
            self.click_count = 0
            self.toggle_demo_mode()

    def toggle_demo_mode(self):
        demo_file = '/home/wowbox_milab/.wowbox_demo_mode'
        if os.path.exists(demo_file):
            os.remove(demo_file)
            # Flashing BLUE means Demo is OFF (Regular Mode)
            threading.Thread(target=self._flash_color, args=(0, 0, 255), daemon=True).start() 
        else:
            with open(demo_file, 'w') as f:
                f.write('1')
            # Flashing GREEN means Demo is ON
            threading.Thread(target=self._flash_color, args=(0, 255, 0), daemon=True).start() 

    def _flash_color(self, r, g, b):
        prev_mode = self.animation_mode
        self.off()
        for _ in range(3):
            self.set_color(r, g, b)
            time.sleep(0.15)
            self.set_color(0, 0, 0)
            time.sleep(0.15)
        if prev_mode:
            self._start_animation(prev_mode)

    # Triggered when held for 5 seconds
    def restart_service(self):
        # Restarts the python service instantly instead of rebooting the entire Pi!
        subprocess.Popen(["sudo", "systemctl", "restart", "wowbox-agent.service"], start_new_session=True)

    def off(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        self.animation_mode = None  # Wipes memory clean to prevent stuck lights
        self.stop_audio()
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()

    def set_color(self, red, green, blue):
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(red, green, blue))
        self.strip.show()

    def _play_audio(self):
        self.stop_audio()
        try:
            cmd = f"while true; do pw-play {os.path.join(SCRIPT_DIR, 'ringtone.wav')}; done"
            subprocess.Popen(
                ["sudo", "-u", "wowbox_milab", "env", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", "bash", "-c", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Failed to play audio: {e}")

    def stop_audio(self):
        if self._audio_timer:
            self._audio_timer.cancel()
            self._audio_timer = None

        try:
            # INSTANT BYPASS: If ringtone isn't playing, skip the slow 2-second fade-out loop!
            res = subprocess.run(["pgrep", "-f", "ringtone.wav"], capture_output=True, text=True)
            if not res.stdout.strip():
                subprocess.run(["sudo", "pkill", "-f", "ringtone.wav"], check=False)
                return
        except Exception:
            pass

        try:
            # Cinematic Volume Fade-Out using PipeWire's wpctl
            prefix = ["sudo", "-u", "wowbox_milab", "env", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"]
            res = subprocess.run(prefix + ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True)
            if "Volume:" in res.stdout:
                vol_str = res.stdout.strip().split()[1]
                orig_vol = float(vol_str)

                # Fade down in 15 smooth steps over ~0.6 seconds
                for i in range(1, 16):
                    fade_vol = orig_vol * (1.0 - (i / 15.0))
                    subprocess.run(prefix + ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{fade_vol:.2f}"], stdout=subprocess.DEVNULL)
                    time.sleep(0.04)

                # Now that it's silent, safely kill the audio process
                subprocess.run(["sudo", "pkill", "-f", "ringtone.wav"], check=False)

                # Instantly restore the volume back to normal for the voice message!
                subprocess.run(prefix + ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{orig_vol:.2f}"], stdout=subprocess.DEVNULL)
                return
        except Exception:
            pass

        # Fallback if wpctl fails
        subprocess.run(["sudo", "pkill", "-f", "ringtone.wav"], check=False)

    def _start_animation(self, mode):
        if self.thread and self.thread.is_alive():
            if self.animation_mode == mode:
                return
            self.stop_event.set()
            self.thread.join()

        self.animation_mode = mode
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._animation_worker)
        self.thread.daemon = True
        self.thread.start()

    def start_heartbeat(self):
        # Notification mode (Sunlight Breath)
        self._play_audio()
        self._start_animation('notification')

    def start_printing_animation(self):
        # Printing mode (Warm Hearth Orbit)
        self._start_animation('printing')

    def stop_heartbeat(self):
        self.off()

    def wait_for_button(self, timeout=600):
        self.is_waiting = True
        start_time = time.time()
        audio_playing = True
        while True: # Keep waiting infinitely for the button!
            # Stop the ringtone after 10 minutes, but keep looping and keep lights on
            if audio_playing and (time.time() - start_time) > timeout:
                self.stop_audio()
                audio_playing = False

            if self.button.is_active:
                stable_press = True
                for _ in range(5):
                    time.sleep(0.02)
                    if not self.button.is_active:
                        stable_press = False
                        break
                if stable_press:
                    self.stop_audio()
                    self.start_printing_animation()
                    self.is_waiting = False
                    return True
            time.sleep(0.01)

    def _animation_worker(self):
        while not self.stop_event.is_set():
            if self.animation_mode == 'notification':
                R, G, B = 255, 80, 0
                if not hasattr(self, "fireflies") or self.animation_mode != getattr(self, "_last_mode", None):
                    self.fireflies = [[0.0, random.uniform(0.5, 1.0), 0.02] for _ in range(self.strip.numPixels())]
                    self._last_mode = self.animation_mode
                for i in range(self.strip.numPixels()):
                    f = self.fireflies[i]
                    current, target, inc = f[0], f[1], f[2]
                    if current < target:
                        current = min(target, current + inc)
                    elif current > target:
                        current = max(target, current - inc)
                    if abs(current - target) < 0.01:
                        if target > 0.1:
                            f[1] = 0.0
                            f[2] = random.uniform(0.01, 0.03)
                        else:
                            if random.random() < 0.05:
                                f[1] = random.uniform(0.5, 1.0)
                                f[2] = random.uniform(0.02, 0.05)
                    f[0] = current
                    self.strip.setPixelColor(i, Color(int(R * current), int(G * current), int(B * current)))
                self.strip.show()
                time.sleep(0.05)

            elif self.animation_mode == 'printing':
                R, G, B = 255, 120, 20
                if not hasattr(self, "orbit_pos"):
                    self.orbit_pos = 0.0
                self.orbit_pos += 0.15
                if self.orbit_pos >= self.strip.numPixels():
                    self.orbit_pos -= self.strip.numPixels()
                pos = int(self.orbit_pos)
                for i in range(self.strip.numPixels()):
                    dist = (pos - i) % self.strip.numPixels()
                    if dist < 4:
                        intensity = 1.0 - (dist * 0.25)
                        self.strip.setPixelColor(i, Color(int(R * intensity), int(G * intensity), int(B * intensity)))
                    else:
                        self.strip.setPixelColor(i, Color(0,0,0))
                self.strip.show()
                time.sleep(0.04)
            else:
                self.set_color(0, 0, 0)
                time.sleep(0.1)


# Singleton instance
leds = None
def get_leds():
    global leds
    if leds is None:
        leds = LEDController()
    return leds
