-----

好的，我将把事件总线（Event Bus）的设计整理成 Markdown 格式的设计文档，你可以直接将其添加到你的项目文档中。

-----

# 事件总线 (Event Bus) 设计文档

## 1\. 概述

事件总线是本项目中实现模块间 **低耦合通信** 的核心机制。它采用 **发布/订阅 (Publish/Subscribe) 模式**，允许不同模块在不知道彼此具体实现的情况下进行通信。

在 MicroPython 的异步环境（`uasyncio`）中，事件总线尤为重要。它确保了模块能够以非阻塞的方式对其他模块发生的事件做出响应，避免了直接函数调用导致的紧密耦合和潜在的阻塞问题。

## 2\. 目标

  * **解耦模块**: 消除模块间的直接依赖，使各功能模块能够独立开发、测试和维护。
  * **提高可扩展性**: 方便地添加新功能或修改现有功能，而无需修改其依赖或被依赖的模块。
  * **简化异步通信**: 提供一个统一的、基于协程的事件处理机制，简化异步操作的协调。
  * **提高可测试性**: 模块的交互可以通过模拟事件总线进行，使单元测试更加容易。

## 3\. 设计原理

事件总线作为一个中央消息分发器，其工作原理如下：

1.  **发布者 (Publisher)**: 当某个模块（如 `BLEManager` 接收到数据）发生一个特定事件时，它会向事件总线 **发布** 一个事件。发布者不需要知道谁会处理这个事件。
2.  **订阅者 (Subscriber)**: 对某个事件感兴趣的模块（如 `MQTTManager` 需要发送数据，或者 `SettingsManager` 需要处理配置更新）会向事件总线 **订阅** 相应的事件。订阅者不需要知道事件是由哪个模块发布的。
3.  **事件总线 (Event Bus)**: 负责接收所有发布的事件，并将这些事件分发给所有已注册的订阅者。它维护一个事件名称到订阅者回调函数的映射。

## 4\. 实现细节 (`event_bus.py`)

事件总线将在一个独立的 Python 文件 `event_bus.py` 中实现，并创建一个全局的 `EventBus` 实例供其他模块导入使用。

### 4.1 类结构

```python
# event_bus.py
import uasyncio as asyncio

class EventBus:
    def __init__(self):
        self._listeners = {} # 存储事件名称到回调函数列表的映射 {event_name: [listener_callback, ...]}

    def subscribe(self, event_name, callback):
        """
        订阅一个事件。
        :param event_name: 事件的唯一标识名称（字符串）。
        :param callback: 当事件发生时被调用的函数或协程。
        """
        # 实现细节：确保回调函数不重复订阅
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        if callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)
        print(f"Subscribed to event: {event_name} by {callback.__name__}")

    def unsubscribe(self, event_name, callback):
        """
        取消订阅一个事件。
        :param event_name: 事件名称。
        :param callback: 之前订阅时使用的回调函数。
        """
        # 实现细节：从列表中移除回调函数
        if event_name in self._listeners and callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)
            print(f"Unsubscribed from event: {event_name} by {callback.__name__}")

    async def publish(self, event_name, *args, **kwargs):
        """
        发布一个事件，异步触发所有订阅者的回调函数。
        :param event_name: 要发布的事件名称。
        :param args: 传递给订阅者回调的位置参数。
        :param kwargs: 传递给订阅者回调的关键字参数。
        """
        # 实现细节：遍历订阅者并异步调度回调
        if event_name in self._listeners:
            for callback in self._listeners[event_name]:
                try:
                    # 判断回调是否是协程函数，如果是则创建任务，确保非阻塞
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(*args, **kwargs))
                    else:
                        # 如果是普通函数，直接调用
                        callback(*args, **kwargs)
                except Exception as e:
                    print(f"Error in event listener '{callback.__name__}' for event '{event_name}': {e}")
        # print(f"Event published: {event_name}") # 可以添加更多调试信息
# 创建一个全局事件总线实例
event_bus = EventBus()
```

### 4.2 核心方法说明

  * **`__init__(self)`**:
      * 初始化内部字典 `_listeners`，用于存储事件名称和其对应的回调函数列表。
  * **`subscribe(self, event_name, callback)`**:
      * 将 `callback` 函数注册为 `event_name` 事件的监听器。
      * 确保同一个回调函数不会被重复订阅同一个事件。
  * **`unsubscribe(self, event_name, callback)`**:
      * 将 `callback` 函数从 `event_name` 事件的监听器列表中移除。
  * **`publish(self, event_name, *args, **kwargs)`**:
      * 这是异步方法 (`async def`)，因为它需要 `asyncio.create_task` 来调度协程回调。
      * 遍历 `event_name` 的所有订阅者。
      * 对于每个回调函数：
          * 如果回调是**协程函数** (`async def` 定义的)，则使用 `asyncio.create_task()` 创建一个新的任务来执行它，这确保了发布者不会因为等待回调执行而阻塞。
          * 如果回调是**普通函数** (`def` 定义的)，则直接调用它。
      * 包含错误处理，防止单个回调函数的错误影响整个事件分发。

## 5\. 模块间的交互示例

以 `BLEManager` 发布数据，`main.py` 订阅并转发到 `MQTTManager` 为例：

1.  **发布者 (`ble_manager.py`)**:

    ```python
    # 在 BLEManager 内部，当接收到外设数据时
    # ...
    data = await request.read()
    await event_bus.publish("ble_peripheral_data_received", data.decode())
    # ...
    ```

2.  **订阅者 (`main.py`)**:

    ```python
    # 在 main.py 内部定义一个异步回调函数
    async def handle_ble_peripheral_data(data):
        print(f"Main: Received BLE Peripheral data event: {data}")
        mqtt_topic = settings_manager.get("mqtt_pub_topic")
        mqtt_manager_instance.publish(mqtt_topic, f"BLE_PERIPHERAL_RX:{data}")

    # 在 main 函数启动时订阅事件
    event_bus.subscribe("ble_peripheral_data_received", handle_ble_peripheral_data)
    ```

通过这种方式，`BLEManager` 不知道 `MQTTManager` 的存在，`main.py` 作为协调者，实现了事件的桥接。

## 6\. 使用考量与最佳实践

  * **事件命名**: 使用清晰、一致的事件命名约定（例如：`module_action_status`，如 `ble_peripheral_data_received`、`mqtt_connected`、`settings_update_request`）。
  * **参数传递**: 通过事件参数 (`*args`, `**kwargs`) 传递必要的数据。避免传递整个对象，除非确实需要，以减少内存占用和耦合。
  * **异步处理**: 大多数事件回调应设计为协程 (`async def`)，并由 `event_bus.publish` 内部的 `asyncio.create_task` 调度，以确保非阻塞和并发执行。如果回调是同步的，确保其执行时间非常短，避免阻塞事件循环。
  * **错误处理**: 发布者和订阅者都应考虑各自的错误处理。事件总线内部会捕获回调执行时的错误，但更具体的业务逻辑错误应由回调函数自身处理。
  * **过度使用**: 并非所有函数调用都需要通过事件总线。对于模块内部的私有逻辑或不需要解耦的简单、直接调用，直接函数调用仍然是合适的。事件总线主要用于跨模块的、异步的、一对多或多对多的通信场景。

## 7\. 未来扩展

  * **事件过滤**: 在复杂的系统中，可能需要为订阅者提供事件过滤功能，只接收特定条件下的事件。
  * **优先级**: 为回调函数设置优先级，控制事件处理的顺序。
  * **错误恢复策略**: 更复杂的错误处理和重试机制。

-----

通过引入这个事件总线，你的 ESP32 MicroPython 项目将变得更加健壮、灵活和易于维护，这是构建可扩展物联网应用的关键一步。

-----