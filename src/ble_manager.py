# ble_manager.py
import uasyncio as asyncio
import aioble
import bluetooth
import time
import struct
from micropython import const
# from settings_manager import settings_manager # 不再直接导入全局实例，而是通过构造函数传递或事件总线
import config
from event_bus import event_bus # <-- 导入事件总线

# ... (decode_name, decode_services 函数保持不变) ...

class BLEManager:
    # 构造函数中可以注入 event_bus 和 settings_manager
    def __init__(self, ble_name="ESP32_Dual_AIOBLE", settings_manager_instance=None):
        self.ble_name = ble_name
        self.settings_manager = settings_manager_instance # 接收注入的设置管理器实例
        if self.settings_manager is None:
            raise ValueError("SettingsManager instance must be provided to BLEManager.")

        self.peripheral_advertiser_task = None
        self.peripheral_connection = None
        self.peripheral_rx_char = None
        self.peripheral_tx_char = None

        self.config_service = aioble.Service(config.SERVICE_UUID_CONFIG)
        self.config_data_char = aioble.Characteristic(
            self.config_service, config.CHAR_UUID_CONFIG_DATA,
            read=True, write=True, notify=False, indicate=False
        )
        aioble.register_services(self.config_service)
        print("Config service registered.")
        # 设置特性初始值，确保在PC/手机读取时能获取到当前配置
        self.config_data_char.write(self.settings_manager.get_all_settings_json().encode())

        self.central_connections = {}
        self.central_devices_info = {}
        self.target_devices = [
            (config.TARGET_DEVICE_1_NAME, config.TARGET_DEVICE_1_SERVICE_UUID, config.TARGET_DEVICE_1_CHAR_UUID_WRITE, config.TARGET_DEVICE_1_CHAR_UUID_NOTIFY),
            (config.TARGET_DEVICE_2_NAME, config.TARGET_DEVICE_2_SERVICE_UUID, config.TARGET_DEVICE_2_CHAR_UUID_WRITE, config.TARGET_DEVICE_2_CHAR_UUID_NOTIFY)
        ]
        self.desired_central_connections = len(self.target_devices)

        # aioble.active(True)
        print("BLE Manager initialized with aioble.")

    async def _peripheral_advertiser(self):
        peripheral_service = aioble.Service(config.SERVICE_UUID_PERIPHERAL)
        self.peripheral_rx_char = aioble.Characteristic(
            peripheral_service, config.CHAR_UUID_PERIPHERAL_RX, read=False, write=True, notify=False, indicate=False
        )
        self.peripheral_tx_char = aioble.Characteristic(
            peripheral_service, config.CHAR_UUID_PERIPHERAL_TX, read=True, write=False, notify=True, indicate=False
        )
        aioble.register_services(peripheral_service)

        print("Peripheral services registered.")

        # adv_data = aioble.advertising.encode_name(self.ble_name) + \
        #            aioble.advertising.encode_services([config.SERVICE_UUID_CONFIG])
                #    aioble.advertising.encode_services([config.SERVICE_UUID_PERIPHERAL, config.SERVICE_UUID_CONFIG])

        while True:
            try:
                print("Starting BLE peripheral advertising...")
                async with await aioble.advertise(
                    100_000, 
                    name = self.ble_name,
                    services=[config.SERVICE_UUID_CONFIG],
                    connectable=True 
                    # adv_data=adv_data
                ) as connection:
                    self.peripheral_connection = connection
                    print(f"Peripheral connected by {connection.device} ")
                    # 发布连接事件
                    await event_bus.publish("ble_peripheral_connected", connection.device.addr_hex())

                    while connection.is_connected():
                        await asyncio.sleep(2)  # 保持连接状态
   
                    # async for request in connection.requests():
                    #         print(f"Received request from ###########{connection.device}: {request}")
                    #         if request.is_peer_write:
                    #             if request.characteristic is self.peripheral_rx_char:
                    #                 data = await request.read()
                    #                 print(f"Peripheral (App) received data from {connection.device}: {data.decode()}")
                    #                 # 发布 BLE 外设接收数据事件
                    #                 await event_bus.publish("ble_peripheral_data_received", data.decode())
                    #             elif request.characteristic is self.config_data_char:
                    #                 data = await request.read()
                    #                 print(f"Peripheral (Config) received data from {connection.device}: {data.decode()}")
                    #                 # 发布配置更新请求事件
                    #                 await event_bus.publish("settings_update_request", data.decode())

                    #         elif request.is_peer_read and request.characteristic is self.config_data_char:
                    #             # 客户端读取配置特性时，返回当前保存的配置
                    #             request.write(self.settings_manager.get_all_settings_json().encode())
                    #             print(f"Peripheral (Config) sent current settings to {connection.device}.")

            except asyncio.CancelledError:
                print("Peripheral advertising task cancelled.")
                break
            except Exception as e:
                print(f"Peripheral advertising error: {e}")
            finally:
                self.peripheral_connection = None
                # 发布断开连接事件
                await event_bus.publish("ble_peripheral_disconnected", connection.device.addr_hex())
                print("Peripheral disconnected, restarting advertisement.")
                await asyncio.sleep_ms(100)

    async def peripheral_send_data(self, data):
        if self.peripheral_connection and self.peripheral_tx_char:
            try:
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
                async with aioble.scan(
                    config.SCAN_DURATION_MS,
                    interval_us=config.SCAN_INTERVAL_US,
                    window_us=config.SCAN_WINDOW_US
                ) as scanner:
                    async for result in scanner:
                        addr_str = result.device.addr_hex()
                        device_name = result.name()
                        device_services = result.services()
                        # manufacturer_data = [f"{man_id:04X}" for man_id, man_data in result.manufacturer()]
                        # result.adv_data
                        
                        print(f"Found device:{result.name()} ({addr_str}), RSSI: {result.rssi}")

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
                                    # 发布主机连接事件
                                    await event_bus.publish("ble_central_connected", device_name, addr_str)
                                    asyncio.create_task(self._handle_central_connection(device_name, connection))
                                    if len(self.central_connections) >= self.desired_central_connections:
                                        print("All target devices connected, stopping scan.")
                                        return
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
                await asyncio.sleep(5)

    async def _handle_central_connection(self, device_name, connection):
        try:
            async for event, data in connection.events():
                if event == aioble.Event.DISCONNECTED:
                    print(f"Central disconnected from {device_name}.")
                    if device_name in self.central_connections:
                        del self.central_connections[device_name]
                        del self.central_devices_info[device_name]
                    # 发布主机断开连接事件
                    await event_bus.publish("ble_central_disconnected", device_name)
                    asyncio.create_task(self._central_scanner_and_connector())
                    break

                elif event == aioble.Event.GATTC_SERVICE_DISCOVERED:
                    service = data
                    print(f"  Service discovered for {device_name}: {service.uuid}")
                    self.central_devices_info[device_name]['services'][service.uuid] = service
                    for char in await service.discover_characteristics():
                        print(f"    Characteristic discovered: {char.uuid}")
                        self.central_devices_info[device_name]['chars'][char.uuid] = char
                        for target_name, _, _, target_char_notify_uuid in self.target_devices:
                            if target_name == device_name and char.uuid == target_char_notify_uuid:
                                if char.props & bluetooth.Characteristic.PROP_NOTIFY:
                                    await char.subscribe(notify=True)
                                    print(f"      Subscribed to notifications for {device_name} char {char.uuid}")
                                    asyncio.create_task(self._handle_notification(device_name, char))
                                break

                elif event == aioble.Event.GATTC_CHARACTERISTIC_READ:
                    char, data_read = data
                    print(f"  Read from {device_name} char {char.uuid}: {data_read.decode()}")
                    # 发布主机读取数据事件
                    await event_bus.publish("ble_central_data_read", device_name, char.uuid, data_read.decode())

        except asyncio.CancelledError:
            print(f"Central connection handler for {device_name} cancelled.")
        except Exception as e:
            print(f"Error handling central connection {device_name}: {e}")
            if device_name in self.central_connections:
                await self.central_connections[device_name].disconnect()
                del self.central_connections[device_name]
                del self.central_devices_info[device_name]
            asyncio.create_task(self._central_scanner_and_connector())

    async def _handle_notification(self, device_name, characteristic):
        try:
            async for data in characteristic.notifications():
                print(f"Central received notification from {device_name} char {characteristic.uuid}: {data.decode()}")
                # 发布主机接收通知事件
                await event_bus.publish("ble_central_notification_received", device_name, characteristic.uuid, data.decode())
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
                        await char.write(data, response=False)
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
        self.peripheral_advertiser_task = asyncio.create_task(self._peripheral_advertiser())
        asyncio.create_task(self._central_scanner_and_connector())

        while True:
            await asyncio.sleep(5)