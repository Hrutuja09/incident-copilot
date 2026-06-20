"""Inject a dependency_timeout fault via the sample_app admin API."""

from _common import inject_fault


def main() -> None:
    inject_fault("dependency_timeout", "dependency timeout")


if __name__ == "__main__":
    main()
