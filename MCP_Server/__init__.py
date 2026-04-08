"""Ableton Live integration through the Model Context Protocol."""

__version__ = "0.1.0"

# Note: server.py is intentionally NOT imported eagerly here so that
# pure-Python helpers like ``MCP_Server.music`` and
# ``MCP_Server.personalities`` can be imported by test scripts without
# requiring the ``mcp`` package. Import server members lazily where needed:
#     from MCP_Server.server import AbletonConnection, get_ableton_connection