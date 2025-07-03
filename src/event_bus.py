# event_bus.py
import asyncio
class EventBus:
    def __init__(self):
        self._listeners = {} # {event_name: [listener_callback, ...]}

    def subscribe(self, event_name, callback):
        """
        订阅一个事件。
        :param event_name: 事件名称（字符串）。
        :param callback: 当事件发生时调用的函数。
        """
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        if callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)
        print(f"Subscribed to event: {event_name} by {callback.__name__}")

    def unsubscribe(self, event_name, callback):
        """
        取消订阅一个事件。
        """
        if event_name in self._listeners and callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)
            print(f"Unsubscribed from event: {event_name} by {callback.__name__}")

    async def publish(self, event_name, *args, **kwargs):
        """
        发布一个事件，异步调用所有订阅者的回调。
        :param event_name: 事件名称。
        :param args: 传递给回调的位置参数。
        :param kwargs: 传递给回调的关键字参数。
        """
        if event_name in self._listeners:
            # 确保回调是异步调用的，且不阻塞事件循环
            for callback in self._listeners[event_name]:
                try:
                    # 如果回调是协程，则创建任务；否则直接调用
                    if type(callback).__name__ == 'generator':
                        asyncio.create_task(callback(*args, **kwargs))
                    else:
                        callback(*args, **kwargs)
                except Exception as e:
                    print(f"Error in event listener for {event_name}: {e}")
        # print(f"Event published: {event_name} with args: {args}, kwargs: {kwargs}")

# 创建一个全局事件总线实例
event_bus = EventBus()