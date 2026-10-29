"""The Textract label fallback needs three things to line up: the setting, the pod permission and the boundary."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_fallback_is_enabled_in_the_shared_configuration():
    data = yaml.safe_load((ROOT / "deploy/kubernetes/apps/base/shared/configmap.yaml").read_text())["data"]
    assert data["TEXTRACT_FALLBACK"] == "true"


def test_vision_pod_may_read_text_but_nothing_else_from_textract():
    source = (ROOT / "infra/terraform/modules/workload-identity/main.tf").read_text()
    vision = source[source.index('resource "aws_iam_role_policy" "vision"'):source.index('resource "aws_iam_role_policy" "forecast"')]
    assert '"textract:DetectDocumentText"' in vision
    assert source.count("textract:") == 1  # only the vision role, only this action


def test_permissions_boundary_allows_the_textract_action_it_grants():
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    statements = template["Resources"]["WorkloadBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    statement = next(s for s in statements if s["Sid"] == "TextractLabelReading")
    assert statement["Effect"] == "Allow" and statement["Action"] == ["textract:DetectDocumentText"]
