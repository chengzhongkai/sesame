# settings_manager.py
import ujson
import asyncio
import os
from event_bus import event_bus # <-- 导入事件总线

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "wifi_ssid": "YourWiFiSSID",
    "wifi_password": "YourWiFiPassword",
    "mqtt_broker": "your_mqtt_broker_ip",
    "mqtt_port": 1883,
    "mqtt_client_id": "esp32_default_client",
    "mqtt_pub_topic": "esp32/data",
    "mqtt_sub_topic": "esp32/cmd",
    "sensor_read_interval_s": 60
}

class SettingsManager:
    def __init__(self):
        self._settings = {}
        self.load_settings()
        # 订阅配置更新请求事件
        event_bus.subscribe("settings_update_request", self._handle_settings_update_request)

    def load_settings(self):
        # ... (保持不变) ...
        try:
            with open(SETTINGS_FILE, "r") as f:
                loaded_settings = ujson.load(f)
                self._settings = DEFAULT_SETTINGS.copy()
                self._settings.update(loaded_settings)
                print(f"Settings loaded from {SETTINGS_FILE}")
        except OSError:
            print(f"'{SETTINGS_FILE}' not found, using default settings.")
            self._settings = DEFAULT_SETTINGS.copy()
            self.save_settings()
        except ValueError:
            print(f"Error parsing '{SETTINGS_FILE}', using default settings and overwriting.")
            self._settings = DEFAULT_SETTINGS.copy()
            self.save_settings()

    def save_settings(self):
        # ... (保持不变) ...
        try:
            with open(SETTINGS_FILE, "w") as f:
                ujson.dump(self._settings, f)
            print(f"Settings saved to {SETTINGS_FILE}")
            # 发布设置已更新事件
            asyncio.create_task(event_bus.publish("settings_updated", self._settings))
        except Exception as e:
            print(f"Error saving settings to {SETTINGS_FILE}: {e}")

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        if key in DEFAULT_SETTINGS:
            self._settings[key] = value
            print(f"Setting '{key}' updated in memory to '{value}'")
            return True
        else:
            print(f"Attempted to set unknown setting: {key}")
            return False

    async def _handle_settings_update_request(self, json_string): # 这是异步回调
        """从 JSON 字符串更新设置，由事件触发。"""
        if self.update_settings_from_json(json_string):
            # 成功更新和保存后，可以通知主程序或其他模块进行重启或重新配置
            # 这里的 settings_manager.update_settings_from_json 已经包含了 save_settings()
            pass


    def update_settings_from_json(self, json_string): # 同步方法供内部调用
        try:
            new_data = ujson.loads(json_string)
            updated = False
            for key, value in new_data.items():
                if self.set(key, value):
                    updated = True
            if updated:
                self.save_settings() # 只有当有实际更新时才保存
                print("Settings updated and saved from BLE.")
                return True
            return False
        except ValueError as e:
            print(f"Invalid JSON received for settings: {e}")
            return False
        except Exception as e:
            print(f"Error updating settings from JSON: {e}")
            return False

    def get_all_settings_json(self):
        return ujson.dumps(self._settings)

# 初始化一个全局设置管理器实例
settings_manager = SettingsManager() # 确保在主程序中它被正确初始化并加载设置