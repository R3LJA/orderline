import base64
import json

import httpx

from orderline.mail import FolderMailSource, GraphMailSource, classify_message, parse_eml

from .conftest import SAMPLES, message


def test_parse_eml_reads_sender_subject_and_pdf():
    msg = parse_eml((SAMPLES / "inbox" / "01-northwind-4500884512.eml").read_bytes(), "01.eml")
    assert msg.sender == "purchasing@northwindhealth.example"
    assert msg.sender_domain == "northwindhealth.example"
    assert "4500884512" in msg.subject
    assert len(msg.pdfs) == 1 and msg.pdfs[0].data.startswith(b"%PDF")


def test_folder_source_remembers_processed_messages(tmp_path):
    state = tmp_path / "state.json"
    source = FolderMailSource(SAMPLES / "inbox", state_file=state)
    first = list(source.fetch_new())
    assert len(first) == 15
    source.mark_processed(first[0], "prepared")
    again = FolderMailSource(SAMPLES / "inbox", state_file=state)
    assert len(list(again.fetch_new())) == 14
    assert json.loads(state.read_text())[first[0].id] == "prepared"


def test_classifier_accepts_a_purchase_order():
    verdict = classify_message(message(subject="PO 4500884512", body="Please see attached purchase order."))
    assert verdict.is_order and verdict.score > 0


def test_classifier_rejects_invoice_quote_and_newsletter():
    for subject in ("Invoice INV-20931", "Request for quotation: splints", "October newsletter, unsubscribe below"):
        assert not classify_message(message(subject=subject)).is_order


def test_classifier_rejects_mail_without_pdf():
    verdict = classify_message(message(pdfs=()))
    assert not verdict.is_order and verdict.reasons == ["no PDF attached"]


def test_classifier_lets_a_bare_pdf_through_to_the_model():
    assert classify_message(message(subject="scan", body="")).is_order


def test_classifier_keeps_a_po_that_mentions_a_quote():
    verdict = classify_message(message(subject="Purchase order 5521", body="Per your quote Q-88, PO attached."))
    assert verdict.is_order


def _graph_transport(calls):
    pdf = base64.b64encode(b"%PDF-1.7 fake").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        url = str(request.url)
        if "login.microsoftonline.com" in url:
            return httpx.Response(200, json={"access_token": "token-1"})
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        if url.endswith("/attachments"):
            return httpx.Response(200, json={"value": [
                {"@odata.type": "#microsoft.graph.fileAttachment", "name": "PO-1.pdf",
                 "contentType": "application/pdf", "contentBytes": pdf},
                {"@odata.type": "#microsoft.graph.itemAttachment", "name": "forwarded"},
            ]})
        if "page2" in url:
            return httpx.Response(200, json={"value": [_graph_message("m2")]})
        return httpx.Response(200, json={
            "value": [_graph_message("m1")],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/users/orders@x.example/mailFolders/Inbox/messages?page2",
        })

    return httpx.MockTransport(handler)


def _graph_message(mid):
    return {"id": mid, "subject": "PO 77", "hasAttachments": True, "receivedDateTime": "2026-10-29T12:00:00Z",
            "from": {"emailAddress": {"address": "Buyer@Northwindhealth.example"}}, "body": {"content": "PO attached"}}


def test_graph_source_pages_and_decodes_attachments():
    calls = []
    source = GraphMailSource("tenant", "client", "secret", "orders@x.example", http=httpx.Client(transport=_graph_transport(calls)))
    messages = list(source.fetch_new())
    assert [m.id for m in messages] == ["m1", "m2"]
    assert messages[0].sender == "buyer@northwindhealth.example"
    assert [a.filename for a in messages[0].attachments] == ["PO-1.pdf"]  # item attachments are skipped
    assert messages[0].attachments[0].data == b"%PDF-1.7 fake"
    listing = next(c for c in calls if c.url.path.endswith("/messages") and c.method == "GET")
    assert "isRead eq false" in listing.url.params["$filter"]
    assert listing.headers["Prefer"] == 'outlook.body-content-type="text"'
    assert listing.headers["Authorization"] == "Bearer token-1"


def test_graph_source_marks_messages_read_and_tagged():
    calls = []
    source = GraphMailSource("tenant", "client", "secret", "orders@x.example", http=httpx.Client(transport=_graph_transport(calls)))
    msg = next(iter(source.fetch_new()))
    source.mark_processed(msg, "prepared")
    patch = [c for c in calls if c.method == "PATCH"][0]
    assert patch.url.path.endswith("/messages/m1")
    assert json.loads(patch.content) == {"isRead": True, "categories": ["Orderline", "Orderline: prepared"]}
