from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from triage.tools import call

server = FastMCP("oncall-evidence")


@server.tool()
def query_prometheus() -> list[dict]:
    """Run the fixed shop Prometheus queries."""
    return [asdict(item) for item in call("query_prometheus")]


@server.tool()
def query_logs() -> list[dict]:
    """Fetch recent shop logs."""
    return [asdict(item) for item in call("query_logs")]


@server.tool()
def k8s_get() -> list[dict]:
    """Read shop pod status in the demo namespace."""
    return [asdict(item) for item in call("k8s_get")]


@server.tool()
def k8s_events() -> list[dict]:
    """Read pod events in the demo namespace."""
    return [asdict(item) for item in call("k8s_events")]


@server.tool()
def recent_deploys() -> list[dict]:
    """Read shop ReplicaSet revisions."""
    return [asdict(item) for item in call("recent_deploys")]


if __name__ == "__main__":
    server.run()
