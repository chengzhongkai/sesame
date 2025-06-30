# main.py
import uasyncio as asyncio
import config
import time
import machine # 用于重启

from event_bus import event_bus # 导入事件总线
from settings_manager import settings_manager # 导入设置管理器实例
from wifi_manager import connect_wifi # WiFi 连接现在直接是函数，或可以封装为类
from mqtt_client import MQTTManager
from ble_manager import BLEManager

# 模块实例
ble_manager_instance = None
mqtt_manager_instance = None

async def main():
    global ble_manager_instance, mqtt_manager_instance

    print("Starting ESP32 Dual BLE/WiFi/MQTT Application with aioble...")

    # --- 模块初始化和依赖注入 ---
    # settings_manager 已经在 settings_manager.py 中作为全局实例初始化

    # 初始化 MQTTManager
    # 此时，MQTTManager 只关心 MQTT 自身，不知道数据要发给谁或从哪里来
    mqtt_broker = settings_manager.get("mqtt_broker")
    mqtt_client_id = settings_manager.get("mqtt_client_id")
    mqtt_manager_instance = MQTTManager(mqtt_broker, mqtt_client_id)

    # 初始化 BLEManager
    # BLEManager 只关心 BLE 自身，不直接知道数据要去哪里
    ble_manager_instance = BLEManager(ble_name="ESP32_Dual_AIOBLE", settings_manager_instance=settings_manager)

    # --- 启动模块的异步任务 ---
    asyncio.create_task(ble_manager_instance.ble_loop())
    asyncio.create_task(mqtt_manager_instance.mqtt_loop())

    # --- 事件订阅与处理逻辑 (核心解耦部分) ---

    # 1. 处理 BLE 外设接收到的数据：发布到 MQTT
    async def handle_ble_peripheral_data(data):
        print(f"Main: Received BLE Peripheral data event: {data}")
        mqtt_topic = settings_manager.get("mqtt_pub_topic")
        mqtt_manager_instance.publish(mqtt_topic, f"BLE_PERIPHERAL_RX:{data}")
    event_bus.subscribe("ble_peripheral_data_received", handle_ble_peripheral_data)

    # 2. 处理 BLE 主机接收到的通知：发布到 MQTT
    async def handle_ble_central_notification(device_name, char_uuid, data):
        print(f"Main: Received BLE Central notification event from {device_name} ({char_uuid}): {data}")
        mqtt_topic = settings_manager.get("mqtt_pub_topic")
        mqtt_manager_instance.publish(mqtt_topic, f"BLE_CENTRAL_NOTIFY_{device_name}:{data}")
    event_bus.subscribe("ble_central_notification_received", handle_ble_central_notification)

    # 3. 处理 MQTT 接收到的消息：转发到 BLE 主机或外设
    async def handle_mqtt_message_received(topic, msg):
        print(f"Main: Received MQTT message event: Topic='{topic}', Message='{msg}'")
        msg_str = msg
        if msg_str.startswith("WRITE_DEV1:"):
            data_to_send = msg_str[len("WRITE_DEV1:"):].encode()
            await ble_manager_instance.central_write_data(config.TARGET_DEVICE_1_NAME, data_to_send)
        elif msg_str.startswith("WRITE_DEV2:"):
            data_to_send = msg_str[len("WRITE_DEV2:"):].encode()
            await ble_manager_instance.central_write_data(config.TARGET_DEVICE_2_NAME, data_to_send)
        elif msg_str.startswith("BLE_PERIPHERAL_TX:"):
            data_to_send = msg_str[len("BLE_PERIPHERAL_TX:"):].encode()
            await ble_manager_instance.peripheral_send_data(data_to_send)
    event_bus.subscribe("mqtt_message_received", handle_mqtt_message_received)

    # 4. 处理设置更新事件：提示可能需要重启
    async def handle_settings_updated(new_settings):
        print(f"Main: Settings updated event received. New settings: {new_settings}")
        print("Please consider restarting the device for some settings (e.g., WiFi/MQTT) to take full effect.")
        # 如果需要自动重启，可以在这里添加 logic：
        # machine.reset()
    event_bus.subscribe("settings_updated", handle_settings_updated)

    # 5. 处理连接事件（可选，用于日志或状态指示）
    async def log_ble_peripheral_connected(addr):
        print(f"Main: BLE Peripheral Connected event: {addr}")
    event_bus.subscribe("ble_peripheral_connected", log_ble_peripheral_connected)

    async def log_mqtt_connected():
        print("Main: MQTT Connected event.")
        # 在这里订阅 MQTT topic，而不是在 MQTTManager 内部
        mqtt_manager_instance.subscribe(settings_manager.get("mqtt_sub_topic"))
    event_bus.subscribe("mqtt_connected", log_mqtt_connected)

    # --- 初始连接 WiFi ---
    # WiFi 连接逻辑放在这里，因为它依赖于 settings_manager 的数据
    # 并且如果连接失败，可能需要停止整个应用或进入恢复模式
    wifi_ssid = settings_manager.get("wifi_ssid")
    wifi_password = settings_manager.get("wifi_password")
    wifi_connected = await connect_wifi(wifi_ssid, wifi_password)
    if not wifi_connected:
        print("Initial WiFi connection failed. Exiting.")
        return

    # 主应用循环
    while True:
        # 可以在这里添加一些周期性的应用逻辑
        await asyncio.sleep(1)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Application stopped by KeyboardInterrupt.")
except Exception as e:
    import sys
    sys.print_exception(e) # 打印详细异常信息
finally:
    print("Cleanup done.")