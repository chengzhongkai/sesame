# wifi_manager.py
import network
import uasyncio as asyncio
import time

async def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)

    max_attempts = 20
    attempts = 0
    while not wlan.isconnected() and attempts < max_attempts:
        print(f"Connecting to WiFi... ({attempts+1}/{max_attempts})")
        await asyncio.sleep(1)
        attempts += 1

    if wlan.isconnected():
        print("WiFi connected:", wlan.ifconfig())
        return True
    else:
        print("WiFi connection failed!")
        return False
