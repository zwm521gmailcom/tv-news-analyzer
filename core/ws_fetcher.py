"""
TradingView WebSocket 行情实时价格追踪器

协议格式: ~m~{length}~m~{payload}
心跳格式: ~m~{n}~m~~h~{seq}  （客户端必须原样回送）
握手流程:
  ← 服务器: {"session_id":"...","auth_scheme_vsn":2,...}
  → 客户端: set_auth_token [JWT]
  → 客户端: set_data_quality ["low"]
  → 客户端: set_locale ["zh-Hans","CN"]
  → 客户端: quote_create_session [session_id]
  → 客户端: quote_set_fields [session_id, fields...]
  → 客户端: quote_add_symbols [session_id, symbols...]
  ← 服务器: qsd (实时行情数据)
"""
import asyncio
import json
import re
import random
import string
import aiohttp
from typing import Optional, Dict
from config import settings
from core.cookie_manager import CookieManager

# ── 协议常量 ────────────────────────────────────────────────

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
AUTH_TOKEN_URL = "https://www.tradingview.com/auth/api/get_token/"

HEARTBEAT_RE = re.compile(r'^~h~(\d+)$')

QUOTE_FIELDS = [
    "pro_name", "short_name", "description", "type",
    "lp", "ch", "chp", "update_mode", "typespecs",
    "exchange", "listed_exchange",
]

# ── 协议编解码 ────────────────────────────────────────────────

def _encode(payload: dict | str) -> str:
    """编码一条消息为 ~m~{len}~m~{payload}"""
    if isinstance(payload, dict):
        payload = json.dumps(payload, separators=(',', ':'))
    return f"~m~{len(payload)}~m~{payload}"

def _decode(raw: str) -> list[str]:
    """解析原始帧，返回所有 payload 列表"""
    result = []
    i = 0
    while i < len(raw):
        if not raw[i:i+3] == '~m~':
            break
        i += 3
        try:
            end = raw.index('~m~', i)
        except ValueError:
            break
        try:
            length = int(raw[i:end])
        except ValueError:
            break
        i = end + 3
        result.append(raw[i:i + length])
        i += length
    return result

def _rand_id(n: int = 12) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


# ── 主类 ──────────────────────────────────────────────────────

class TVPriceFetcher:
    """
    通过 TradingView WebSocket 订阅实时行情价格。
    维护一个内存价格缓存 {symbol: price}，供新闻分析时参考。
    """

    def __init__(self, cookie_manager: CookieManager, symbols: Optional[list[str]] = None):
        self.cm = cookie_manager
        self.symbols: list[str] = symbols or settings.TV_PRICE_SYMBOLS
        self._prices: Dict[str, float] = {}
        self._running = False
        self._session_id = f"qs_py_{_rand_id()}"
        self._auth_token: Optional[str] = None

    # ── 公共接口 ─────────────────────────────────────────────

    def get_price(self, symbol: str) -> Optional[float]:
        """获取某交易对最新价格（无数据返回 None）"""
        return self._prices.get(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        return dict(self._prices)

    async def run(self):
        """持续运行，断线自动重连"""
        self._running = True
        while self._running:
            try:
                await self._connect_and_stream()
            except Exception as e:
                print(f"[WSPrice] 连接中断: {e}，10秒后重连...")
                await asyncio.sleep(10)

    async def stop(self):
        self._running = False

    # ── 连接流程 ──────────────────────────────────────────────

    async def _connect_and_stream(self):
        if not self.symbols:
            print("[WSPrice] 没有配置订阅交易对，跳过")
            return

        proxy = settings.HTTP_PROXY or None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "Origin": "https://cn.tradingview.com",
        }
        headers.update(self.cm.get_headers())

        url = f"{WS_URL}?from=py_price_tracker&date=2026-01-01T00:00:00&auth=sessionid"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                url, headers=headers, proxy=proxy,
                heartbeat=None,       # 由我们手动处理
                compress=15,
            ) as ws:
                print(f"[WSPrice] 已连接，订阅 {len(self.symbols)} 个交易对")
                self._session_id = f"qs_py_{_rand_id()}"

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._on_text(ws, msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print(f"[WSPrice] WS 错误: {ws.exception()}")
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        break

    # ── 消息处理 ──────────────────────────────────────────────

    async def _on_text(self, ws, raw: str):
        for payload in _decode(raw):
            # ── 心跳 ──────────────────────────────────────────
            m = HEARTBEAT_RE.match(payload)
            if m:
                await ws.send_str(_encode(f"~h~{m.group(1)}"))
                return

            # ── JSON 消息 ──────────────────────────────────────
            try:
                msg = json.loads(payload)
            except json.JSONDecodeError:
                return

            method = msg.get('m', '')
            params = msg.get('p', [])

            if method == '':
                # 服务器握手（没有 "m" 字段，只有 session_id 等）
                await self._on_handshake(ws, msg)

            elif method == 'qsd':
                # 行情数据更新
                self._on_qsd(params)

    async def _on_handshake(self, ws, server_info: dict):
        """服务器握手后，发送认证和订阅消息"""
        print(f"[WSPrice] 服务器握手: {server_info.get('session_id', '?')}")

        # 1. 获取并发送 JWT（可选，失败时跳过）
        jwt = await self._fetch_jwt()
        if jwt:
            await ws.send_str(_encode({"m": "set_auth_token", "p": [jwt]}))
        else:
            await ws.send_str(_encode({"m": "set_auth_token", "p": ["unauthorized_user_token"]}))

        # 2. 设置数据质量和地区
        await ws.send_str(_encode({"m": "set_data_quality", "p": ["low"]}))
        await ws.send_str(_encode({"m": "set_locale", "p": ["zh-Hans", "CN"]}))

        # 3. 创建行情会话
        await ws.send_str(_encode({"m": "quote_create_session", "p": [self._session_id]}))

        # 4. 设置订阅字段
        await ws.send_str(_encode({
            "m": "quote_set_fields",
            "p": [self._session_id] + QUOTE_FIELDS,
        }))

        # 5. 批量订阅交易对
        await ws.send_str(_encode({
            "m": "quote_add_symbols",
            "p": [self._session_id] + self.symbols,
        }))

        print(f"[WSPrice] 订阅消息已发送，等待行情推送...")

    def _on_qsd(self, params: list):
        """处理行情快照数据"""
        if len(params) < 2:
            return
        data = params[1]
        symbol = data.get('n', '')
        v = data.get('v', {})
        lp = v.get('lp')
        if symbol and lp is not None:
            old = self._prices.get(symbol)
            self._prices[symbol] = float(lp)
            if old is None:
                # 首次接收
                short = v.get('short_name', symbol)
                print(f"[WSPrice] {short:>15} = {lp}")

    # ── JWT 获取 ──────────────────────────────────────────────

    async def _fetch_jwt(self) -> Optional[str]:
        """
        尝试从 TradingView 获取认证 JWT。
        通过 sessionid cookie 换取 JWT token。
        """
        if not self.cm.is_authenticated:
            return None
        proxy = settings.HTTP_PROXY or None
        headers = {"Referer": "https://cn.tradingview.com/", "X-Requested-With": "XMLHttpRequest"}
        headers.update(self.cm.get_headers())
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    AUTH_TOKEN_URL,
                    headers=headers,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        token = data.get("token") or data.get("access_token")
                        if token:
                            print("[WSPrice] JWT 获取成功")
                            return token
        except Exception as e:
            print(f"[WSPrice] JWT 获取失败 ({e})，将以匿名模式订阅")
        return None

    # ── 动态管理订阅 ─────────────────────────────────────────

    async def add_symbols(self, ws, symbols: list[str]):
        """运行时追加订阅"""
        new = [s for s in symbols if s not in self.symbols]
        if not new:
            return
        self.symbols.extend(new)
        await ws.send_str(_encode({"m": "quote_add_symbols", "p": [self._session_id] + new}))

    async def remove_symbols(self, ws, symbols: list[str]):
        """运行时取消订阅"""
        for s in symbols:
            if s in self.symbols:
                self.symbols.remove(s)
                del self._prices[s]
        await ws.send_str(_encode({"m": "quote_remove_symbols", "p": [self._session_id] + symbols}))
