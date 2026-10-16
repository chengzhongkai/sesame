import asyncio
import time
from bleak import BleakClient, BleakError
from Crypto.Cipher import AES
from Crypto.Hash import CMAC
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 常量定义 ---
CONNECTION_TIMEOUT = 20.0
CMD_CHARACTERISTIC_UUID = "16860002-a5ae-9856-b6d3-dbb4c676993e"
STATUS_CHARACTERISTIC_UUID = "16860003-a5ae-9856-b6d3-dbb4c676993e"
ITEM_CODE_LOGIN = 2
ITEM_CODE_LOCK = 82
ITEM_CODE_UNLOCK = 83



class SesameController:
    def __init__(self, mac_address, device_secret_hex):
        self.mac_address = mac_address
        self.device_secret = bytes.fromhex(device_secret_hex)
        self.client = None
        self.random_code = None
        self.session_key = None
        self.tx_counter = 0
        self.rx_counter = 0
        self.random_code_received_event = asyncio.Event()

    async def connect(self):
        logging.info(f"正在连接到 {self.mac_address}...")
        try:
            self.client = BleakClient(self.mac_address, timeout=CONNECTION_TIMEOUT)
            await self.client.connect()
            await self.client.start_notify(STATUS_CHARACTERISTIC_UUID, self._notification_handler)
            logging.info("连接成功并已开启通知。")
            return True
        except Exception as e:
            logging.error(f"连接失败: {e}")
            return False

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logging.info("已断开连接。")

    def _notification_handler(self, sender, data: bytes):
        logging.info(f"[通知] 收到原始数据: {data.hex()}")

        if data[0] == 5:
            decrypted_data = self.decode(data[1:])
            data  = data[0:1]+decrypted_data
            self.rx_counter += 1
            logging.info(f"[通知] 收到原始数据decode: {data.hex()}")
        
        match data[1]:
            case 7:
                logging.info("response msg")
                
                match data[2]:
                    case 2:
                        logging.info("login")
                    case 4:
                        logging.info("history")
                    case 5:
                        logging.info("version")
            case 8:
                logging.info("public msg")
                match data[2]:
                    case 14:
                        logging.info("init sent random code")
                    case 80:
                        logging.info("setting")
                    case 81:
                        logging.info("status")

        if not self.random_code_received_event.is_set() and data.startswith(b'\x03\x08\x0e'):
            self.random_code = data[3:7]
            logging.info(f"成功捕获到 random_code: {self.random_code.hex()}")
            self.random_code_received_event.set()

    async def _send_packet(self, data: bytes):
        await self.client.write_gatt_char(CMD_CHARACTERISTIC_UUID, data, response=False)

    def generate_session_key(self):
        """最终确认的会话密钥生成算法"""
        logging.info("正在生成会话密钥...")

        token = CMAC.new(self.device_secret,self.random_code, ciphermod=AES)
  
        self.session_key = bytes.fromhex(token.digest().hex())

        logging.info(f"已生成正确的会话密钥 (Token): {self.session_key.hex()}")

    async def login(self):
        logging.info("正在开始最终的登录流程...")
        try:
            await asyncio.wait_for(self.random_code_received_event.wait(), timeout=10.0)
            self.generate_session_key()
            pincode = self.session_key[:4]
            login_payload = bytes([ITEM_CODE_LOGIN]) + pincode
            packet_to_send = b'\x03' + login_payload
            logging.info(f"发送标准登录指令: {packet_to_send.hex()}")
            await self._send_packet(packet_to_send)
            await asyncio.sleep(1.0)
            logging.info("🎉 登录流程成功完成！")
            return True
        except Exception as e:
            logging.error(f"登录失败: {e}")
            return False
        
    def encode(self, data: bytes):
        nonce = bytes.fromhex(f"{self.tx_counter.to_bytes(9, "little").hex()}{self.random_code.hex()}")
        cobj = AES.new(self.session_key, AES.MODE_CCM, nonce = nonce,mac_len=4)
        cobj.update(bytes([0]))
        enc_data, tag = cobj.encrypt_and_digest(data)
        tag4 = tag[0:4]

        return enc_data+ tag4
       
    def decode(self, data: bytes):
        nonce = bytes.fromhex(f"{self.rx_counter.to_bytes(9, "little").hex()}{self.random_code.hex()}")
        cobj = AES.new(self.session_key, AES.MODE_CCM, nonce = nonce,mac_len=4)
        cobj.update(bytes([0]))
        decode_data = cobj.decrypt(data[0:-4])

        return decode_data  
        
    async def _send_command(self, item_code: int, parameter: bytes = b''):
        if not self.session_key:
            logging.error("未登录，无法发送指令。")
            return
        try:
            command = self.encode(bytes([item_code]) + parameter)
          
            self.tx_counter += 1
            
            packet_to_send = b'\x05' + command
            op_str = {ITEM_CODE_UNLOCK: "开锁", ITEM_CODE_LOCK: "上锁"}.get(item_code, "未知操作")
            
            logging.info(f"发送 AES-GCM 加密后的'{op_str}'指令: {packet_to_send.hex()}")
            await self._send_packet(packet_to_send)
            logging.info(f"'{op_str}' 指令已发送。")
        except Exception as e:
            logging.error(f"发送指令'{op_str}'失败: {e}")

    async def lock(self):
        # 官方App和pysesameos2都使用了简化的payload
        await self._send_command(ITEM_CODE_LOCK, b'\x03abc')

    async def unlock(self):
        await self._send_command(ITEM_CODE_UNLOCK, b'\x03abc')

async def main():
    ################################################################
    DEVICE_SECRET_HEX = "<DEVICE_SECRET_HEX>  # pi/config.json 参照（git 管理外）"
    SESAME_MAC_ADDRESS = "FA:EE:B1:3F:13:0F"
        
    controller = None
    try:
        controller = SesameController(SESAME_MAC_ADDRESS, DEVICE_SECRET_HEX)
        if await controller.connect():
            if await controller.login():
            #     await asyncio.sleep(1.0)
            #     logging.info("初始化完成，现在可以控制您的芝麻锁了！")
                
                while True:
                    action = input("\n请输入指令 'login','lock', 'unlock', 或 'exit': ").lower().strip()

                    if action == "lock": await controller.lock()
                    elif action == "login": await controller.login()
                    elif action == "unlock": await controller.unlock()
                    elif action == "exit": break
                    await asyncio.sleep(2.0)
                
                logging.info("操作流程结束。")
    except Exception as e:
        logging.error(f"程序运行中发生意外错误: {e}")
    finally:
        if controller: await controller.disconnect()

if __name__ == "__main__":
    asyncio.run(main())