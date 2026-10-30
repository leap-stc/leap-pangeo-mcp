"""The LEAP primer and the how_to snippets.

Sources: https://leap-stc.github.io/data/data_locations/, .../data/data_tools/,
.../compute/dask/, .../compute/compute_scaling/, .../compute/skypilot/ and
.../support/contact/. Each snippet is executed in tests/test_knowledge.py.
"""

import os

PRIMER = """\
# LEAP Pangeo primer

LEAP Pangeo is the cloud platform of LEAP (Learning the Earth with Artificial Intelligence and Physics, an NSF Science and Technology Center at Columbia University): a JupyterHub on Google Cloud with the Pangeo stack (xarray, Dask, Zarr), shared cloud buckets, a data catalog and Dask Gateway.

## Where data lives
- `gs://leap-scratch/`: temporary. Files are deleted after 7 days. Use it for tests and large intermediate results.
- `gs://leap-persistent/`: kept until you delete it. Use it for results you reuse or share inside LEAP.
- `gs://leap-persistent-ro/`: read-only. Curated datasets from the LEAP data library.
- OSN (Open Storage Network, https://nyu1.osn.mghpcc.org): for sharing data publicly, with no egress fees. Write keys come from the Data & Compute team.
- Write only under `<bucket>/<github-username>/`, for example `gs://leap-persistent/<github-username>/`. Every LEAP member can read the buckets.
- Your home directory (/home/jovyan) is for code, notebooks and small files only. Put data in a bucket.

## Rules
- Never put credentials (keys, tokens, passwords) in a bucket or in a batch-job pull request.
- Open data lazily, e.g. `xr.open_dataset(url, engine="zarr", chunks={})`, select what you need, then compute. Don't load whole arrays into memory.
- GPU: start on a T4. Move to an L4 or A100 only when you hit a specific limit, and stop GPU servers when you finish.
- Dask Gateway: shut clusters down when you are done (`cluster.shutdown()`) so the nodes return to the shared pool.
- Long or heavy jobs run as batch jobs: open a pull request to leap-stc/LEAP-batch-jobs.

## Getting help
- Docs: https://leap-stc.github.io
- Data catalog: https://catalog.leap.columbia.edu
- Ask in the LEAP Slack (#leap-pangeo, #technical_questions) and tag @data-and-compute.

## Tools in this server
- Find data: search_datasets, then get_dataset for store URLs and an open snippet.
- Inspect data: describe_store (variables, chunks, size; loads no values) and list_storage (folder contents).
- Docs and setup: search_docs, get_my_environment (your user, limits, folders) and how_to (tested snippets).
"""

USER_PLACEHOLDER = "<github-username>"

_WRITE_TO_MY_FOLDER = '''\
import fsspec
import xarray as xr

user = "<github-username>"  # your GitHub username, as in JUPYTERHUB_USER
scratch = f"gs://leap-scratch/{user}"  # deleted after 7 days
persistent = f"gs://leap-persistent/{user}"  # kept until you delete it

# `ds` is your xarray Dataset. Writing it computes it chunk by chunk.
ds.to_zarr(f"{persistent}/my_result.zarr", mode="w")

# Other files (CSV, Parquet, raw bytes) go through a file object.
fs = fsspec.filesystem("gs")
with fs.open(f"{scratch}/notes.txt", "wb") as f:
    f.write(b"written from the LEAP hub")

# Check your folder, then reopen the result lazily.
print(fs.ls(persistent))
ds = xr.open_dataset(f"{persistent}/my_result.zarr", engine="zarr", chunks={})
'''

_START_DASK_CLUSTER = '''\
from dask_gateway import Gateway

gateway = Gateway()  # preconfigured on the LEAP hub
options = gateway.cluster_options()
# options.worker_memory = 8  # GB per worker; raise it if workers get killed
cluster = gateway.new_cluster(options)
cluster.adapt(minimum=1, maximum=10)  # or cluster.scale(4) for a fixed size
client = cluster.get_client()
print(client.dashboard_link)  # memory, progress and task graphs

# Your work, kept lazy until the final compute or write, e.g.:
# ds = xr.open_dataset(url, engine="zarr", chunks={})
# ds.mean("time").to_zarr("gs://leap-scratch/<github-username>/mean.zarr")

# Shut down when you are done so the nodes go back to the shared pool.
client.close()
cluster.shutdown()
'''

_COPY_TO_OSN = '''\
import getpass
import os

import xarray as xr

user = "<github-username>"  # your GitHub username, as in JUPYTERHUB_USER

# OSN write keys come from the Data & Compute team. Never write them into a
# notebook, a bucket or a git repository: batch jobs get them as environment
# variables, and in a notebook you type them when prompted.
osn = {
    "key": os.environ.get("OSN_ACCESS_KEY_INBOX") or getpass.getpass("OSN access key: "),
    "secret": os.environ.get("OSN_SECRET_KEY_INBOX") or getpass.getpass("OSN secret key: "),
    "client_kwargs": {"endpoint_url": "https://nyu1.osn.mghpcc.org"},
}

# Copy a Zarr store from your GCS folder to the OSN inbox, chunk by chunk.
src = f"gs://leap-persistent/{user}/my_result.zarr"
dst = f"s3://leap-pangeo-inbox/{user}/my_result.zarr"
ds = xr.open_dataset(src, engine="zarr", chunks={})
ds.to_zarr(dst, mode="w", storage_options=osn)

# Read it back to check the copy.
print(xr.open_dataset(dst, engine="zarr", chunks={}, storage_options=osn))
'''

# task -> (title, snippet, notes)
TASKS = {
    "write_to_my_folder": (
        "Write results to your personal folder on GCS",
        _WRITE_TO_MY_FOLDER,
        [
            "Only write under your own folder: gs://leap-scratch/<github-username>/ or "
            "gs://leap-persistent/<github-username>/.",
            "leap-scratch deletes files after 7 days; leap-persistent keeps them until you delete them.",
            "Source: https://leap-stc.github.io/data/data_tools/#writing-to-gcs",
        ],
    ),
    "start_dask_cluster": (
        "Start a Dask Gateway cluster and shut it down",
        _START_DASK_CLUSTER,
        [
            "Aim for chunks of about 100 MB; stay lazy until the final compute or write.",
            "Always run cluster.shutdown() when you finish, even after an error.",
            "Source: https://leap-stc.github.io/compute/dask/",
        ],
    ),
    "copy_to_osn": (
        "Copy a Zarr store from GCS to the OSN inbox for public sharing",
        _COPY_TO_OSN,
        [
            "Ask the Data & Compute team for leap-pangeo-inbox write keys on the LEAP Slack "
            "(tag @data-and-compute).",
            "For more than a few GB, use rclone instead: "
            "`rclone copy leap-gcs:leap-persistent/<github-username>/my_result.zarr "
            "leap-inbox:leap-pangeo-inbox/<github-username>/my_result.zarr` "
            "(remote setup: https://leap-stc.github.io/data/data_tools/#rclone).",
            "Source: https://leap-stc.github.io/data/data_tools/#writing-to-osn-via-s3-interface",
        ],
    ),
}


def overview() -> str:
    return PRIMER


def how_to(task: str) -> str:
    key = task.strip().lower()
    if key not in TASKS:
        valid = "\n".join(f"- `{name}`: {title}" for name, (title, _, _) in TASKS.items())
        return f"Unknown task {task!r}. Valid tasks:\n{valid}"

    title, snippet, notes = TASKS[key]
    user = os.environ.get("JUPYTERHUB_USER", "").strip()
    if user:
        snippet = snippet.replace(USER_PLACEHOLDER, user)
        notes = [note.replace(USER_PLACEHOLDER, user) for note in notes]
    else:
        notes = [
            f"JUPYTERHUB_USER is not set (not on the LEAP hub?). Replace {USER_PLACEHOLDER} "
            "with your GitHub username.",
            *notes,
        ]
    bullets = "\n".join(f"- {note}" for note in notes)
    return f"# {title}\n\n```python\n{snippet}```\n\n{bullets}\n"
