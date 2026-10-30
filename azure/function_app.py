"""Orderline on Azure Functions (Python v2 programming model): poll the order mailbox on a timer.

Every run:
1. downloads the latest ERP reference export from the ``erp-reference`` blob container,
2. reads unread order emails from the Microsoft 365 mailbox through Microsoft Graph,
3. prepares each order with Claude (Claude API or Claude on Microsoft Foundry),
4. uploads one CSV plus a JSON sidecar per order to the ``erp-import`` container, and the
   batch review report to ``review``,
5. keeps the duplicate-PO memory in the ``orderline-state`` container.

Point the ERP import at ``erp-import`` directly, or sync it to the share the import already
watches. Nothing is released from here: every CSV row carries its review status.
"""

import logging
import os
from datetime import datetime, timezone
import tempfile
from pathlib import Path

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from orderline.erp import ErpData
from orderline.extract.claude import ClaudeExtractor
from orderline.mail.graph import GraphMailSource
from orderline.output import CsvSpec
from orderline.pipeline import run_batch
from orderline.prepare import SeenOrders
from orderline.report import write_report

app = func.FunctionApp()
SPEC = Path(__file__).parent / "columns.yaml"


@app.function_name(name="poll_order_inbox")
@app.timer_trigger(schedule="%ORDERLINE_SCHEDULE%", arg_name="timer", run_on_startup=False)
def poll_order_inbox(timer: func.TimerRequest) -> None:
    blobs = BlobServiceClient(os.environ["ORDERLINE_STORAGE_URL"], credential=DefaultAzureCredential())
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        erp_dir, out_dir, state = work / "erp", work / "out", work / "seen.json"
        _download_folder(blobs, "erp-reference", erp_dir)
        _download_file(blobs, "orderline-state", "seen.json", state)

        batch = run_batch(
            source=GraphMailSource(
                tenant_id=os.environ["GRAPH_TENANT_ID"],
                client_id=os.environ["GRAPH_CLIENT_ID"],
                client_secret=os.environ["GRAPH_CLIENT_SECRET"],  # a Key Vault reference in app settings
                mailbox=os.environ["GRAPH_MAILBOX"],
                folder=os.getenv("GRAPH_FOLDER", "Inbox"),
            ),
            erp=ErpData.load(erp_dir),
            extractor=ClaudeExtractor(),
            spec=CsvSpec.load(SPEC),
            out_dir=out_dir,
            seen=SeenOrders(state),
        )
        if batch.orders:
            report = write_report(batch, out_dir, f"Claude ({os.getenv('ORDERLINE_MODEL', 'default')})")
            _upload(blobs, "review", report, f"review-{datetime.now(timezone.utc):%Y%m%d-%H%M}.html")
        for processed in batch.orders:
            _upload(blobs, "erp-import", processed.csv_path, processed.csv_path.name)
            _upload(blobs, "erp-import", processed.sidecar_path, processed.sidecar_path.name)
        if state.exists():
            _upload(blobs, "orderline-state", state, "seen.json")
        logging.info(
            "orderline: %d orders prepared, %d skipped, %d input and %d output tokens",
            len(batch.orders), len(batch.skipped), batch.usage.input_tokens, batch.usage.output_tokens,
        )


def _download_folder(blobs: BlobServiceClient, container: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    client = blobs.get_container_client(container)
    for blob in client.list_blobs():
        (target / Path(blob.name).name).write_bytes(client.download_blob(blob.name).readall())


def _download_file(blobs: BlobServiceClient, container: str, name: str, target: Path) -> None:
    blob = blobs.get_blob_client(container, name)
    if blob.exists():
        target.write_bytes(blob.download_blob().readall())


def _upload(blobs: BlobServiceClient, container: str, path: Path, name: str) -> None:
    blobs.get_blob_client(container, name).upload_blob(path.read_bytes(), overwrite=True)
