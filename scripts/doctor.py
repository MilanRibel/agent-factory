"""Check whether this laptop is ready to run the factory: uv and Docker.

Run it with `uv run scripts/doctor.py`. Each check prints one line with its
measured and required value; the exit code is 0 only when every check passes.

doctor reports only the two numbers it parses from `docker info` and never
echoes command output: a command that exits non-zero shows only its exit code,
and output that is not valid JSON shows only "invalid output".
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

GIB = 2**30
DEFAULT_MIN_MEMORY_GIB = 16  # ADR-001
DEFAULT_MIN_CPUS = 4  # milestone decision; ADR-001 names no CPU minimum
TIMEOUT_SECONDS = 10

UV_VERSION = ("uv", "--version")
DOCKER_INFO = ("docker", "info", "--format", "{{json .}}")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run argv without a shell and with a timeout.

    This is the only place where doctor starts a process.
    """
    # argv is one of the fixed tuples above, never user input, and no shell is involved.
    return subprocess.run(  # noqa: S603
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def attempt(runner: Runner, argv: Sequence[str], label: str) -> tuple[str | None, str]:
    """Run argv and describe the outcome without any of its output.

    Returns stdout when the command exits 0 (None otherwise) and the measured value
    for the check detail.
    """
    try:
        result = runner(argv)
    except FileNotFoundError:
        return None, f"{argv[0]} not found"
    except OSError:
        return None, f"{argv[0]} could not be started"
    except subprocess.TimeoutExpired:
        return None, f"{label} timed out after {TIMEOUT_SECONDS} s"
    stdout = result.stdout if result.returncode == 0 else None
    return stdout, f"{label} exited {result.returncode}"


def parse_info(stdout: str) -> dict[str, object] | None:
    """Parse the `docker info` JSON object, or return None when it is not one."""
    try:
        info: object = json.loads(stdout)
    except ValueError:
        return None
    return cast(dict[str, object], info) if isinstance(info, dict) else None


def read_int(info: dict[str, object] | None, field: str) -> int | str:
    """Return an integer field, or a message saying why it cannot be read."""
    if info is None:
        return "invalid output"
    value = info.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{field} missing or not an integer"
    return value


def gib(size: int) -> str:
    """Format bytes as GiB with two decimals, rounded down."""
    hundredths = size * 100 // GIB
    return f"{hundredths // 100}.{hundredths % 100:02d} GiB"


def check_uv(runner: Runner) -> CheckResult:
    stdout, actual = attempt(runner, UV_VERSION, "uv --version")
    return CheckResult(
        "uv", stdout is not None, f"{actual}; required: uv --version exits 0"
    )


def check_docker(
    runner: Runner, min_memory_gib: int, min_cpus: int
) -> list[CheckResult]:
    """Run `docker info` once and check the daemon, the VM memory and the CPUs."""
    min_memory = min_memory_gib * GIB
    required_memory = f"required: at least {min_memory_gib} GiB ({min_memory:,} bytes)"
    required_cpus = f"required: at least {min_cpus} CPUs"

    stdout, actual = attempt(runner, DOCKER_INFO, "docker info")
    daemon = CheckResult(
        "docker daemon", stdout is not None, f"{actual}; required: docker info exits 0"
    )
    if stdout is None:
        failed = "unknown, docker info failed"
        return [
            daemon,
            CheckResult("docker memory", False, f"{failed}; {required_memory}"),
            CheckResult("docker cpus", False, f"{failed}; {required_cpus}"),
        ]

    info = parse_info(stdout)
    memory = read_int(info, "MemTotal")
    cpus = read_int(info, "NCPU")
    if isinstance(memory, str):
        memory_check = CheckResult(
            "docker memory", False, f"{memory}; {required_memory}"
        )
    else:
        memory_check = CheckResult(
            "docker memory",
            memory >= min_memory,
            f"{memory:,} bytes ({gib(memory)}); {required_memory}",
        )
    if isinstance(cpus, str):
        cpus_check = CheckResult("docker cpus", False, f"{cpus}; {required_cpus}")
    else:
        cpus_check = CheckResult(
            "docker cpus", cpus >= min_cpus, f"{cpus} CPUs; {required_cpus}"
        )
    return [daemon, memory_check, cpus_check]


def main(argv: Sequence[str] | None = None, runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether this laptop is ready to run the factory."
    )
    parser.add_argument(
        "--min-memory-gib",
        type=int,
        default=DEFAULT_MIN_MEMORY_GIB,
        help="minimum Docker VM memory in GiB (default: %(default)s)",
    )
    parser.add_argument(
        "--min-cpus",
        type=int,
        default=DEFAULT_MIN_CPUS,
        help="minimum Docker VM CPUs (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    results = [
        check_uv(runner),
        *check_docker(runner, args.min_memory_gib, args.min_cpus),
    ]
    for result in results:
        print(f"{'PASS' if result.ok else 'FAIL'}  {result.name}: {result.detail}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
