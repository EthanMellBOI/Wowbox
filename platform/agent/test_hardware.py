import time
from hardware import get_leds

print("Testing WOWBOX Hardware...")
leds = get_leds()

print("1. Playing Kalimba melody and pink heartbeat...")
leds.start_heartbeat()
time.sleep(5)

print("2. Simulating button press! Switching to orange printing animation...")
leds.stop_audio()
leds.start_printing_animation()
time.sleep(5)

print("3. Turning off...")
leds.stop_heartbeat()
print("Test Complete!")
