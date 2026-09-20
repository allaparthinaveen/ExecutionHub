from abc import ABC, abstractmethod
import requests
import structlog
from trading_engine.config.settings import settings

logger = structlog.get_logger("trading_engine.notifications")

class NotificationProvider(ABC):
    @abstractmethod
    def send_info(self, message: str) -> bool:
        pass
        
    @abstractmethod
    def send_warning(self, message: str) -> bool:
        pass
        
    @abstractmethod
    def send_error(self, message: str) -> bool:
        pass
        
    @abstractmethod
    def send_critical(self, message: str) -> bool:
        pass

class TelegramNotificationProvider(NotificationProvider):
    def __init__(self):
        self.token = settings.tg_bot_token
        self.chat_id = settings.tg_chat_id
        
        if not self.token or not self.chat_id:
            logger.warning("TELEGRAM_NOT_CONFIGURED", reason="Missing tg_bot_token or tg_chat_id in settings")
            self.enabled = False
        else:
            self.enabled = True
            self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def _send(self, message: str, prefix: str) -> bool:
        if not self.enabled:
            return False
            
        text = f"{prefix}\n\n{message}"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            r = requests.post(self.base_url, json=payload, timeout=5)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error("TELEGRAM_SEND_FAILED", error=str(e))
            return False

    def send_info(self, message: str) -> bool:
        return self._send(message, "🟢 INFO")
        
    def send_warning(self, message: str) -> bool:
        return self._send(message, "🟡 WARNING")
        
    def send_error(self, message: str) -> bool:
        return self._send(message, "🔴 ERROR")
        
    def send_critical(self, message: str) -> bool:
        return self._send(message, "🚨 CRITICAL")

class ConsoleNotificationProvider(NotificationProvider):
    def send_info(self, message: str) -> bool:
        print(f"[INFO NOTIFICATION]\n{message}")
        return True
        
    def send_warning(self, message: str) -> bool:
        print(f"[WARNING NOTIFICATION]\n{message}")
        return True
        
    def send_error(self, message: str) -> bool:
        print(f"[ERROR NOTIFICATION]\n{message}")
        return True
        
    def send_critical(self, message: str) -> bool:
        print(f"[CRITICAL NOTIFICATION]\n{message}")
        return True
