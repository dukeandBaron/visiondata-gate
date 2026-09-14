"""Legal upload/annotation limits must not overflow presentation summaries."""

from io import BytesIO
import hashlib
import json

from PIL import Image

from tests import test_operator_workspace as helpers

HEADERS, WORKSPACE, _upload = helpers.HEADERS, helpers.WORKSPACE, helpers._upload
operator_client = helpers.operator_client


def test_analysis_handles_maximum_duplicate_batch(operator_client):
    client, service = operator_client
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (80, 120, 160)).save(buffer, format="PNG")
    uploaded = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
        files=[
            ("files", (f"copy-{i}.png", buffer.getvalue(), "image/png"))
            for i in range(64)
        ],
    )
    assert uploaded.status_code == 201, uploaded.text
    assets = uploaded.json()["assets"]
    endpoint = f"/v1/operator-workspaces/{WORKSPACE}/assets/{assets[0]['asset_id']}/analysis-runs"
    response = client.post(endpoint, headers=HEADERS)
    assert response.status_code == 201, response.text
    run = response.json()
    event = next(e for e in run["events"] if e["action"] == "lookup_duplicate_ledger")
    assert len(event["summary"]) <= 1200
    assert "63" in event["summary"]
    digest = event["evidence_refs"][0].split(":")[-1]
    evidence = (
        service.product_root
        / "operator_workspace"
        / "usr_local_demo"
        / WORKSPACE
        / assets[0]["asset_id"]
        / "analysis_evidence"
        / f"{digest}.json"
    ).read_bytes()
    assert hashlib.sha256(evidence).hexdigest() == digest
    assert len(json.loads(evidence)["duplicate_asset_ids"]) == 63
    assert client.get(endpoint, headers=HEADERS).json() == [run]


def test_analysis_handles_maximum_legal_annotation_labels(operator_client):
    client, _ = operator_client
    image = Image.new("RGB", (48, 32))
    image.putdata(
        [
            (40, 40, 40) if (x + y) % 2 else (210, 210, 210)
            for y in range(32)
            for x in range(48)
        ]
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    asset = _upload(client, buffer.getvalue())
    root = f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}"
    annotations = [
        dict(
            annotation_id=f"box_{i:03}",
            label=f"{i:03}-" + "x" * 116,
            x=0.1,
            y=0.1,
            width=0.2,
            height=0.2,
            source="MANUAL",
        )
        for i in range(500)
    ]
    saved = client.put(
        root + "/annotations",
        headers=HEADERS,
        json={"expected_revision": 0, "annotations": annotations},
    )
    assert saved.status_code == 200, saved.text
    response = client.post(root + "/analysis-runs", headers=HEADERS)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["recommendation"]["code"] == "ANNOTATION_REVIEW"
    assert len(run["recommendation"]["summary"]) <= 1200
    assert run["annotation_document_sha256"] == saved.json()["document_sha256"]
    assert (
        len(client.get(root + "/annotations", headers=HEADERS).json()["annotations"])
        == 500
    )
