# ESP32 MicroPython BLE/WiFi/MQTT 项目设计文档

## 1. 项目概述

* **目标**: 在 ESP32 上实现 BLE 外设/主机双角色、WiFi 连接和 MQTT 通信，用于物联网设备控制和数据传输。
* **核心功能**:
    * BLE 外设模式：广播信息，允许其他 BLE 设备连接并进行数据交互。
    * BLE 主机模式：扫描并连接到两台特定的 BLE 设备，进行数据读写和接收通知。
    * WiFi 连接管理：稳定连接到无线网络。
    * MQTT 通信：发布传感器数据，订阅控制命令。
* **预期用途**: （例如：智能家居设备控制、工业数据采集等）

## 2. 技术选型

* **硬件平台**: ESP32 (MicroPython 兼容模块)
* **固件**: MicroPython 最新稳定版
* **主要库**:
    * **BLE**: `aioble` (推荐，基于 `uasyncio` 的异步 BLE 库)
    * **WiFi**: `network` 模块
    * **MQTT**: `umqtt.simple`
    * **异步I/O**: `uasyncio` (MicroPython 内置)

## 3. 文件及任务组织方法

### 3.1 文件结构
```
project_root/
├── main.py             # 程序主入口，启动所有异步任务
├── config.py           # 所有配置信息（WiFi SSID、MQTT Broker、BLE UUIDs等）
├── wifi_manager.py     # WiFi 连接和重连逻辑
├── mqtt_client.py      # MQTT 连接、发布、订阅和消息处理逻辑
├── ble_manager.py      # 核心: 封装 BLE 外设和主机模式的所有逻辑 (使用 aioble)
└── lib/                # MicroPython 外部库存放目录 (例如: aioble, umqtt)
├── aioble/
│   └── ...
└── umqtt/
└── simple.py
```
### 3.2 任务组织

* **开发阶段**:
    1.  需求分析与设计 (当前阶段)
    2.  WiFi 模块独立开发与测试
    3.  MQTT 模块独立开发与测试
    4.  BLE 外设模式开发与测试
    5.  BLE 主机模式开发与测试 (连接一台设备)
    6.  BLE 主机模式扩展 (连接第二台设备)
    7.  各模块集成与联调 (BLE <-> MQTT 桥接、MQTT -> BLE 控制)
    8.  优化、部署与稳定性测试
    9.  维护与迭代
* **管理工具**:
    * **版本控制**: Git (GitHub/GitLab)
    * **任务追踪**: （可选：Trello / GitHub Issues / `TODO.md` 文件）
* **异步编程**:
    * 所有长时间运行的操作（网络连接、BLE 扫描/广告、数据收发）都将使用 `uasyncio` 协程实现，确保非阻塞运行。
    * BLE 事件处理通过 `aioble` 的异步 API 简化。

## 4. BLE 双角色实现细节 (使用 aioble)

### 4.1 核心概念

* **BLE 外设 (Peripheral)**: ESP32 广播其服务并等待连接。
* **BLE 主机 (Central)**: ESP32 扫描并连接目标设备。
* **`aioble.core.active(True)`**: 激活 BLE。
* **`aioble.advertising.advertise()`**: 用于外设模式的异步广播。
* **`aioble.gap.scan()`**: 用于主机模式的异步扫描。
* **`connection.device.connect()`**: 用于主机模式连接到扫描到的设备。
* **`connection.events()`**: 处理连接生命周期事件（断开连接）。
* **`service.discover_characteristics()`**: 发现连接设备的服务和特性。
* **`characteristic.read()` / `write()` / `subscribe()`**: 与特性进行交互。

### 4.2 外设模式 (`_peripheral_advertiser` 协程)

* **服务定义**: 通过 `aioble.Service` 和 `aioble.Characteristic` 定义服务 UUID、特性 UUID (RX/TX) 和权限。
* **广播**: `aioble.advertising.advertise` 在 `async with` 语句中启动，当有连接时，上下文管理器结束，外设停止广播。断开连接后自动重新开始广播。
* **数据接收**: 在连接的 `async for request in connection.requests()` 循环中监听写入请求 (`request.is_peer_write`)，通过 `request.read()` 获取数据。
* **数据发送**: 通过 `self.peripheral_tx_char.notify(self.peripheral_connection, data)` 向连接的主机发送通知。

### 4.3 主机模式 (`_central_scanner_and_connector` 及 `_handle_central_connection` 协程)

* **目标设备**: 预设要连接的 `TARGET_DEVICE_1_NAME` 和 `TARGET_DEVICE_2_NAME`，以及它们的服务/特性 UUID。
* **扫描**: `aioble.scan` 在 `async with` 语句中启动，遍历 `scanner` 中的 `result` 对象。
* **连接逻辑**:
    * 在扫描结果中匹配目标设备的名称和所需的服务 UUID。
    * 如果找到未连接的目标设备，尝试通过 `result.device.connect()` 建立连接。
    * 连接成功后，启动独立的协程 (`_handle_central_connection`) 来管理该连接。
    * 达到所需连接数量后停止扫描，否则在扫描结束后重新启动扫描。
* **连接处理 (`_handle_central_connection`)**:
    * 在 `async for event, data in connection.events()` 中处理连接的事件，特别是 `aioble.Event.DISCONNECTED`。
    * **服务/特性发现**: 连接后，通过 `connection.discover_services()` 和 `service.discover_characteristics()` 发现远程设备的服务和特性。
    * **订阅通知**: 如果特性支持通知，通过 `char.subscribe(notify=True)` 订阅，并启动独立的协程 (`_handle_notification`) 来异步处理接收到的通知数据。
    * **读写数据**: 通过 `characteristic.read()` 和 `characteristic.write(data)` 进行数据交互。

### 4.4 异步协调

* **`main.py`**: 作为主协调器，启动 `WiFiManager`、`MQTTManager` 和 `BLEManager` 的核心异步任务。
* **MQTT <-> BLE 桥接**: MQTT 接收到的控制命令通过 `asyncio.create_task()` 异步调用 `BLEManager` 的方法（如 `central_write_data` 或 `peripheral_send_data`）转发到 BLE 设备。同样，BLE 接收到的数据通过 `MQTTManager` 发布到 MQTT。

## 5. 待办事项与未来展望

* 实现具体的数据格式和协议。
* 增加错误日志记录机制。
* 优化内存使用。
* 考虑掉线重连的策略和超时机制。
* 部署和实际测试。
