"""The remaining Step 89 contracts are closed and carry no authority."""

from __future__ import annotations

import pytest
from contract_helpers import load

pytestmark = pytest.mark.contract


def test_agent_contract_is_bounded_and_authority_free():
    schema = load("agent-schema.json")
    assert schema["descriptor"]["schema"] == "sparknet-agent/1"
    assert set(schema["descriptor"]["roles"]) == {"engineering", "cyber", "vault-curator"}
    assert "max_classification" in schema["descriptor"]["required"]
    assert set(schema["descriptor"]["classifications"]) == {"public", "internal", "confidential", "restricted"}
    text = " ".join(schema["rules"]).lower()
    assert "never authority" in text
    assert "never writes a vault page" in text
    assert "defensive-only" in text
    assert "signer socket" in text


def test_self_improvement_contract_requires_benchmarks_and_rollback():
    schema = load("self-improvement-schema.json")
    assert schema["run"]["schema"] == "sparknet-self-improvement/1"
    assert set(schema["run"]["modes"]) == {"worktree", "firecracker"}
    assert "promote" in schema["run"]["decisions"]
    assert "rollback" in schema["run"]["decisions"]
    text = " ".join(schema["rules"]).lower()
    assert "no benchmark, no promotion" in text
    assert "no auto-merge" in text
    assert schema["fallback"]["mode"] == "worktree"
    assert "feature/* -> develop" in schema["promotion"]["gitflow"]
    assert "source_branch" in schema["run"]["fields"]


def test_release_contract_binds_artifacts_to_the_package_index():
    schema = load("release-schema.json")
    assert schema["release"]["schema"] == "sparknet-release/1"
    assert "package_index_sha256" in schema["release"]["required"]
    assert set(schema["release"]["channels"]) == {"stable", "candidate", "test"}
    text = " ".join(schema["rules"]).lower()
    assert "cannot grant a capability" in text
    assert "explicit operator action" in schema["distribution"]["install"].lower()


def test_data_lake_is_consented_and_never_served():
    schema = load("data-lake-schema.json")
    assert schema["extends"] == "uplift-schema.json"
    assert schema["record"]["schema"] == "sparknet-data-lake/1"
    assert "consent" in schema["record"]["required"]
    text = " ".join(schema["rules"]).lower()
    assert "never authority" in text
    assert "never served" in schema["storage"]["never_served"].lower()


def test_exec_policy_is_closed_and_validate_only_by_default():
    schema = load("exec-schema.json")
    policy = schema["policy"]
    assert policy["schema"] == "sparknet-exec-policy/1"
    assert "allowed_argv" in policy["fields"]
    text = " ".join(policy["rules"]).lower()
    assert "no allowlist, no execution" in text
    assert "starts validate-only" in text
    assert "never accepts a shell" in text


def test_pipeline_contract_requires_confirmation_and_inheritance():
    schema = load("pipeline-schema.json")
    assert schema["o2"]["marker"].startswith("<!-- o2-source:")
    assert set(schema["eligibility"]["states"]) == {"signed", "sanitized"}
    text = " ".join(schema["rules"]).lower()
    assert "never deleted" in text
    assert "human action" in text
    assert "not authority" in text


def test_container_registry_is_private_and_read_only():
    schema = load("container-registry-schema.json")
    assert schema["surface"]["binding"].startswith("loopback only")
    text = " ".join(schema["rules"]).lower()
    assert "no push route" in text
    assert "no token, no response" in text
    assert "not a knowledge channel" in text
