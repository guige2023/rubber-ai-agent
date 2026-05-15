"""
RabAiAgent CLI - Command-line interface for agent cluster management.
"""

import asyncio
import json
import sys
from typing import Optional

import typer

from app.core.agent_cluster import (
    AgentClusterManager,
    get_cluster,
    get_registry,
)
from app.core.agent_cluster.agents import AGENT_REGISTRY, create_agent
from app.core.agent_cluster.base import AgentContext

app = typer.Typer(help="RabAiAgent CLI - Agent Cluster Management")

# State
_cluster: Optional[AgentClusterManager] = None


def get_cluster_manager() -> AgentClusterManager:
    """Get or create cluster manager."""
    global _cluster
    if _cluster is None:
        _cluster = get_cluster()
    return _cluster


@app.command()
def list_agents():
    """List all registered agents."""
    cluster = get_cluster_manager()
    agents = cluster.list_agents()

    if not agents:
        typer.echo("No agents registered")
        return

    typer.echo(f"\nRegistered Agents ({len(agents)}):\n")
    typer.echo(f"{'Name':<20} {'Description':<40} {'Heartbeat':<10}")
    typer.echo("-" * 70)
    for agent in agents:
        typer.echo(
            f"{agent['name']:<20} {agent['description']:<40} {agent['heartbeat_interval']:<10}"
        )


@app.command()
def status(agent_name: Optional[str] = None):
    """Show agent status."""
    cluster = get_cluster_manager()
    status_info = cluster.get_status()

    if agent_name:
        # Find specific agent
        for agent_status in status_info["agents"]:
            if agent_status["name"] == agent_name:
                typer.echo(f"\nAgent: {agent_status['name']}")
                typer.echo(f"Status: {agent_status['status']}")
                typer.echo(f"Last Heartbeat: {agent_status['last_heartbeat']}")
                typer.echo(f"Last Active: {agent_status['last_active']}")
                typer.echo(f"Total Invocations: {agent_status['total_invocations']}")
                typer.echo(f"Errors: {agent_status['error_count']}")
                return

        typer.echo(f"Agent not found: {agent_name}", err=True)
    else:
        # Show all status
        typer.echo(f"\nCluster Status:")
        typer.echo(f"  Running: {status_info['running']}")
        typer.echo(f"  Total Agents: {status_info['total_agents']}")

        typer.echo(f"\nAgent Details:\n")
        for agent in status_info["agents"]:
            typer.echo(
                f"  {agent['name']:<20} {agent['status']:<12} "
                f"Invocations: {agent['total_invocations']:<6} Errors: {agent['error_count']}"
            )


@app.command()
def invoke(
    agent_name: str = typer.Argument(..., help="Agent name to invoke"),
    task: str = typer.Argument(..., help="Task to execute"),
    session_id: Optional[str] = typer.Option(None, "--session", help="Session ID"),
):
    """Invoke a specific agent."""
    cluster = get_cluster_manager()

    context = AgentContext(session_id=session_id or "cli")

    typer.echo(f"Invoking {agent_name}...")

    result = asyncio.run(cluster.invoke(agent_name, task, context))

    if result.success:
        typer.echo(f"\nSuccess ({result.duration_ms}ms):")
        typer.echo(json.dumps(result.output, indent=2))
    else:
        typer.echo(f"\nError: {result.error}", err=True)


@app.command()
def memory_stats():
    """Show memory system statistics."""
    cluster = get_cluster_manager()
    stats = asyncio.run(cluster.memory.get_stats())

    typer.echo(f"\nMemory System Status:\n")
    typer.echo(f"Initialized: {stats.get('initialized', False)}")

    # L1
    l1 = stats.get("l1", {})
    typer.echo(f"\nL1 (Working Memory):")
    typer.echo(f"  Entries: {l1.get('entries', 0)}")

    # L2
    l2 = stats.get("l2", {})
    typer.echo(f"\nL2 (Semantic Memory):")
    typer.echo(f"  Connected: {l2.get('connected', False)}")
    typer.echo(f"  Entities: {l2.get('entities', 'N/A')}")

    # L3
    l3 = stats.get("l3", {})
    typer.echo(f"\nL3 (Crystal Memory):")
    typer.echo(f"  Skills Count: {l3.get('skills_count', 0)}")


@app.command()
def heartbeat_trigger(agent_name: str = typer.Argument(..., help="Agent name")):
    """Manually trigger heartbeat for an agent."""
    cluster = get_cluster_manager()

    cluster.trigger_heartbeat(agent_name)
    typer.echo(f"Heartbeat triggered for {agent_name}")


@app.command()
def init_cluster():
    """Initialize the agent cluster."""
    cluster = get_cluster_manager()

    typer.echo("Initializing cluster...")

    asyncio.run(cluster.initialize())

    # Register default agents
    for agent_type in AGENT_REGISTRY:
        agent = create_agent(agent_type)
        cluster.register_agent(agent)

        # Special handling for memory agent
        if agent_type == "memory":
            from app.core.agent_cluster.agents import MemoryAgent
            if isinstance(agent, MemoryAgent):
                agent.set_memory_manager(cluster.memory)

    asyncio.run(cluster.start())

    typer.echo(f"\nCluster initialized with {len(AGENT_REGISTRY)} agents")
    typer.echo("Use 'rabaiagent-cli list-agents' to see all agents")


if __name__ == "__main__":
    app()
