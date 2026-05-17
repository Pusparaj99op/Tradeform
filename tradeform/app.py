"""
Tradeform — Main Textual TUI Application.
The terminal-based trading dashboard.
"""

import os
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import (
    Header,
    Footer,
    Static,
    Input,
    DataTable,
    RichLog,
    Label,
    Button,
)
from textual.binding import Binding
from textual.worker import Worker, get_current_worker
from textual import work
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from rich.align import Align

from tradeform.core.engine import TradingEngine
from tradeform.config import load_config


class TradeformApp(App):
    """The Tradeform terminal trading application."""

    CSS_PATH = os.path.join(os.path.dirname(__file__), "ui", "styles.tcss")

    TITLE = "TRADEFORM"
    SUB_TITLE = "AI-Powered Forex Terminal"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
        Binding("a", "analyze", "AI Analyze", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("k", "kill_switch", "Kill Switch", show=True),
        Binding("c", "focus_chat", "Chat", show=True),
        Binding("1", "analyze_symbol_1", "Analyze Sym 1", show=False),
        Binding("2", "analyze_symbol_2", "Analyze Sym 2", show=False),
        Binding("3", "analyze_symbol_3", "Analyze Sym 3", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.engine = TradingEngine(self.config)
        self._selected_symbol_idx = 0

    def compose(self) -> ComposeResult:
        """Build the UI layout."""
        yield Header(show_clock=True)

        # Account bar
        yield Horizontal(
            Static("", id="account-info"),
            id="account-bar",
        )

        # Main grid
        with Container(id="main-container"):
            # Left column — Market Prices
            with Vertical(id="market-panel"):
                yield Static("📊 MARKET", classes="panel-title")
                yield Static("Connecting...", id="market-prices")

            # Center column — AI Analysis (spans 2 rows)
            with Vertical(id="ai-panel"):
                yield Static("🤖 AI ANALYST", classes="panel-title")
                yield RichLog(id="ai-output", wrap=True, markup=True)
                yield Input(
                    placeholder="Ask the AI anything... (Enter to send)",
                    id="ai-input",
                )

            # Right column — Positions
            with Vertical(id="trade-panel"):
                yield Static("📈 POSITIONS", classes="panel-title")
                yield Static("No positions", id="positions-display")

            # Bottom left — Logs
            with Vertical(id="log-panel"):
                yield Static("📋 LOG", classes="panel-title")
                yield RichLog(id="log-output", wrap=True, markup=True, max_lines=100)

            # Bottom right — Risk
            with Vertical(id="risk-panel"):
                yield Static("🛡️ RISK", classes="panel-title")
                yield Static("Loading...", id="risk-display")

        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted — start connections and timers."""
        self._write_log("[bold cyan]TRADEFORM[/] v0.1.0 starting...")
        self._write_log(f"Mode: [bold]{self.config.trading.mode}[/]")
        self._write_log(f"Symbols: {', '.join(self.config.trading.symbols)}")
        self._write_log(f"Timeframe: {self.config.trading.timeframe}")
        self._write_log("")

        # Connect in background
        self.connect_services()

        # Set up periodic refresh — fast for scalping
        self.set_interval(1.0, self._refresh_market_data)    # 1s price updates
        self.set_interval(3.0, self._refresh_positions)       # 3s position updates
        self.set_interval(5.0, self._refresh_risk)            # 5s risk check
        self.set_interval(3.0, self._refresh_account)         # 3s account refresh

        # Autonomous scalping loop — runs every interval
        interval_secs = self.config.ollama.analysis_interval_minutes * 60
        self.set_interval(interval_secs, self._autonomous_loop)

        # Scalp position management — trail stops every 15s
        self.set_interval(15.0, self._manage_positions)

        # Trigger first scalp analysis 8s after startup
        self.set_timer(8.0, self._autonomous_loop)

        self._write_log(
            f"[bold yellow]⚡ GOLD SCALPING MODE ACTIVE[/]: "
            f"M1 analysis every {self.config.ollama.analysis_interval_minutes}m | "
            f"Trailing stops every 15s | "
            f"Symbol: XAUUSD.sc"
        )

    @work(thread=True, exclusive=True, group="connect")
    def connect_services(self) -> None:
        """Connect to MT5 and Ollama in a background thread."""
        # Connect MT5
        self._write_log("Connecting to MT5...")
        try:
            self.engine.connect_mt5()
            self._write_log("[bold green]✅ MT5 connected[/]")
            account = self.engine.get_account_summary()
            self._write_log(
                f"Account: {account['name']} | "
                f"Balance: ${account['balance']:,.2f} | "
                f"Leverage: 1:{account['leverage']}"
            )
        except Exception as e:
            self._write_log(f"[bold red]❌ MT5 failed: {e}[/]")

        # Connect Ollama
        self._write_log(f"Connecting to Ollama ({self.config.ollama.host})...")
        try:
            self.engine.connect_ollama()
            models = self.engine.ollama_client.list_models()
            self._write_log(f"[bold green]✅ Ollama connected[/]")
            self._write_log(f"Models: {', '.join(models[:5])}")
            if self.engine.ollama_client.is_model_available():
                self._write_log(
                    f"[bold green]Model '{self.config.ollama.model}' ready[/]"
                )
            else:
                self._write_log(
                    f"[bold yellow]⚠️ Model '{self.config.ollama.model}' not found. "
                    f"Run: ollama pull {self.config.ollama.model}[/]"
                )
        except Exception as e:
            self._write_log(f"[bold red]❌ Ollama failed: {e}[/]")

        self._write_log("")
        self._write_log("[dim]Press [bold]a[/bold] to analyze | [bold]c[/bold] to chat | [bold]k[/bold] for kill switch[/]")

    # ── Periodic Refresh Workers ──────────────────────────────

    def _refresh_market_data(self) -> None:
        """Refresh market prices display."""
        if not self.engine.mt5_connected:
            return

        try:
            ticks = self.engine.get_multi_ticks()
            lines = []
            for symbol in self.config.trading.symbols:
                tick = ticks.get(symbol)
                if tick:
                    bid = tick.get("bid", 0)
                    ask = tick.get("ask", 0)
                    spread = self.engine.get_spread(symbol)
                    # Format based on digits
                    info = self.engine.mt5_data.get_symbol_info(symbol)
                    digits = info.get("digits", 5) if info else 5

                    idx = self.config.trading.symbols.index(symbol)
                    marker = "▸" if idx == self._selected_symbol_idx else " "

                    lines.append(
                        f"{marker} [bold white]{symbol:10s}[/]  "
                        f"[green]{bid:.{digits}f}[/]  "
                        f"[red]{ask:.{digits}f}[/]  "
                        f"[dim]{spread:.1f}sp[/]"
                    )
                else:
                    lines.append(f"  [dim]{symbol:10s}  --[/]")

            market_widget = self.query_one("#market-prices", Static)
            market_widget.update("\n".join(lines))
        except Exception:
            pass

    def _refresh_positions(self) -> None:
        """Refresh positions display."""
        if not self.engine.mt5_connected:
            return

        try:
            positions = self.engine.get_positions()
            if not positions:
                pos_widget = self.query_one("#positions-display", Static)
                pos_widget.update("[dim]No open positions[/]")
                return

            lines = []
            total_pnl = 0.0
            for p in positions:
                direction = "BUY" if p.get("type") == 0 else "SELL"
                dir_color = "green" if direction == "BUY" else "red"
                pnl = p.get("profit", 0)
                total_pnl += pnl
                pnl_color = "green" if pnl >= 0 else "red"

                lines.append(
                    f"[{dir_color}]{direction}[/] {p.get('symbol', '')}\n"
                    f"  {p.get('volume', 0)} lots @ {p.get('price_open', 0):.5f}\n"
                    f"  P/L: [{pnl_color}]${pnl:.2f}[/]  "
                    f"SL:{p.get('sl', 0):.5f} TP:{p.get('tp', 0):.5f}\n"
                    f"  [dim]#{p.get('ticket', '')}[/]\n"
                )

            total_color = "green" if total_pnl >= 0 else "red"
            lines.append(f"\n[bold]Total P/L: [{total_color}]${total_pnl:.2f}[/][/]")

            pos_widget = self.query_one("#positions-display", Static)
            pos_widget.update("\n".join(lines))
        except Exception:
            pass

    def _refresh_risk(self) -> None:
        """Refresh risk display."""
        if not self.engine.mt5_connected:
            return

        try:
            account = self.engine.get_account_summary()
            positions = self.engine.get_positions()
            risk = self.engine.risk_manager.get_risk_summary(
                account["balance"], positions
            )

            kill_icon = "🔴 ACTIVE" if risk["kill_switch"] else "🟢 OFF"
            pnl_color = "green" if risk["daily_pnl"] >= 0 else "red"

            text = (
                f"Kill Switch: {kill_icon}\n\n"
                f"Daily P/L: [{pnl_color}]${risk['daily_pnl']:.2f}[/]\n"
                f"Daily Limit: ${risk['daily_limit']:.2f}\n\n"
                f"Positions: {risk['open_positions']}/{risk['max_positions']}\n"
                f"Total Lots: {risk['total_lots']}\n"
                f"Max Lot: {risk['max_lot_size']}\n\n"
                f"Floating: [{pnl_color}]${risk['floating_pnl']:.2f}[/]"
            )

            risk_widget = self.query_one("#risk-display", Static)
            risk_widget.update(text)
        except Exception:
            pass

    def _refresh_account(self) -> None:
        """Refresh account bar."""
        if not self.engine.mt5_connected:
            self.query_one("#account-info", Static).update(
                "[dim]MT5: Disconnected[/]"
            )
            return

        try:
            a = self.engine.get_account_summary()
            mt5_status = "[green]●[/]" if self.engine.mt5_connected else "[red]●[/]"
            ai_status = "[green]●[/]" if self.engine.ollama_connected else "[red]●[/]"
            pnl_color = "green" if a["profit"] >= 0 else "red"

            text = (
                f" {mt5_status} MT5  {ai_status} AI  │  "
                f"[bold]${a['balance']:,.2f}[/]  │  "
                f"Equity: ${a['equity']:,.2f}  │  "
                f"Margin: ${a['margin']:,.2f}  │  "
                f"Free: ${a['free_margin']:,.2f}  │  "
                f"P/L: [{pnl_color}]${a['profit']:,.2f}[/]  │  "
                f"1:{a['leverage']}"
            )

            self.query_one("#account-info", Static).update(text)
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────

    def action_quit_app(self) -> None:
        """Quit the application."""
        self.engine.disconnect()
        self.exit()

    def action_analyze(self) -> None:
        """Trigger AI analysis on the selected symbol."""
        symbols = self.config.trading.symbols
        if self._selected_symbol_idx < len(symbols):
            symbol = symbols[self._selected_symbol_idx]
            self._run_analysis(symbol)

    def action_analyze_symbol_1(self) -> None:
        self._selected_symbol_idx = 0
        if len(self.config.trading.symbols) > 0:
            self._run_analysis(self.config.trading.symbols[0])

    def action_analyze_symbol_2(self) -> None:
        self._selected_symbol_idx = 1
        if len(self.config.trading.symbols) > 1:
            self._run_analysis(self.config.trading.symbols[1])

    def action_analyze_symbol_3(self) -> None:
        self._selected_symbol_idx = 2
        if len(self.config.trading.symbols) > 2:
            self._run_analysis(self.config.trading.symbols[2])

    @work(thread=True, exclusive=True, group="analysis")
    def _run_analysis(self, symbol: str) -> None:
        """Run AI analysis in background thread."""
        ai_output = self.query_one("#ai-output", RichLog)

        ai_output.write(f"\n[bold cyan]{'='*50}[/]")
        ai_output.write(
            f"[bold magenta]🤖 Analyzing {symbol} ({self.config.trading.timeframe})...[/]"
        )
        ai_output.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/]\n")

        try:
            signal = self.engine.run_analysis(symbol)

            if signal.error:
                ai_output.write(f"[bold red]Error: {signal.error}[/]")
                return

            # Display signal card
            if signal.signal == "BUY":
                color = "green"
                icon = "🟢"
            elif signal.signal == "SELL":
                color = "red"
                icon = "🔴"
            else:
                color = "yellow"
                icon = "⚪"

            ai_output.write(
                f"[bold {color}]{icon} SIGNAL: {signal.signal}[/]  "
                f"Confidence: [bold]{signal.confidence:.0%}[/]"
            )
            ai_output.write(
                f"Entry: {signal.entry_price}  "
                f"SL: {signal.stop_loss}  "
                f"TP: {signal.take_profit}"
            )
            ai_output.write(f"Risk/Reward: {signal.risk_reward_ratio}")
            ai_output.write(f"\n[italic]{signal.reasoning}[/]")

            if signal.key_factors:
                ai_output.write("\nKey Factors:")
                for f in signal.key_factors:
                    ai_output.write(f"  • {f}")

            # If in auto mode and signal is actionable, execute
            if (
                self.config.trading.mode == "auto"
                and signal.is_actionable
            ):
                ai_output.write(
                    f"\n[bold yellow]⚡ AUTO-EXECUTING {signal.signal}...[/]"
                )
                result = self.engine.execute_signal(signal)
                ai_output.write(str(result))
            elif signal.is_actionable:
                ai_output.write(
                    f"\n[bold cyan]Signal ready. Mode: confirmation "
                    f"(type 'execute {symbol}' to trade)[/]"
                )

            self._write_log(
                f"Analysis complete: {signal.signal} {symbol} "
                f"({signal.confidence:.0%})"
            )

        except Exception as e:
            ai_output.write(f"[bold red]Analysis failed: {e}[/]")
            self._write_log(f"[red]Analysis error: {e}[/]")

    # ── Autonomous Loop ───────────────────────────────────────

    def _autonomous_loop(self) -> None:
        """Periodic hook — kicks off background analysis for all symbols."""
        if not self.engine.mt5_connected or not self.engine.ollama_connected:
            return
        if self.engine.risk_manager.is_killed:
            return
        self._run_autonomous_cycle()

    @work(thread=True, exclusive=False, group="auto")
    def _run_autonomous_cycle(self) -> None:
        """Analyze all symbols and auto-execute actionable signals."""
        ai_output = self.query_one("#ai-output", RichLog)
        mode = self.config.trading.mode

        for symbol in self.config.trading.symbols:
            if self.engine.risk_manager.is_killed:
                break
            if not self.engine.should_analyze(symbol):
                continue

            ai_output.write(
                f"\n[bold cyan]{'='*50}[/]"
            )
            ai_output.write(
                f"[bold magenta]🤖 [AUTO] Analyzing {symbol} "
                f"({self.config.trading.timeframe})...[/]"
            )
            ai_output.write(
                f"[dim]{datetime.now().strftime('%H:%M:%S')}[/]\n"
            )

            try:
                signal = self.engine.run_analysis(symbol)

                if signal.error:
                    ai_output.write(f"[bold red]Error: {signal.error}[/]")
                    continue

                color = "green" if signal.signal == "BUY" else (
                    "red" if signal.signal == "SELL" else "yellow"
                )
                icon = "🟢" if signal.signal == "BUY" else (
                    "🔴" if signal.signal == "SELL" else "⚪"
                )
                ai_output.write(
                    f"[bold {color}]{icon} {signal.signal}[/]  "
                    f"Confidence: [bold]{signal.confidence:.0%}[/]  "
                    f"RR: {signal.risk_reward_ratio}"
                )
                ai_output.write(
                    f"Entry: {signal.entry_price}  "
                    f"SL: {signal.stop_loss}  TP: {signal.take_profit}"
                )
                if signal.reasoning:
                    ai_output.write(f"[italic]{signal.reasoning}[/]")

                if signal.is_actionable and mode == "auto":
                    ai_output.write(
                        f"\n[bold yellow]⚡ AUTO-EXECUTING {signal.signal} {symbol}...[/]"
                    )
                    result = self.engine.execute_signal(signal)
                    if result.success:
                        ai_output.write(
                            f"[bold green]✅ Trade opened: ticket #{result.order_ticket} "
                            f"@ {result.price}[/]"
                        )
                        self._write_log(
                            f"[green]⚡ AUTO {signal.signal} {symbol} — "
                            f"ticket #{result.order_ticket}[/]"
                        )
                    else:
                        ai_output.write(
                            f"[bold red]❌ Execution failed: {result.message}[/]"
                        )
                        self._write_log(
                            f"[red]Auto-trade failed {symbol}: {result.message}[/]"
                        )
                elif signal.is_actionable and mode == "confirmation":
                    ai_output.write(
                        f"[bold cyan]Signal ready — type "
                        f"'execute {symbol}' to trade[/]"
                    )
                else:
                    ai_output.write("[dim]No actionable signal — holding[/]")

            except Exception as e:
                ai_output.write(f"[bold red]Auto-analysis error ({symbol}): {e}[/]")
                self._write_log(f"[red]Auto-loop error {symbol}: {e}[/]")

    def _manage_positions(self) -> None:
        """Periodic position management — trail stops on winners."""
        if not self.engine.mt5_connected:
            return
        if self.engine.risk_manager.is_killed:
            return
        self._run_position_management()

    @work(thread=True, exclusive=True, group="manage")
    def _run_position_management(self) -> None:
        """Run trailing stop management in background."""
        try:
            self.engine.manage_open_positions()
        except Exception as e:
            self._write_log(f"[red]Position management error: {e}[/]")

    def action_kill_switch(self) -> None:
        """Emergency close all positions."""
        self._write_log("[bold red]🛑 KILL SWITCH ACTIVATED[/]")
        self._execute_kill_switch()

    @work(thread=True, exclusive=True, group="killswitch")
    def _execute_kill_switch(self) -> None:
        """Execute kill switch in background."""
        ai_output = self.query_one("#ai-output", RichLog)
        ai_output.write("\n[bold red]🛑 KILL SWITCH — CLOSING ALL POSITIONS[/]")

        results = self.engine.close_all_positions()
        for r in results:
            ai_output.write(str(r))

        if not results:
            ai_output.write("[dim]No positions to close[/]")

        ai_output.write("[bold red]Kill switch engaged — new trades blocked[/]")

    def action_refresh(self) -> None:
        """Manual refresh of all panels."""
        self._refresh_market_data()
        self._refresh_positions()
        self._refresh_risk()
        self._refresh_account()
        self._write_log("Manual refresh")

    def action_focus_chat(self) -> None:
        """Focus the AI chat input."""
        self.query_one("#ai-input", Input).focus()

    # ── Input Handling ────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input."""
        if event.input.id == "ai-input":
            message = event.value.strip()
            if not message:
                return

            event.input.clear()
            ai_output = self.query_one("#ai-output", RichLog)

            # Check for commands
            if message.lower().startswith("execute "):
                symbol = message.split(" ", 1)[1].upper().strip()
                self._execute_pending_signal(symbol)
                return

            if message.lower() == "clear":
                ai_output.clear()
                self.engine.analyst.clear_history()
                return

            if message.lower() == "status":
                self._show_status()
                return

            # Regular chat
            ai_output.write(f"\n[bold cyan]You:[/] {message}")
            self._run_chat(message)

    @work(thread=True, exclusive=True, group="chat")
    def _run_chat(self, message: str) -> None:
        """Run chat in background."""
        ai_output = self.query_one("#ai-output", RichLog)
        try:
            response = self.engine.chat(message)
            ai_output.write(f"\n[bold magenta]AI:[/] {response}")
        except Exception as e:
            ai_output.write(f"[red]Chat error: {e}[/]")

    @work(thread=True, exclusive=True, group="execute")
    def _execute_pending_signal(self, symbol: str) -> None:
        """Execute the pending signal for a symbol."""
        ai_output = self.query_one("#ai-output", RichLog)

        signal = self.engine.get_latest_signal(symbol)
        if signal is None:
            ai_output.write(f"[yellow]No pending signal for {symbol}[/]")
            return

        if not signal.is_actionable:
            ai_output.write(f"[yellow]Signal for {symbol} is not actionable ({signal.signal})[/]")
            return

        ai_output.write(f"\n[bold yellow]⚡ Executing {signal.signal} {symbol}...[/]")
        result = self.engine.execute_signal(signal)
        ai_output.write(str(result))
        self._write_log(str(result))

    def _show_status(self) -> None:
        """Show system status in AI panel."""
        ai_output = self.query_one("#ai-output", RichLog)
        ai_output.write("\n[bold cyan]── System Status ──[/]")
        ai_output.write(f"MT5: {'🟢 Connected' if self.engine.mt5_connected else '🔴 Disconnected'}")
        ai_output.write(f"Ollama: {'🟢 Connected' if self.engine.ollama_connected else '🔴 Disconnected'}")
        ai_output.write(f"Model: {self.config.ollama.model}")
        ai_output.write(f"Mode: {self.config.trading.mode}")
        ai_output.write(f"Kill Switch: {'🔴 ON' if self.engine.risk_manager.is_killed else '🟢 OFF'}")

        stats = self.engine.get_daily_stats()
        ai_output.write(f"\nToday: {stats['trades']} trades, "
                       f"Win rate: {stats['win_rate']}%, "
                       f"P/L: ${stats['total_pnl']:.2f}")

    # ── Helpers ───────────────────────────────────────────────

    def _write_log(self, message: str) -> None:
        """Write to the log panel."""
        try:
            log_widget = self.query_one("#log-output", RichLog)
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_widget.write(f"[dim]{timestamp}[/] {message}")
        except Exception:
            pass
