# main.py
import uasyncio as asyncio
import config
import wifi_manager
from ble_manager import BLEManager
from mqtt_client import MQTTManager
import time # For time.time() in example

# 全局变量或通过类实例传递
ble_manager_instance = None
mqtt_manager_instance = None

async def main():
    global ble_manager_instance, mqtt_manager_instance

    print("Starting ESP32 Dual BLE/WiFi/MQTT Application with aioble...")

    # 1. 连接WiFi
    wifi_connected = await wifi_manager.connect_wifi(config.WIFI_SSID, config.WIFI_PASSWORD)
    if not wifi_connected:
        print("Exiting due to WiFi connection failure.")
        return

    # 2. 初始化MQTT
    mqtt_manager_instance = MQTTManager(config.MQTT_BROKER, config.MQTT_CLIENT_ID)
    await mqtt_manager_instance.connect()
    mqtt_manager_instance.subscribe(config.MQTT_SUB_TOPIC)
    asyncio.create_task(mqtt_manager_instance.mqtt_loop()) # 启动MQTT循环

    # 3. 初始化BLE管理器
    ble_manager_instance = BLEManager()
    # ble_loop会同时启动外设和主机相关任务
    asyncio.create_task(ble_manager_instance.ble_loop())

    # 示例：MQTT消息处理，转发到BLE设备
    def mqtt_msg_handler(topic, msg):
        global ble_manager_instance
        msg_str = msg.decode()
        print(f"Main loop received MQTT: {msg_str}")
        if msg_str.startswith("WRITE_DEV1:"):
            data_to_send = msg_str[len("WRITE_DEV1:"):].encode()
            asyncio.create_task(ble_manager_instance.central_write_data(config.TARGET_DEVICE_1_NAME, data_to_send))
        elif msg_str.startswith("WRITE_DEV2:"):
            data_to_send = msg_str[len("WRITE_DEV2:"):].encode()
            asyncio.create_task(ble_manager_instance.central_write_data(config.TARGET_DEVICE_2_NAME, data_to_send))
        elif msg_str.startswith("BLE_PERIPHERAL_TX:"):
            data_to_send = msg_str[len("BLE_PERIPHERAL_TX:"):].encode()
            asyncio.create_task(ble_manager_instance.peripheral_send_data(data_to_send))

    mqtt_manager_instance.client.set_callback(mqtt_msg_handler)

    # 主应用循环
    while True:
        # 示例：每10秒通过外设模式向连接的主机发送数据
        if ble_manager_instance and ble_manager_instance.peripheral_connection:
            await ble_manager_instance.peripheral_send_data(f"Hello from Peripheral! Time: {time.time()}".encode())

        # 可以在这里添加其他应用逻辑，例如：
        # - 定期从BLE设备读取数据并发布到MQTT
        # - 根据MQTT命令控制BLE外设的特性
        # - 检查BLE连接状态并重新连接 (aioble会自动处理一部分)
        await asyncio.sleep(10) # 主循环间隔

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Application stopped by KeyboardInterrupt.")
except Exception as e:
    print(f"An error occurred: {e}")
finally:
    # aioble会自动处理蓝牙关闭，通常不需要手动调用 aioble.core.active(False)
    # 但如果遇到问题，可以尝试加上
    # aioble.core.active(False)
    print("Cleanup done.")
  
