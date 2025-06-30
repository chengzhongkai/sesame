# mqtt_client.py
from umqtt.simple import MQTTClient
import uasyncio as asyncio
import time
from event_bus import event_bus # <-- 导入事件总线

class MQTTManager:
    # 构造函数中注入 event_bus
    def __init__(self, broker, client_id):
        self.client = MQTTClient(client_id, broker)
        self.client.set_callback(self._mqtt_callback)
        self.broker = broker
        self.client_id = client_id
        self.connected = False

    def _mqtt_callback(self, topic, msg):
        print(f"MQTT Received: Topic='{topic.decode()}', Message='{msg.decode()}'")
        # 发布 MQTT 消息接收事件
        # 注意：这里不能 await，因为 _mqtt_callback 是同步的。
        # event_bus.publish 内部会创建异步任务。
        asyncio.create_task(event_bus.publish("mqtt_message_received", topic.decode(), msg.decode()))

    async def connect(self):
        try:
            print(f"Connecting to MQTT broker: {self.broker}...")
            self.client.connect()
            self.connected = True
            print("MQTT connected.")
            # 发布 MQTT 连接成功事件
            await event_bus.publish("mqtt_connected")
            return True
        except OSError as e:
            print(f"MQTT connection failed: {e}")
            self.connected = False
            # 发布 MQTT 连接失败事件
            await event_bus.publish("mqtt_disconnected")
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
                # 发布 MQTT 断开连接事件（或发布失败）
                asyncio.create_task(event_bus.publish("mqtt_disconnected"))

    async def mqtt_loop(self):
        while True:
            if self.connected:
                try:
                    self.client.check_msg()
                except OSError as e:
                    print(f"MQTT check_msg failed: {e}, attempting reconnect...")
                    self.connected = False
                except Exception as e:
                    print(f"MQTT error: {e}, attempting reconnect...")
                    self.connected = False

            if not self.connected:
                success = await self.connect()
                if success:
                    # 重新订阅需要在连接成功后由外部逻辑触发，或者在 EventBus 中监听 mqtt_connected 事件来触发
                    # 这里为了简化，直接在连接成功后订阅
                    # 更好的方式是 MQTTManager 不知道订阅哪个 topic，由 Main 或一个更高层级的应用逻辑订阅
                    pass # 不再在这里订阅，让 Main 来订阅

                else:
                    await asyncio.sleep(5)

            await asyncio.sleep(1)