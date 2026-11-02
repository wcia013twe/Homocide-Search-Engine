"""Build a clean Databricks Apps source folder without credentials or UI files."""
import argparse
from pathlib import Path
import shutil


MODULES = (
    "__init__.py", "agent_server.py", "agent_service.py", "research_agent.py",
    "research_triage.py", "search_audit.py", "search_provider.py", "providers.py",
    "exa.py", "brave.py", "research_review.py", "research_session.py",
    "hosted_session.py", "audit_review.py",
)


def package(destination: Path, stateful: bool = False) -> Path:
    root = Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    modules = destination / "research_app"
    modules.mkdir()
    for name in MODULES:
        shutil.copyfile(root / "research_app" / name, modules / name)
    manifest = "research-agent-stateful.app.yaml" if stateful else "research-agent.app.yaml"
    shutil.copyfile(root / "hosting" / manifest, destination / "app.yaml")
    shutil.copyfile(root / "hosting" / "requirements.txt", destination / "requirements.txt")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="A NEW source directory; existing directories are refused")
    parser.add_argument("--stateful", action="store_true", help="Include the shared checkpoint secret resource")
    args = parser.parse_args()
    print(package(args.destination, args.stateful))
