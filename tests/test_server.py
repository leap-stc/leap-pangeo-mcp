"""Server checks: the console script serves exactly the eight Phase 1 tools over stdio, all read-only."""

import functools
import shutil
import threading
import time

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from leap_pangeo_mcp import server
from leap_pangeo_mcp.core import knowledge
from leap_pangeo_mcp.core.common import MAX_CHARS, LeapError

PHASE_1_TOOLS = {
    "leap_overview",
    "search_datasets",
    "get_dataset",
    "describe_store",
    "list_storage",
    "search_docs",
    "get_my_environment",
    "how_to",
}


async def _talk_to_console_script():
    command = shutil.which("leap-pangeo-mcp")
    assert command, "leap-pangeo-mcp console script is not on PATH"
    params = StdioServerParameters(command=command, args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            overview = await session.call_tool("leap_overview", {})
            unknown = await session.call_tool("how_to", {"task": "nope"})
            return init, tools, overview, unknown


@pytest.fixture(scope="module")
def stdio():
    return anyio.run(_talk_to_console_script)


def test_server_lists_exactly_the_eight_tools(stdio):
    init, tools, _, _ = stdio
    assert init.serverInfo.name == "leap-pangeo"
    names = [tool.name for tool in tools]
    assert len(names) == 8
    assert set(names) == PHASE_1_TOOLS


def test_every_tool_is_read_only_and_documented(stdio):
    _, tools, _, _ = stdio
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.readOnlyHint is True, tool.name
        assert tool.description and len(tool.description) > 200, tool.name
        assert tool.outputSchema is None, tool.name  # plain markdown text only


def test_instructions_are_the_primer_that_leap_overview_returns(stdio):
    init, _, overview, _ = stdio
    assert init.instructions == knowledge.PRIMER
    assert not overview.isError
    assert overview.content[0].text == knowledge.PRIMER


def test_unknown_how_to_task_lists_valid_tasks(stdio):
    *_, unknown = stdio
    assert "Valid tasks" in unknown.content[0].text
    assert "copy_to_osn" in unknown.content[0].text


# --- the wrapper every tool goes through ------------------------------------


def _run(func, timeout=5.0):
    return anyio.run(functools.partial(server._run, func, timeout=timeout))


def test_timeout_returns_a_message_without_waiting_for_the_thread():
    release = threading.Event()
    start = time.monotonic()
    text = _run(lambda: release.wait(10) and "late", timeout=0.3)
    elapsed = time.monotonic() - start
    release.set()
    assert text.startswith("Error: no answer within")
    assert elapsed < 3


def test_errors_become_one_line_messages():
    def expected():
        raise LeapError("No GCS credentials found; this tool works on the LEAP hub.")

    def unexpected():
        raise ValueError("bad\n  thing")

    assert _run(expected) == "Error: No GCS credentials found; this tool works on the LEAP hub."
    assert _run(unexpected) == "Error: ValueError: bad thing"


def test_long_output_is_capped():
    text = _run(lambda: "a line of output\n" * 2000)
    assert len(text) <= MAX_CHARS
    assert text.endswith("Ask for something narrower.]")


def test_tools_run_core_functions_in_process():
    async def call(name, args):
        return (await server.mcp.call_tool(name, args))[0].text

    found = anyio.run(call, "search_datasets", {"query": "era5"})
    assert "### ARCO ERA5" in found
    refused = anyio.run(call, "describe_store", {"url": "/home/jovyan/data.nc"})
    assert refused.startswith("Error: Unsupported location")
