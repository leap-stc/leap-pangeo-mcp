"""FastMCP wrapper exposing leap_pangeo_mcp.core functions as MCP tools over stdio."""

import logging
from collections.abc import Callable
from typing import Annotated, Any

import anyio
import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from leap_pangeo_mcp.core import catalog, docs, hub, knowledge, storage
from leap_pangeo_mcp.core.common import MAX_CHARS, LeapError, one_line

QUICK_TIMEOUT_SECONDS = 20  # catalog, docs and the local tools
STORAGE_TIMEOUT_SECONDS = 60

# Every tool is read-only. Open-world tools reach the catalog, docs or buckets.
LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
REMOTE = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

logger = logging.getLogger(__name__)

mcp = FastMCP("leap-pangeo", instructions=knowledge.PRIMER)

Cursor = Annotated[
    str,
    Field(description="Leave empty for the first page. For the next page, pass the cursor from the previous result."),
]


async def _run(func: Callable[..., str], *args: Any, timeout: float) -> str:
    """Run a blocking core function in a worker thread; always return text, never raise."""
    try:
        with anyio.fail_after(timeout) as scope:
            # abandon_on_cancel lets the timeout fire while the call is still blocked.
            text = await anyio.to_thread.run_sync(func, *args, abandon_on_cancel=True)
    except LeapError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        if isinstance(exc, TimeoutError) and scope.cancel_called:
            return f"Error: no answer within {timeout:.0f} s; the service may be slow or unreachable. Try again later."
        logger.exception("%s failed", getattr(func, "__name__", func))
        return f"Error: {type(exc).__name__}: {one_line(exc, 300)}"
    return _cap(text)


def _cap(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    cut = text.rfind("\n", 0, MAX_CHARS - 200)
    return text[: cut if cut > 0 else MAX_CHARS - 200] + "\n\n[Output cut at about 8,000 characters. Ask for something narrower.]"


@mcp.tool(title="LEAP overview", annotations=LOCAL, structured_output=False)
async def leap_overview() -> str:
    """Start here for any question about LEAP Pangeo: the hub, its storage, its rules or where to get help.

    Returns a short primer: what LEAP Pangeo is; the cloud buckets and what each is for
    (gs://leap-scratch deletes files after 7 days); where you may write (only under
    <bucket>/<github-username>/); the rules for credentials, lazy data loading, GPUs, Dask
    clusters and batch jobs; and where to ask for help. It does not look anything up: use the
    other tools for datasets, docs, storage contents and the user's own environment.
    """
    return await _run(knowledge.overview, timeout=QUICK_TIMEOUT_SECONDS)


@mcp.tool(title="Search LEAP datasets", annotations=REMOTE, structured_output=False)
async def search_datasets(
    query: Annotated[
        str,
        Field(description="Words to find in dataset titles, descriptions and tags, e.g. 'sea surface temperature'. Empty matches everything."),
    ] = "",
    tag: Annotated[
        str, Field(description="Only datasets with exactly this tag (case does not matter), e.g. 'zarr' or 'SST'.")
    ] = "",
    cursor: Cursor = "",
) -> str:
    """Find datasets in the LEAP data catalog (https://catalog.leap.columbia.edu).

    Use this when someone asks what data LEAP has, or needs data for a variable, region or
    model. Every word of the query must appear in a dataset's title, description or tags
    (case does not matter). Returns up to 10 datasets per page, each with its title, tags, a
    one-line description and its store ids, plus a cursor when there are more. It does not
    open or read any data and only knows datasets listed in the catalog. Next step: call
    get_dataset with an exact title from the results.
    """
    return await _run(catalog.search_datasets, query, tag, cursor, timeout=QUICK_TIMEOUT_SECONDS)


@mcp.tool(title="Get a LEAP dataset", annotations=REMOTE, structured_output=False)
async def get_dataset(
    title: Annotated[str, Field(description="The dataset's title as shown by search_datasets, e.g. 'ARCO ERA5'.")],
    cursor: Cursor = "",
) -> str:
    """Get one catalog dataset in full, with code to open each of its stores.

    Use this after search_datasets, with the dataset's exact title (case does not matter).
    Returns the description, provenance, license, maintainers and every store: its id, name,
    URL, whether it is public, and a ready-to-run `xr.open_dataset(url, ...)` snippet built
    from that store's own xarray_open_kwargs. Datasets with many stores are paged with a
    cursor. If no title matches exactly, it returns the closest titles instead. It does not
    open the data: use describe_store on a store URL to see its variables and size.
    """
    return await _run(catalog.get_dataset, title, cursor, timeout=QUICK_TIMEOUT_SECONDS)


@mcp.tool(title="Describe a Zarr store or NetCDF file", annotations=REMOTE, structured_output=False)
async def describe_store(
    url: Annotated[
        str,
        Field(description="A gs://, s3:// or OSN https:// URL of one Zarr store or one .nc file, e.g. 'gs://leap-persistent-ro/data-library-manual/CESM.zarr'."),
    ],
) -> str:
    """Show what is inside one Zarr store or one NetCDF (.nc) file without loading its data.

    Use this before opening a dataset, to see its dimensions, variables, chunking and size.
    Accepts gs:// URLs (read with the hub's credentials), s3:// URLs and OSN URLs such as
    https://nyu1.osn.mghpcc.org/<bucket>/<path> or https://ncsa.osn.xsede.org/<bucket>/<path>
    (read anonymously). Returns dimensions and sizes; each variable's dimensions, dtype, chunk
    shape and units; the global attributes (shortened); and the estimated uncompressed size.
    It opens the data lazily and never reads array values. It refuses folders, wildcards and
    other formats such as GRIB, CSV or GeoTIFF: use list_storage to find a .zarr store or .nc
    file first. It cannot read private OSN buckets.
    """
    return await _run(storage.describe_store, url, timeout=STORAGE_TIMEOUT_SECONDS)


@mcp.tool(title="List a LEAP bucket folder", annotations=REMOTE, structured_output=False)
async def list_storage(
    path: Annotated[
        str,
        Field(description="A gs:// folder or an OSN https:// folder, e.g. 'gs://leap-scratch/<github-username>/' or 'https://nyu1.osn.mghpcc.org/leap-pangeo-manual/'."),
    ],
    cursor: Cursor = "",
) -> str:
    """List what is in one folder of a LEAP bucket or on OSN, with file sizes.

    Use this to see what is in the user's folders (gs://leap-scratch/<github-username>/ and
    gs://leap-persistent/<github-username>/), in gs://leap-persistent-ro/, or under an OSN
    URL such as https://nyu1.osn.mghpcc.org/leap-pangeo-manual/. Returns up to 100 entries
    per page, sorted by name: folders end with "/" and files show their size, plus a cursor
    when there are more. It lists one level only, without folder totals, and it never
    changes, copies or deletes anything.
    """
    return await _run(storage.list_storage, path, cursor, timeout=STORAGE_TIMEOUT_SECONDS)


@mcp.tool(title="Search the LEAP docs", annotations=REMOTE, structured_output=False)
async def search_docs(
    query: Annotated[str, Field(description="A few keywords, e.g. 'dask gateway shutdown' or 'GPU types'.")],
) -> str:
    """Search the LEAP documentation (https://leap-stc.github.io) by keywords.

    Use this for how-to and policy questions about the hub, data, storage, compute, Dask,
    GPUs, batch jobs, authentication or getting help, when leap_overview is not enough.
    Returns the 5 best-matching sections, each with its title, a link to the page and a short
    excerpt. Answer from the excerpts and include the link. It searches only the LEAP docs,
    not the wider web or the data catalog (use search_datasets for data).
    """
    return await _run(docs.search_docs, query, timeout=QUICK_TIMEOUT_SECONDS)


@mcp.tool(title="Show my hub environment", annotations=LOCAL, structured_output=False)
async def get_my_environment() -> str:
    """Show the user's own hub server: who they are, what it can do and where they may write.

    Use this when an answer depends on the user: their username, which image they run, how
    much memory and CPU they have, whether a GPU is attached, or their personal folders.
    Returns JUPYTERHUB_USER, JUPYTER_IMAGE_SPEC, MEM_LIMIT, CPU_LIMIT, the GPU name from
    nvidia-smi, and gs://leap-scratch/<user>/ and gs://leap-persistent/<user>/. Missing
    values are shown as "not set (not on the LEAP hub?)". It reads only those values and
    nvidia-smi, shows no secrets and changes nothing.
    """
    return await _run(hub.get_my_environment, timeout=QUICK_TIMEOUT_SECONDS)


@mcp.tool(title="How to do a LEAP task", annotations=LOCAL, structured_output=False)
async def how_to(
    task: Annotated[
        str, Field(description="One of: 'write_to_my_folder', 'start_dask_cluster', 'copy_to_osn'.")
    ],
) -> str:
    """Give a tested code snippet for a common LEAP task.

    task is one of: write_to_my_folder (save results to the user's own GCS folder),
    start_dask_cluster (start a Dask Gateway cluster and shut it down), or copy_to_osn (copy a
    Zarr store from GCS to the OSN inbox to share it publicly). Returns Python code, with the
    user's GitHub username filled in when JUPYTERHUB_USER is set, plus short notes and the
    docs page it is based on. Unknown tasks return the list of valid ones. It does not run
    the code: show it to the user to run. The OSN snippet asks for keys when it runs and never
    contains them.
    """
    return await _run(knowledge.how_to, task, timeout=QUICK_TIMEOUT_SECONDS)


def main() -> None:
    """Run the server over stdio (console script: leap-pangeo-mcp)."""
    mcp.run()


if __name__ == "__main__":
    main()
