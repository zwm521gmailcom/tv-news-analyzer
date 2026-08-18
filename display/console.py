import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from db.models import RawNews

console = Console()


class ConsoleDisplay:

    def show_startup(self):
        console.print(Panel(
            "[bold cyan]TradingView News Monitor[/bold cyan]\n"
            f"[dim]启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            box=box.ROUNDED,
        ))

    def show_poll_result(self, total: int, inserted: int):
        ts = datetime.now().strftime("%H:%M:%S")
        console.print(
            f"[dim]{ts}[/dim] 轮询完成 · 获取 [bold]{total}[/bold] 条 · "
            f"新增 [bold cyan]{inserted}[/bold cyan] 条"
        )

    def show_raw(self, news: RawNews):
        """展示原始新闻"""
        published = datetime.fromtimestamp(news.published).strftime("%m-%d %H:%M")
        title_text = Text()
        if news.is_flash:
            title_text.append("[快讯] ", style="bold magenta")
        title_text.append(news.title, style="bold white")

        urgency_map = {1: "[dim]低", 2: "[yellow]中", 3: "[bold red]高"}
        urgency_label = urgency_map.get(news.urgency, "[dim]未知") + "[/]"
        syms = ", ".join(news.symbols[:5]) if news.symbols else "—"
        lang_tag = f"[dim]{news.lang}[/dim]"
        market_tag = f"[dim]{news.market}[/dim]"
        body = (
            f"紧急度:{urgency_label}  语言:{lang_tag}  市场:{market_tag}  "
            f"来源:[dim]{news.provider}[/dim]  时间:[dim]{published}[/dim]\n"
            f"交易对: [yellow]{syms}[/yellow]"
        )
        if news.short_desc:
            body += f"\n[dim]{news.short_desc[:120]}[/dim]"
        console.print(Panel(f"{title_text}\n{body}", border_style="dim", padding=(0, 1)))

    def show_raw_list(self, results: list[dict], total: int = 0):
        """展示原始新闻列表"""
        if not results:
            console.print("[yellow]未找到符合条件的新闻[/yellow]")
            return
        shown = len(results)
        title_str = f"新闻列表（显示 {shown} / 共 {total} 条）" if total > shown else f"新闻列表（共 {shown} 条）"

        table = Table(
            title=title_str,
            box=box.SIMPLE_HEAD,
            show_lines=True,
        )
        table.add_column("标题", style="white", max_width=55)
        table.add_column("语言", justify="center", width=6)
        table.add_column("市场", justify="center", width=8)
        table.add_column("来源", style="dim", max_width=14)
        table.add_column("时间", style="dim", width=12)

        for r in results:
            published = ""
            if r.get("published"):
                published = datetime.fromtimestamp(r["published"]).strftime("%m-%d %H:%M")

            table.add_row(
                r.get("title", "")[:54],
                r.get("lang", ""),
                r.get("market", ""),
                r.get("provider", ""),
                published,
            )

        console.print(table)
