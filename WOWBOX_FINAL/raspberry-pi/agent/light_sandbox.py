import time
import threading
import math
import random
from rpi_ws281x import PixelStrip, Color

# LED Configuration
LED_COUNT = 12
LED_PIN = 10
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 255
LED_INVERT = False
LED_CHANNEL = 0

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

stop_event = threading.Event()
current_mode = None

def set_color(r, g, b):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(r, g, b))
    strip.show()

def animation_worker():
    current_flicker = 0.5  # For campfire state
    
    while not stop_event.is_set():
        if current_mode == '1': # Digital Heartbeat
            R, G, B = 255, 0, 100
            steps, delay = 50, 0.02
            for i in range(steps + 1):
                if stop_event.is_set() or current_mode != '1': break
                level = i / steps
                set_color(int(R * level), int(G * level), int(B * level))
                time.sleep(delay)
            for i in range(steps, -1, -1):
                if stop_event.is_set() or current_mode != '1': break
                level = i / steps
                set_color(int(R * level), int(G * level), int(B * level))
                time.sleep(delay)
            time.sleep(0.5)

        elif current_mode == '2': # Sunlight Breath
            R, G, B = 255, 180, 50
            steps, delay = 100, 0.03
            for i in range(steps + 1):
                if stop_event.is_set() or current_mode != '2': break
                level = i / steps
                set_color(int(R * level), int(G * level), int(B * level))
                time.sleep(delay)
            for i in range(steps, -1, -1):
                if stop_event.is_set() or current_mode != '2': break
                level = i / steps
                set_color(int(R * level), int(G * level), int(B * level))
                time.sleep(delay)
            time.sleep(1.0)

        elif current_mode == '3': # Ocean Wave
            R, G, B = 0, 150, 255
            in_steps, in_delay = 100, 0.04  # 4s build up
            out_steps, out_delay = 100, 0.02 # 2s recede
            for i in range(in_steps + 1):
                if stop_event.is_set() or current_mode != '3': break
                level = i / in_steps
                eased = (1 - math.cos(level * math.pi)) / 2
                set_color(int(R * eased), int(G * eased), int(B * eased))
                time.sleep(in_delay)
            for i in range(out_steps, -1, -1):
                if stop_event.is_set() or current_mode != '3': break
                level = i / out_steps
                eased = (1 - math.cos(level * math.pi)) / 2
                set_color(int(R * eased), int(G * eased), int(B * eased))
                time.sleep(out_delay)
            time.sleep(0.5)

        elif current_mode == '4': # Campfire (Gentle)
            if stop_event.is_set() or current_mode != '4': 
                continue
            R, G, B = 255, 110, 15
            target = random.uniform(0.4, 1.0)
            steps = 20
            diff = (target - current_flicker) / steps
            for i in range(steps):
                if stop_event.is_set() or current_mode != '4': break
                current_flicker += diff
                set_color(int(R * current_flicker), int(G * current_flicker), int(B * current_flicker))
                time.sleep(0.01)
            time.sleep(random.uniform(0.05, 0.2))

        elif current_mode == '5': # Deep-Sea Split (HRI Blue Split)
            if stop_event.is_set() or current_mode != '5': 
                continue
            R, G, B = 0, 30, 200 # Soft Blue
            for pos in range(6): # Center is between 5 and 6
                if stop_event.is_set() or current_mode != '5': break
                for i in range(strip.numPixels()):
                    strip.setPixelColor(i, Color(0,0,0)) # clear
                strip.setPixelColor(5 - pos, Color(R, G, B))
                strip.setPixelColor(6 + pos, Color(R, G, B))
                if pos > 0:
                    strip.setPixelColor(5 - pos + 1, Color(int(R*0.3), int(G*0.3), int(B*0.3)))
                    strip.setPixelColor(6 + pos - 1, Color(int(R*0.3), int(G*0.3), int(B*0.3)))
                strip.show()
                time.sleep(0.2)
            for i in range(strip.numPixels()):
                strip.setPixelColor(i, Color(0,0,0))
            strip.show()
            time.sleep(1.0)

        elif current_mode in ['6', '7']: # Gentle Orbit (6=Blue, 7=Warm)
            if stop_event.is_set() or current_mode not in ['6', '7']: 
                continue
            if current_mode == '6':
                R, G, B = 0, 80, 200 # Cyan/Blue
            else:
                R, G, B = 255, 120, 20 # Warm Amber/Yellow
            
            if not hasattr(animation_worker, "orbit_pos"):
                animation_worker.orbit_pos = 0.0
                
            animation_worker.orbit_pos += 0.15 
            if animation_worker.orbit_pos >= strip.numPixels():
                animation_worker.orbit_pos -= strip.numPixels()
                
            pos = int(animation_worker.orbit_pos)
            for i in range(strip.numPixels()):
                dist = (pos - i) % strip.numPixels()
                if dist < 4:
                    intensity = 1.0 - (dist * 0.25)
                    strip.setPixelColor(i, Color(int(R * intensity), int(G * intensity), int(B * intensity)))
                else:
                    strip.setPixelColor(i, Color(0,0,0))
            strip.show()
            time.sleep(0.04)

        elif current_mode in ['8', '9', '10']: # Firefly Jar
            if stop_event.is_set() or current_mode not in ['8', '9', '10']: 
                continue
                
            if current_mode == '8':
                r, g, b = 150, 255, 50
            elif current_mode == '9':
                r, g, b = 255, 110, 15
            else:
                r, g, b = 255, 80, 0
                
            if not hasattr(animation_worker, "fireflies"):
                animation_worker.fireflies = [[0.0, random.uniform(0.5, 1.0), 0.02] for _ in range(strip.numPixels())]
            for i in range(strip.numPixels()):
                f = animation_worker.fireflies[i]
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
                strip.setPixelColor(i, Color(int(r * current), int(g * current), int(b * current)))
            strip.show()
            time.sleep(0.05)

        else:
            set_color(0, 0, 0)
            time.sleep(0.1)

    set_color(0, 0, 0)

print("\n" + "="*45)
print("     WOWBOX Final 9-Mode Sandbox     ")
print("="*45)
print("1) Digital Heartbeat (Baseline)")
print("2) Sunlight Breath (Warmth)")
print("3) Gentle Ocean Wave (Serenity)")
print("4) Campfire Glow (Gentle Coals)")
print("5) Deep-Sea Split (HRI Blue Split)")
print("6) Gentle Orbit (HRI Blue Circle)")
print("7) Warm Hearth Orbit (HRI Warm Circle)")
print("8) Firefly Jar (Nature Green/Yellow)")
print("9) Campfire Fireflies (Golden Ember)")
print("10) Old Fireflies (Deep Orange)")
print("0) Turn Off / Exit")
print("="*45)

t = threading.Thread(target=animation_worker)
t.daemon = True
t.start()

try:
    while True:
        choice = input("\nSelect mode (0-10): ").strip()
        if choice == '0':
            print("Exiting...")
            stop_event.set()
            t.join()
            break
        elif choice in [str(i) for i in range(1, 11)]:
            current_mode = choice
            print(f"--> Switched to Mode {choice}")
            # Clean up state variables when switching
            if choice not in ['8', '9'] and hasattr(animation_worker, "fireflies"):
                delattr(animation_worker, "fireflies")
            if choice not in ['6', '7'] and hasattr(animation_worker, "orbit_pos"):
                delattr(animation_worker, "orbit_pos")
        else:
            print("Invalid choice. Enter 0-9.")
except KeyboardInterrupt:
    stop_event.set()
    t.join()
