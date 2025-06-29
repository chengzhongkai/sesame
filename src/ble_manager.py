# ble_manager.py
import uasyncio as asyncio
import aioble
import bluetooth
import time
import struct

# 辅助函数，用于从广告数据中解析名称和UUIDs
# aioble内部可能也有类似功能，但手动解析有时更灵活
def decode_name(payload):
    n = aioble.decode_services.decode_adv_data(payload, 0x09) # AD Type: Complete Local Name
    return str(n[0], 'utf-8') if n else ''

def decode_services(payload):
    services = []
    # Incomplete List of 16-bit Service UUIDs
    for u in aioble.decode_services.decode_adv_data(payload, 0x02):
        services.append(bluetooth.UUID(struct.unpack("<h", u)[0]))
    # Complete List of 16-bit Service UUIDs
    for u in aioble.decode_services.decode_adv_data(payload, 0x03):
        services.append(bluetooth.UUID(struct.unpack("<h", u)[0]))
    # Incomplete List of 128-bit Service UUIDs
    for u in aioble.decode_services.decode_adv_data(payload, 0x06):
        services.append(bluetooth.UUID(u))
    # Complete List of 128-bit Service UUIDs
    for u in aioble.decode_services.decode_adv_data(payload, 0x07):
        services.append(bluetooth.UUID(u))
    return services


class BLEManager:
    def __init__(self, ble_name="ESP32_Dual_AIOBLE"):
        self.ble_name = ble_name
        self.peripheral_advertiser_task = None
        self.peripheral_connection = None
        self.peripheral_rx_char = None
        self.peripheral_tx_char = None

        self.central_connections = {} # {device_name: connection_object}
        self.central_devices_info = {} # {device_name: {'conn': conn_obj, 'services': {}, 'chars': {}}}
        self.target_devices = [
            (config.TARGET_DEVICE_1_NAME, config.TARGET_DEVICE_1_SERVICE_UUID, config.TARGET_DEVICE_1_CHAR_UUID_WRITE, config.TARGET_DEVICE_1_CHAR_UUID_NOTIFY),
            (config.TARGET_DEVICE_2_NAME, config.TARGET_DEVICE_2_SERVICE_UUID, config.TARGET_DEVICE_2_CHAR_UUID_WRITE, config.TARGET_DEVICE_2_CHAR_UUID_NOTIFY)
        ]
        self.desired_central_connections = len(self.target_devices)

        # 初始化aioble
        aioble.core.active(True)
        print("BLE Manager initialized with aioble.")

    async def _peripheral_advertiser(self):
        # 定义外设的服务和特性
        service = aioble.Service(config.SERVICE_UUID_PERIPHERAL)
        self.peripheral_rx_char = aioble.Characteristic(
            service, config.CHAR_UUID_PERIPHERAL_RX, read=False, write=True, notify=False, indicate=False
        )
        self.peripheral_tx_char = aioble.Characteristic(
            service, config.CHAR_UUID_PERIPHERAL_TX, read=True, write=False, notify=True, indicate=False
        )
        aioble.core.register_services(service)

        print("Peripheral services registered.")

        adv_data = aioble.advertising.encode_name(self.ble_name) + \
                   aioble.advertising.encode_services([config.SERVICE_UUID_PERIPHERAL])

        # 启动广播循环
        while True:
            try:
                # 0 for don't wait for connection, 100_000 for 100ms interval
                async with aioble.advertising.advertise(
                    100_000, adv_data=adv_data
                ) as connection:
                    self.peripheral_connection = connection
                    print(f"Peripheral connected by {connection.device}")
                    # 处理外设连接的读写事件
                    async for request in connection.requests():
                        if request.is_peer_write and request.characteristic is self.peripheral_rx_char:
                            data = await request.read()
                            print(f"Peripheral received data from {connection.device}: {data.decode()}")
                            # TODO: 处理接收到的数据，例如通过MQTT转发
                        # elif request.is_peer_read and request.characteristic is self.peripheral_tx_char:
                        #     # 如果有读请求，可以发送数据，但通常notify更常用
                        #     pass
            except asyncio.CancelledError:
                print("Peripheral advertising task cancelled.")
                break
            except Exception as e:
                print(f"Peripheral advertising error: {e}")
            finally:
                self.peripheral_connection = None
                print("Peripheral disconnected, restarting advertisement.")
                await asyncio.sleep_ms(100) # 短暂等待以避免立即重新广播

    async def peripheral_send_data(self, data):
        if self.peripheral_connection and self.peripheral_tx_char:
            try:
                # notify() 是一个协程，需要 await
                await self.peripheral_tx_char.notify(self.peripheral_connection, data)
                print(f"Peripheral sent data: {data.decode()}")
            except Exception as e:
                print(f"Failed to send peripheral data: {e}")
        else:
            print("No peripheral connection or tx_char available to send data.")

    async def _central_scanner_and_connector(self):
        while len(self.central_connections) < self.desired_central_connections:
            print("Starting BLE scan for target devices...")
            try:
                # 扫描设备
                async with aioble.scan(
                    config.SCAN_DURATION_MS,
                    interval_us=config.SCAN_INTERVAL_US,
                    window_us=config.SCAN_WINDOW_US
                ) as scanner:
                    async for result in scanner:
                        addr_str = result.device.addr_hex
                        device_name = result.name()
                        device_services = result.services()

                        # 检查是否是我们想要连接的设备且尚未连接
                        for target_name, target_service_uuid, _, _ in self.target_devices:
                            if device_name == target_name and \
                                target_service_uuid in device_services and \
                                device_name not in self.central_connections:
                                print(f"Found target device: {device_name} ({addr_str}), RSSI: {result.rssi}")
                                try:
                                    print(f"Attempting to connect to {device_name}...")
                                    connection = await result.device.connect()
                                    self.central_connections[device_name] = connection
                                    self.central_devices_info[device_name] = {'conn': connection, 'services': {}, 'chars': {}}
                                    print(f"Central connected to {device_name} ({addr_str})")
                                    # 启动该连接的 GATT 发现和数据交互任务
                                    asyncio.create_task(self._handle_central_connection(device_name, connection))
                                    if len(self.central_connections) >= self.desired_central_connections:
                                        print("All target devices connected, stopping scan.")
                                        return # 退出扫描循环
                                except asyncio.TimeoutError:
                                    print(f"Connection to {device_name} timed out.")
                                except Exception as e:
                                    print(f"Failed to connect to {device_name}: {e}")
            except asyncio.CancelledError:
                print("Central scanning task cancelled.")
                break
            except Exception as e:
                print(f"Central scanning error: {e}")

            if len(self.central_connections) < self.desired_central_connections:
                print("Scan finished, not all target devices connected. Retrying scan in 5 seconds...")
                await asyncio.sleep(5) # 等待一段时间再重新扫描

    async def _handle_central_connection(self, device_name, connection):
        try:
            # 处理连接断开事件
            async for event, data in connection.events():
                if event == aioble.Event.DISCONNECTED:
                    print(f"Central disconnected from {device_name}.")
                    if device_name in self.central_connections:
                        del self.central_connections[device_name]
                        del self.central_devices_info[device_name]
                    # 重新启动扫描和连接，尝试重新连接
                    asyncio.create_task(self._central_scanner_and_connector())
                    break # 退出当前连接处理循环

                elif event == aioble.Event.GATTC_SERVICE_DISCOVERED:
                    service = data
                    print(f"  Service discovered for {device_name}: {service.uuid}")
                    self.central_devices_info[device_name]['services'][service.uuid] = service
                    # 发现特性
                    for char in await service.discover_characteristics():
                        print(f"    Characteristic discovered: {char.uuid}")
                        self.central_devices_info[device_name]['chars'][char.uuid] = char
                        # 如果是通知特性，订阅
                        for target_name, _, _, target_char_notify_uuid in self.target_devices:
                            if target_name == device_name and char.uuid == target_char_notify_uuid:
                                if char.props & bluetooth.Characteristic.PROP_NOTIFY:
                                    await char.subscribe(notify=True)
                                    print(f"      Subscribed to notifications for {device_name} char {char.uuid}")
                                    # 启动一个协程来处理通知
                                    asyncio.create_task(self._handle_notification(device_name, char))
                                break # 找到并处理了通知特性，跳出内部循环

                elif event == aioble.Event.GATTC_CHARACTERISTIC_READ:
                    char, data_read = data
                    print(f"  Read from {device_name} char {char.uuid}: {data_read.decode()}")
                    # TODO: 处理读取到的数据，例如通过MQTT转发

                # aioble内部处理了通知的事件，直接通过char.subscribe()后的异步迭代器获取

        except asyncio.CancelledError:
            print(f"Central connection handler for {device_name} cancelled.")
        except Exception as e:
            print(f"Error handling central connection {device_name}: {e}")
            if device_name in self.central_connections:
                await self.central_connections[device_name].disconnect() # 断开连接，触发DISCONNECTED事件
                del self.central_connections[device_name]
                del self.central_devices_info[device_name]
            asyncio.create_task(self._central_scanner_and_connector()) # 尝试重新连接

    async def _handle_notification(self, device_name, characteristic):
        try:
            async for data in characteristic.notifications():
                print(f"Central received notification from {device_name} char {characteristic.uuid}: {data.decode()}")
                # TODO: 处理接收到的通知数据，例如通过MQTT转发
                # self.mqtt_client.publish(config.MQTT_PUB_TOPIC, f"BLE_NOTIFY_FROM_{device_name}:{data.decode()}")
        except asyncio.CancelledError:
            print(f"Notification handler for {device_name} cancelled.")
        except Exception as e:
            print(f"Error in notification handler for {device_name}: {e}")


    async def central_write_data(self, target_device_name, data):
        if target_device_name in self.central_devices_info:
            device_info = self.central_devices_info[target_device_name]
            for target_name, _, target_char_write_uuid, _ in self.target_devices:
                if target_name == target_device_name and target_char_write_uuid in device_info['chars']:
                    char = device_info['chars'][target_char_write_uuid]
                    try:
                        # write() 是一个协程，需要 await
                        await char.write(data, response=False) # response=False for write_no_response
                        print(f"Central wrote data to {target_device_name}: {data.decode()}")
                        return True
                    except Exception as e:
                        print(f"Failed to write data to {target_device_name}: {e}")
                        return False
            print(f"Write characteristic not found for {target_device_name}.")
            return False
        else:
            print(f"No active connection to device: {target_device_name}")
            return False

    async def ble_loop(self):
        # 启动外设广播任务
        self.peripheral_advertiser_task = asyncio.create_task(self._peripheral_advertiser())
        # 启动主机扫描和连接任务
        asyncio.create_task(self._central_scanner_and_connector())

        while True:
            # 可以在这里添加一些周期性的BLE相关检查或任务
            await asyncio.sleep(5)
          
