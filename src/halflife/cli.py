"""Command line interface."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .actions import Actuator
from .client import HalfLifeClient
from .models import MemoryStatus
from .properties import bootstrap
from .recall import Recall
from .store import MemoryStore, now_ms
from .validator import Validator

app = typer.Typer(
    help="Memory integrity for DataHub agents.",
    no_args_is_help=True,
    add_completion=False,
)
demo_app = typer.Typer(help="Scripted demo scenario.", no_args_is_help=True)
app.add_typer(demo_app, name="demo")

console = Console()

_STATUS_STYLE = {
    MemoryStatus.VALID: "green",
    MemoryStatus.SUSPECT: "yellow",
    MemoryStatus.EXPIRED: "red",
}


def _client() -> HalfLifeClient:
    return HalfLifeClient()


@app.command()
def init() -> None:
    """Create the structured properties Half-Life stores provenance in."""
    results = bootstrap(_client())
    for name, outcome in results.items():
        style = "red" if outcome.startswith("failed") else "green"
        console.print(f"  [{style}]{outcome:9}[/] {name}")

    if any(o.startswith("failed") for o in results.values()):
        raise typer.Exit(1)
    console.print("\n[green]Ready.[/] Record a memory with [bold]halflife record[/].")


@app.command()
def record(
    title: str = typer.Option(..., "--title", "-t", help="What the memory claims."),
    text: str = typer.Option(..., "--text", "-x", help="The memory body."),
    depends_on: list[str] = typer.Option(
        ..., "--depends-on", "-d", help="URN this memory relies on (repeatable)."
    ),
    memory_id: str = typer.Option(None, "--id", help="Stable id; derived from title if omitted."),
) -> None:
    """Record a memory together with the state of everything it relies on."""
    store = MemoryStore(_client())
    memory = store.record(
        memory_id=memory_id or _slug(title),
        title=title,
        text=text,
        dependencies=list(depends_on),
    )
    console.print(f"[green]Recorded[/] {memory.urn}")
    for urn, fingerprint in memory.fingerprints.items():
        console.print(f"  [dim]{fingerprint}[/]  {urn}")


@app.command()
def validate(
    apply: bool = typer.Option(False, "--apply", help="Write verdicts back to DataHub."),
    urn: list[str] = typer.Option(None, "--urn", help="Validate only these memories."),
) -> None:
    """Check every memory against the current state of its dependencies."""
    client = _client()
    store = MemoryStore(client)
    validator = Validator(client)
    actuator = Actuator(client)

    memories = [store.load(u) for u in urn] if urn else store.list_memories()
    memories = [m for m in memories if m is not None]

    if not memories:
        console.print("[yellow]No memories found.[/] Record one with [bold]halflife record[/].")
        return

    now = now_ms()
    table = Table(title=f"Validated {len(memories)} memories", header_style="bold")
    table.add_column("Memory", max_width=42)
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Why", max_width=60)

    changed = 0
    for memory in memories:
        verdict = validator.validate(memory, now=now)
        if verdict.changed:
            changed += 1
        if apply:
            actuator.apply(verdict)

        style = _STATUS_STYLE[verdict.new_status]
        transition = (
            f"[{style}]{verdict.new_status.value}[/]"
            if not verdict.changed
            else f"{verdict.previous_status.value} → [{style}]{verdict.new_status.value}[/]"
        )
        table.add_row(
            memory.title,
            transition,
            str(verdict.integrity_score),
            verdict.reason[:200] or "—",
        )

    console.print(table)
    if changed and not apply:
        console.print(
            f"\n[yellow]{changed} memory/memories changed state.[/] "
            "Re-run with [bold]--apply[/] to write verdicts back to DataHub."
        )


@app.command("list")
def list_memories() -> None:
    """Show the memory ledger."""
    store = MemoryStore(_client())
    memories = store.list_memories()

    if not memories:
        console.print("[yellow]No memories found.[/]")
        return

    table = Table(title=f"{len(memories)} memories", header_style="bold")
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Memory", max_width=46)
    table.add_column("Deps", justify="right")
    table.add_column("Reason", max_width=48)

    for memory in memories:
        style = _STATUS_STYLE[memory.status]
        table.add_row(
            f"[{style}]{memory.status.value}[/]",
            str(memory.integrity_score),
            memory.title,
            str(len(memory.dependencies)),
            (memory.invalidation_reason or "—")[:160],
        )
    console.print(table)


@app.command()
def recall(
    query: str = typer.Argument(..., help="What the agent wants to know."),
    limit: int = typer.Option(5, "--limit", "-n"),
) -> None:
    """Retrieve trustworthy memories. Expired memories are never returned."""
    store = MemoryStore(_client())
    engine = Recall(store)

    results = engine.search(query, limit=limit)
    if not results:
        console.print("[yellow]No trustworthy memories matched.[/]")

    for result in results:
        memory = result.memory
        style = _STATUS_STYLE[memory.status]
        console.print(f"\n[{style}]● {memory.status.value}[/] [bold]{memory.title}[/]")
        console.print(f"  {memory.text}")
        if result.warning:
            console.print(f"  [yellow]⚠ {result.warning}[/]")

    withheld = engine.excluded(query)
    if withheld:
        console.print(
            f"\n[red]{len(withheld)} expired memory/memories withheld:[/] "
            + ", ".join(m.title for m in withheld)
        )
        console.print("[dim]Re-derive these from the catalog rather than trusting them.[/]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8420, "--port"),
) -> None:
    """Run the web ledger."""
    import uvicorn

    from .ledger.app import create_app

    console.print(f"Ledger on [bold]http://{host}:{port}[/]")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@demo_app.command("seed")
def demo_seed() -> None:
    """Record the demo memories against real datapack entities."""
    from .demo import seed

    seed(_client(), console)


@demo_app.command("drift")
def demo_drift() -> None:
    """Apply the three upstream changes the demo hinges on."""
    from .demo import drift

    drift(_client(), console)


@demo_app.command("reset")
def demo_reset() -> None:
    """Remove demo memories and restore the mutated entities."""
    from .demo import reset

    reset(_client(), console)


def _slug(text: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "memory"


if __name__ == "__main__":
    app()
