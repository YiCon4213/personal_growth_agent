from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP

server = FastMCP("phase3-test-time")


@server.tool()
def get_current_time(timezone: str) -> str:
    """Get the current time in an IANA timezone."""
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Invalid IANA timezone") from exc
    return datetime.now(zone).isoformat()


@server.tool()
def convert_time(
    source_timezone: str,
    target_timezone: str,
    time: str,
) -> str:
    """Convert HH:MM between two IANA timezones."""
    source = ZoneInfo(source_timezone)
    target = ZoneInfo(target_timezone)
    hour, minute = (int(part) for part in time.split(":", maxsplit=1))
    value = datetime.now(source).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return value.astimezone(target).isoformat()


if __name__ == "__main__":
    server.run(transport="stdio")
