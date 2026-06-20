"""Inject a bad_deploy fault via the sample_app admin API."""

from _common import inject_fault


def main() -> None:
    inject_fault("bad_deploy", "bad deploy")


if __name__ == "__main__":
    main()
