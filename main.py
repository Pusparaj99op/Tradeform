"""
Tradeform — AI-Powered Terminal Forex Trader
Entry point.

Usage:
    python main.py          # Launch the terminal UI
    python main.py --test   # Test connections without UI
"""

import sys
import os

# Fix Windows console encoding for Unicode/emoji
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_connections():
    """Test MT5 and Ollama connections without launching the UI."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from tradeform.config import load_config

    console = Console(force_terminal=True)
    config = load_config()

    console.print(Panel(
        "[bold cyan]TRADEFORM[/] Connection Test",
        border_style="cyan",
    ))

    # Test MT5
    console.print("\n[bold]1. Testing MetaTrader 5...[/]")
    try:
        from tradeform.mt5.connection import MT5Connection
        conn = MT5Connection(config.mt5)
        conn.connect()
        account = conn.get_account_summary()

        table = Table(title="MT5 Account", border_style="green")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        for key, val in account.items():
            table.add_row(key, str(val))
        console.print(table)
        console.print("[green]>> MT5 connected successfully![/]\n")
        conn.disconnect()
    except Exception as e:
        console.print(f"[red]>> MT5 failed: {e}[/]")
        console.print("[dim]Make sure MT5 is running and config.yaml has correct credentials[/]\n")

    # Test Ollama
    console.print("[bold]2. Testing Ollama...[/]")
    try:
        from tradeform.ai.ollama_client import OllamaClient
        client = OllamaClient(config.ollama)
        client.connect()
        models = client.list_models()

        table = Table(title="Ollama Models", border_style="magenta")
        table.add_column("Model", style="white")
        for m in models:
            table.add_row(m)
        console.print(table)

        if client.is_model_available():
            console.print(f"[green]>> Model '{config.ollama.model}' is available![/]")
        else:
            console.print(
                f"[yellow]>> Model '{config.ollama.model}' not found. "
                f"Run: ollama pull {config.ollama.model}[/]"
            )

        # Quick test
        console.print("\n[dim]Testing chat...[/]")
        response = client.chat([
            {"role": "user", "content": "Say 'Tradeform AI is ready!' in exactly those words."}
        ])
        console.print(f"[green]AI says: {response}[/]\n")

    except Exception as e:
        console.print(f"[red]>> Ollama failed: {e}[/]")
        console.print("[dim]Make sure Ollama is running (ollama serve)[/]\n")

    console.print(Panel(
        "Run [bold]python main.py[/] to launch the trading terminal",
        border_style="cyan",
    ))


def main():
    """Main entry point."""
    if "--test" in sys.argv:
        test_connections()
        return

    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
TRADEFORM - AI-Powered Terminal Forex Trader

Usage:
    python main.py          Launch the trading terminal
    python main.py --test   Test MT5 and Ollama connections
    python main.py --help   Show this help

Prerequisites:
    1. MetaTrader 5 running and logged into your broker
    2. Ollama running (ollama serve) with a model pulled
    3. config.yaml configured with your MT5 credentials

Keyboard Shortcuts (in terminal):
    a    - Run AI analysis on selected symbol
    1/2/3 - Analyze symbol 1/2/3
    c    - Focus chat input
    k    - Kill switch (close all positions)
    r    - Refresh all panels
    q    - Quit
        """)
        return

    from tradeform.app import TradeformApp
    app = TradeformApp()
    app.run()


if __name__ == "__main__":
    main()
