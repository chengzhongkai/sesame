# mqtt_client.py
from umqtt.simple import MQTTClient
import uasyncio as asyncio
import time

class MQTTManager:
    def __init__(self, broker, client_id):
        self.client = MQTTClient(client_id, broker)
        self.client.set_callback(self._mqtt_callback)
        self.broker = broker
        self.client_id = client_id
        self.connected = False

    def _mqtt_callback(self, topic, msg):
        print(f"MQTT Received: Topic='{topic.decode()}', Message='{msg.decode()}'")
        # 在这里处理MQTT接收到的消息，例如转发到BLE设备
        # 注意：这里不能直接调用BLEManager的方法，因为回调函数是同步的
        # 应该将消息放入一个队列，然后在主循环或另一个异步任务中处理
        # 例如：asyncio.create_task(self.ble_manager.central_write_data("MyBLEDevice1", msg))
        # 但这需要将ble_manager实例传递进来

    async def connect(self):
        try:
            print(f"Connecting to MQTT broker: {self.broker}...")
            self.client.connect()
            self.connected = True
            print("MQTT connected.")
            return True
        except OSError as e:
            print(f"MQTT connection failed: {e}")
            self.connected = False
            return False

    def subscribe(self, topic):
        if self.connected:
            self.client.subscribe(topic)
            print(f"Subscribed to topic: {topic}")

    def publish(self, topic, msg):
        if self.connected:
            try:
                self.client.publish(topic, msg)
                # print(f"MQTT Published: Topic='{topic}', Message='{msg}'")
            except Exception as e:
                print(f"MQTT publish failed: {e}")
                self.connected = False # 发布失败可能需要重新连接

    async def mqtt_loop(self):
        while True:
            if self.connected:
                try:
                    self.client.check_msg() # 检查是否有新消息
                except OSError as e:
                    print(f"MQTT check_msg failed: {e}, attempting reconnect...")
                    self.connected = False
                except Exception as e:
                    print(f"MQTT error: {e}, attempting reconnect...")
                    self.connected = False

            if not self.connected:
                # 尝试重新连接
                success = await self.connect()
                if success:
                    self.subscribe(config.MQTT_SUB_TOPIC) # 重新订阅
                else:
                    await asyncio.sleep(5) # 连接失败，等待一段时间再试

            await asyncio.sleep(1) # 避免忙等待
