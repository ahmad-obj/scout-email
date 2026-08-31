from __future__ import annotations

import json
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / "n8n" / "workflows" / "follow-up.json"
)


def test_followup_workflow_uses_gmail_reply_and_backend_owned_copy():
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["active"] is False

    nodes = {node["name"]: node for node in workflow["nodes"]}
    receive = nodes["Receive Follow-up"]
    gmail = nodes["Gmail Reply"]
    success = nodes["Callback Success"]
    failure = nodes["Callback Failure"]

    assert receive["parameters"]["authentication"] == "headerAuth"
    assert gmail["type"] == "n8n-nodes-base.gmail"
    assert gmail["parameters"]["resource"] == "message"
    assert gmail["parameters"]["operation"] == "reply"
    assert gmail["parameters"]["messageId"] == (
        "={{ $('Receive Follow-up').item.json.body.reply_to_message_id }}"
    )
    assert gmail["parameters"]["emailType"] == "text"
    assert gmail["parameters"]["message"] == (
        "={{ $('Receive Follow-up').item.json.body.body }}"
    )
    assert gmail["parameters"]["options"]["appendAttribution"] is False

    assert "/provider-result" in success["parameters"]["url"]
    assert "provider_message_id" in success["parameters"]["body"]
    assert "provider_thread_id" in success["parameters"]["body"]
    assert "X-Scout-Email-Secret" in json.dumps(success)
    assert "status: 'FAILED'" in failure["parameters"]["body"]

    rendered = json.dumps(workflow)
    assert "sendTo" not in json.dumps(gmail)
    assert "subject" not in gmail["parameters"]
    assert "reply_to_message_id" in rendered
