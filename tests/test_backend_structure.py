"""The two Spring Boot services are self-contained and share one layered structure:
controller -> service -> repository, plus dto, config and exception packages."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"inventory": "services/inventory", "workshop": "services/workshop"}
LAYERS = {"controller", "service", "repository", "dto", "config", "exception"}
# Each service keeps its own copy of these cross-cutting classes (no shared library).
COPIED = ["config/SecurityConfig.java", "exception/ConflictException.java", "exception/NotFoundException.java",
          "exception/GlobalExceptionHandler.java", "service/Commands.java", "repository/CommandRepository.java"]


def main_dir(name):
    return ROOT / SERVICES[name] / "src/main/java/com/stocklane" / name


def main_sources(name):
    return sorted(main_dir(name).rglob("*.java"))


def layer(path):
    parts = path.relative_to(ROOT).parts
    return next((p for p in parts if p in LAYERS), "root")


def test_each_service_has_every_layer_and_an_entry_point():
    for name in SERVICES:
        layers = {layer(p) for p in main_sources(name)}
        assert LAYERS <= layers, (name, layers)
        assert (main_dir(name) / f"{name.capitalize()}Application.java").exists()


def test_services_are_self_contained():
    assert not (ROOT / "packages").exists()
    for name, base in SERVICES.items():
        pom = (ROOT / base / "pom.xml").read_text()
        assert "platform-java" not in pom, name
        for path in [*main_sources(name), *(ROOT / base / "src/test/java").rglob("*.java")]:
            text = path.read_text()
            assert "com.stocklane.platform" not in text, path.relative_to(ROOT)
            other = "workshop" if name == "inventory" else "inventory"
            assert f"com.stocklane.{other}." not in text, f"{path.relative_to(ROOT)} must not import the other service"


def test_copied_cross_cutting_classes_stay_identical():
    def normalised(name, rel):
        return (main_dir(name) / rel).read_text().replace(f"com.stocklane.{name}", "com.stocklane.SERVICE")
    for rel in COPIED:
        assert normalised("inventory", rel) == normalised("workshop", rel), f"{rel} differs between the services"


def test_sql_only_lives_in_repositories():
    for name in SERVICES:
        for path in main_sources(name):
            if layer(path) == "repository":
                continue
            text = path.read_text()
            assert "JdbcTemplate" not in text, f"{path.relative_to(ROOT)} must go through a repository"
            assert not re.search(r'"\s*(select\b[^"]*\bfrom\b|insert into\b|update \w+ set\b|delete from\b)', text, re.I), path.relative_to(ROOT)


def test_controllers_only_call_services_and_dtos():
    for name in SERVICES:
        for path in main_sources(name):
            if layer(path) == "controller":
                assert ".repository." not in path.read_text(), path.name


def test_repositories_do_not_depend_on_services_or_controllers():
    for name in SERVICES:
        for path in main_sources(name):
            if layer(path) == "repository":
                text = path.read_text()
                assert ".service." not in text and ".controller." not in text, path.name


def test_class_names_match_their_layer():
    for name in SERVICES:
        for path in main_sources(name):
            if layer(path) == "service":
                assert re.search(r"(Service|Verifier|Relay|Files|Queue|Commands)$", path.stem), path.name
            if layer(path) == "controller":
                assert path.stem.endswith("Controller"), path.name
            if layer(path) == "repository":
                assert path.stem.endswith("Repository"), path.name
