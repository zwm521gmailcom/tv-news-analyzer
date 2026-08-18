import json
import time
import os
from typing import Optional
from config import settings


class CookieManager:
    def __init__(self):
        self.cookies: dict = {}
        self.is_authenticated: bool = False
        self.source: str = "none"

    # ── 粘贴文件路径：data/cookies.txt ───────────────────────
    @property
    def _paste_path(self) -> str:
        return os.path.join(os.path.dirname(settings.COOKIE_PATH), "cookies.txt")

    def load(self):
        """
        加载优先级：
          1. data/cookies.txt  ← 人工维护的唯一输入源
             - 为空：匿名模式
             - 有内容：解析并同步到 data/cookies.json
          2. data/cookies.json ← 上次保存的 JSON 缓存（仅当 cookies.txt 不存在时）
          3. 匿名模式
        """
        self.cookies = {}
        self.is_authenticated = False
        self.source = "none"
        if self._load_from_paste_file():
            return
        if self._load_from_file():
            return
        print("[CookieManager] 匿名模式运行（无 Cookie）")

    # ── 格式解析 ─────────────────────────────────────────────

    @staticmethod
    def parse_cookie_string(raw: str) -> dict:
        """
        自动识别三种格式：
          1. JSON:       {"key": "value"}
          2. 换行格式:    key=val\nkey2=val2   ← 浏览器 DevTools 粘贴
          3. 分号格式:    key=val; key2=val2   ← 单行字符串
        """
        raw = raw.strip()
        if not raw:
            return {}

        # JSON
        if raw.startswith("{"):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        cookies = {}
        # 换行格式
        if "\n" in raw:
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cookies[k.strip()] = v.strip()
            return cookies

        # 分号格式
        for pair in raw.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    # ── 加载策略 ─────────────────────────────────────────────

    def _load_from_paste_file(self) -> bool:
        """从 data/cookies.txt 加载（用户直接粘贴浏览器 Cookie）"""
        if not os.path.exists(self._paste_path):
            return False
        try:
            with open(self._paste_path, encoding="utf-8") as f:
                raw = f.read()
            if not raw.strip():
                self.cookies = {}
                self.is_authenticated = False
                self.source = "paste_file_empty"
                print("[CookieManager] cookies.txt 为空，匿名模式运行")
                return True

            cookies = self.parse_cookie_string(raw)
            if not cookies:
                self.cookies = {}
                self.is_authenticated = False
                self.source = "paste_file_invalid"
                print("[CookieManager] cookies.txt 无法解析，匿名模式运行")
                return True
            self.cookies = cookies
            self.is_authenticated = True
            self.source = "paste_file"
            self._save_to_file()  # 同步到 cookies.json
            print(f"[CookieManager] 从 cookies.txt 加载 Cookie，条目数: {len(self.cookies)}")
            return True
        except Exception as e:
            self.cookies = {}
            self.is_authenticated = False
            self.source = "paste_file_error"
            print(f"[CookieManager] cookies.txt 加载失败，匿名模式运行: {e}")
            return True

    def _load_from_file(self) -> bool:
        """从 data/cookies.json 加载（上次保存的缓存）"""
        if not os.path.exists(settings.COOKIE_PATH):
            return False
        try:
            with open(settings.COOKIE_PATH) as f:
                data = json.load(f)
            self.cookies = data.get("cookies", {})
            self.is_authenticated = bool(self.cookies)
            self.source = "file"
            print(f"[CookieManager] 从文件加载 Cookie，条目数: {len(self.cookies)}")
            return True
        except Exception as e:
            print(f"[CookieManager] 文件加载失败: {e}")
            return False

    def _save_to_file(self):
        """持久化到 data/cookies.json"""
        os.makedirs(os.path.dirname(settings.COOKIE_PATH), exist_ok=True)
        with open(settings.COOKIE_PATH, "w") as f:
            json.dump({
                "cookies": self.cookies,
                "saved_at": int(time.time()),
                "source": self.source,
            }, f, indent=2)

    # ── 使用 ─────────────────────────────────────────────────

    def get_headers(self) -> dict:
        if not self.cookies:
            return {}
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return {"Cookie": cookie_str}

    def update_from_response(self, set_cookie: Optional[str]):
        """从响应头 set-cookie 更新 Cookie"""
        if not set_cookie:
            return
        for pair in set_cookie.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                self.cookies[k.strip()] = v.strip()
        self._save_to_file()

    def on_auth_error(self):
        """遇到 403 降级到匿名模式"""
        print("[CookieManager] ⚠️  收到 403，降级为匿名模式")
        self.cookies = {}
        self.is_authenticated = False


def inspect_cookie_runtime() -> dict:
    """
    读取当前 Cookie 配置状态，不修改任何文件。

    规则与 CookieManager.load() 保持一致：
    - data/cookies.txt 有内容 -> 使用该内容
    - data/cookies.txt 为空白 -> 匿名模式
    - data/cookies.txt 不存在 -> 回退 data/cookies.json
    - 两者都没有/不可用 -> 匿名模式
    """
    paste_path = os.path.join(os.path.dirname(settings.COOKIE_PATH), "cookies.txt")

    def _anonymous(source: str) -> dict:
        return {
            "anonymous_mode": True,
            "cookie_source": source,
            "cookie_count": 0,
        }

    if os.path.exists(paste_path):
        try:
            with open(paste_path, encoding="utf-8") as f:
                raw = f.read()
            if not raw.strip():
                return _anonymous("paste_file_empty")
            cookies = CookieManager.parse_cookie_string(raw)
            if not cookies:
                return _anonymous("paste_file_invalid")
            return {
                "anonymous_mode": False,
                "cookie_source": "paste_file",
                "cookie_count": len(cookies),
            }
        except Exception:
            return _anonymous("paste_file_error")

    if os.path.exists(settings.COOKIE_PATH):
        try:
            with open(settings.COOKIE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies", {}) or {}
            if cookies:
                return {
                    "anonymous_mode": False,
                    "cookie_source": "file",
                    "cookie_count": len(cookies),
                }
            return _anonymous("file_empty")
        except Exception:
            return _anonymous("file_error")

    return _anonymous("none")
