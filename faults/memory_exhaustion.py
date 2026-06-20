"""Inject a memory_exhaustion fault via the sample_app admin API."""

from _common import inject_fault


def main() -> None:
    inject_fault("memory_exhaustion", "memory exhaustion")


if __name__ == "__main__":
    main()
