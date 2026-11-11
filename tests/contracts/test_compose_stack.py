"""compose stack"""

from __future__ import annotations

import re

import pytest
from contract_helpers import (
    REPO_ROOT,
)

pytestmark = pytest.mark.contract


#
# The node's ports are docker host-publishes plus in-stack listeners, not overlay
# sockets, so they live in `node_ports` beside `ports` rather than inside it: a
# shared NUMBER (9090, 4222) is a documentation signal, not a merge. These
# tests keep the declaration and spark.compose.yml from drifting apart, and keep
# the two namespaces from collapsing back into one dict.

COMPOSE = REPO_ROOT / "spark.compose.yml"

NODE_PORT_STATES = {"implemented", "provisioned", "spec-only"}
NODE_PORT_RUNTIME = {"running", "not-listening", "not-verifiable-here"}


def _compose_ports() -> dict[int, int]:
    """host_port -> container_port for every published mapping in spark.compose.yml."""
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    published: dict[int, int] = {}
    for _service, spec in (compose.get("services") or {}).items():
        for mapping in spec.get("ports") or []:
            parts = str(mapping).split(":")
            host, container = int(parts[-2]), int(parts[-1])
            assert host not in published, (
                f"spark.compose.yml publishes host port {host} twice; a second "
                f"publish is a conflict compose cannot express"
            )
            published[host] = container
    return published


def test_node_ports_are_declared_and_have_the_honest_axes(ports: dict):
    """Every node port declares its namespace, its bind and both state axes."""
    node = ports.get("node_ports")
    assert node, "the node's ports must be contracted in node_ports, not left implicit"
    for number, spec in node.items():
        assert spec.get("service"), f"node port {number} names no service"
        assert spec.get("bound_by") == "node", (
            f"node port {number} must be bound_by 'node' — the compose stack is not a peer/master role"
        )
        assert isinstance(spec.get("host_published"), bool), (
            f"node port {number} must say whether it is published to the host"
        )
        assert spec.get("container_port"), f"node port {number} names no container port"
        assert spec.get("implementation_state") in NODE_PORT_STATES, (
            f"node port {number} has an unknown implementation_state: {spec.get('implementation_state')!r}"
        )
        assert spec.get("runtime") in NODE_PORT_RUNTIME, (
            f"node port {number} has an unknown runtime: {spec.get('runtime')!r}"
        )
        if spec["runtime"] != "running":
            assert spec.get("runtime_why"), f"node port {number} is not running here; it must record why"


def test_node_ports_match_what_compose_actually_publishes(ports: dict):
    """The declared host-published set is exactly the set compose maps."""
    node = ports["node_ports"]
    published = _compose_ports()
    declared = {int(n) for n, s in node.items() if s.get("host_published")}
    assert declared == set(published), (
        f"node_ports and spark.compose.yml disagree on published host ports: "
        f"declared-only={sorted(declared - set(published))}, "
        f"compose-only={sorted(set(published) - declared)}"
    )
    for host, container in published.items():
        spec = node[str(host)]
        assert spec["container_port"] == container, (
            f"node port {host} maps to container {container} in compose but node_ports says {spec['container_port']}"
        )
        if host in (8080, 8081, 3000, 8000):
            assert spec["host_bind"] == "${SPARKNET_BIND_API:-0.0.0.0}", (
                f"node port {host} is a LAN API and must keep the wildcard default"
            )
        else:
            assert spec["host_bind"] == "${SPARKNET_BIND_LOCAL:-127.0.0.1}", (
                f"node port {host} is host-local tooling and must stay loopback by default"
            )


def test_unpublished_node_ports_are_absent_from_compose_publishing(ports: dict):
    """A node port marked host_published:false must not be in compose's ports:."""
    node = ports["node_ports"]
    published = _compose_ports()
    text = COMPOSE.read_text()
    for number, spec in node.items():
        if spec.get("host_published"):
            continue
        assert int(number) not in published, f"node port {number} is declared unpublished but compose publishes it"
        assert str(spec["container_port"]) in text, (
            f"unpublished node port {number} ({spec['service']}) names a container "
            f"port that appears nowhere in spark.compose.yml — the declaration drifted"
        )


def test_node_and_fabric_port_namespaces_stay_separate(ports: dict):
    """A shared number must be recorded as a collision, never merged into one entry."""
    fabric = set(ports["ports"])
    node = set(ports.get("node_ports", {}))
    assert fabric and node, "both namespaces must be populated"

    for number in sorted(fabric & node, key=int):
        spec = ports["node_ports"][number]
        assert spec.get("collides_number_with"), f"port {number} exists in both namespaces; the node entry must say so"
        assert spec.get("collision_note"), (
            f"node port {number} collides with a fabric number and must explain "
            f"how a same-host deployment keeps them apart"
        )


def test_setup_script_advertises_only_profiles_compose_defines():
    """`--profiles` names must be real, or the setup script promises a no-op.

    The setup script hands its profile list straight to `docker compose
    --profile`; a name with no service behind it is silently ignored by compose,
    so an operator believes a service started that never did.
    """
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    defined: set[str] = set()
    for spec in (compose.get("services") or {}).values():
        for profile in spec.get("profiles") or []:
            defined.add(str(profile))

    advertised: set[str] = set()
    for line in (REPO_ROOT / "sparknet-node-setup.py").read_text().splitlines():
        if "--profiles A,B,C" in line:
            advertised = set(line.split(":", 1)[1].split())
            break
    assert advertised, "could not find the advertised profile list in the setup script"

    unknown = advertised - defined
    assert not unknown, f"sparknet-node-setup.sh advertises profiles compose does not define: {sorted(unknown)}"
    undeclared = defined - advertised
    assert not undeclared, f"compose defines profiles the setup script does not advertise: {sorted(undeclared)}"


def test_node_foreign_images_are_pinned():
    """A node image that floats is not reproducible: `main`/`latest` move.

    Two node stacks ship (DGX Spark, AGX Xavier — goagx/), and each rides two
    foreign images. The NATS one must be the same release as the nats-server
    baked into its node image (that dockerfile's NATS_VERSION), or the
    upstream bus and the in-image binary disagree; the WebUI one must be an
    immutable release tag, not a rolling branch. The two stacks must also
    agree with each other: one fabric, one bus release.
    """
    import yaml

    stacks = [
        ("spark.docker", REPO_ROOT / "spark.docker", COMPOSE),
        (
            "goagx/goagx/sparknet.agx.docker",
            REPO_ROOT / "goagx" / "goagx" / "sparknet.agx.docker",
            REPO_ROOT / "goagx" / "goagx" / "sparknet.agx.compose.yml",
        ),
    ]
    nats_versions: dict[str, str] = {}
    for dname, dockerfile, compose_path in stacks:
        compose = yaml.safe_load(compose_path.read_text())
        services = compose["services"]

        assert ":${NATS_IMAGE_TAG:-2." in services["nats"]["image"], (
            f"{compose_path.name}: the nats service must keep a pinned default tag"
        )
        docker_nats = re.search(r"ARG NATS_VERSION=([\w.\-]+)", dockerfile.read_text())
        assert docker_nats, f"{dname} no longer pins NATS_VERSION"
        compose_nats = re.search(r"NATS_IMAGE_TAG:-([\w.\-]+)", services["nats"]["image"])
        assert compose_nats, f"cannot read {compose_path.name} nats tag default"
        assert compose_nats.group(1) == f"{docker_nats.group(1)}-alpine", (
            f"compose nats tag {compose_nats.group(1)!r} must track {dname} "
            f"NATS_VERSION {docker_nats.group(1)!r} (as <version>-alpine)"
        )
        nats_versions[dname] = docker_nats.group(1)

        webui = services["webui"]["image"]
        default = re.search(r"WEBUI_TAG:-([\w.\-]+)", webui)
        assert default, f"{compose_path.name}: the webui service must keep an overridable pinned tag"
        tag = default.group(1)
        assert tag not in ("main", "latest", "dev"), (
            f"the webui default tag {tag!r} is a rolling tag; pin a release (e.g. v0.12.2)"
        )
        assert re.match(r"^v?\d+\.\d+\.\d+", tag), f"the webui default tag {tag!r} is not a release version"

    assert len(set(nats_versions.values())) == 1, f"the two node stacks disagree on the bus release: {nats_versions}"
