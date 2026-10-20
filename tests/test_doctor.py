"""Tests for scripts/doctor.py: every check runs against a fake runner.

scripts/ is not a package, so each test loads doctor from its path. An autouse
fixture replaces subprocess.Popen with a stub that fails the test, so no test in
this file can start a real process, docker included. The stub does not catch
calls that bypass subprocess, such as os.system.
"""

import importlib.util
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"

GIB = 2**30
# Planted in fake command output; it must never show up in doctor's output.
MARKER = "MARKER-doctor-echo-7f3a"

REQUIRED_UV = "required: uv --version exits 0"
REQUIRED_DOCKER = "required: docker info exits 0"
REQUIRED_MEMORY = "required: at least 16 GiB (17,179,869,184 bytes)"
REQUIRED_CPUS = "required: at least 4 CPUs"

# One line per check: "PASS  docker memory: <actual>; required: <required>".
LINE = re.compile(r"(PASS|FAIL)  ([a-z ]+): (.+)")

Outcome = subprocess.CompletedProcess[str] | BaseException


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail(f"test started a real process: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", refuse)


def load_doctor() -> ModuleType:
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def docker_info(mem_total: int = 24 * GIB, ncpu: int = 8, **extra: object) -> str:
    return json.dumps({"MemTotal": mem_total, "NCPU": ncpu, **extra})


class FakeRunner:
    """Answers each command by its program name and logs every call."""

    def __init__(self, docker: Outcome, uv: Outcome | None = None) -> None:
        self.outcomes = {
            "uv": completed("uv 0.10.12") if uv is None else uv,
            "docker": docker,
        }
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        outcome = self.outcomes[argv[0]]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@dataclass(frozen=True)
class Report:
    code: int
    checks: dict[str, tuple[bool, str]]
    text: str  # stdout and stderr together


def run_doctor(
    runner: FakeRunner, capsys: pytest.CaptureFixture[str], *args: str
) -> Report:
    code = load_doctor().main(list(args), runner=runner)
    captured = capsys.readouterr()
    checks: dict[str, tuple[bool, str]] = {}
    for line in captured.out.splitlines():
        match = LINE.fullmatch(line)
        assert match, f"unexpected output line: {line!r}"
        checks[match[2]] = (match[1] == "PASS", match[3])
    return Report(code, checks, captured.out + captured.err)


def test_all_checks_pass_with_fake_runner(capsys: pytest.CaptureFixture[str]) -> None:
    runner = FakeRunner(docker=completed(docker_info(mem_total=24 * GIB, ncpu=8)))

    report = run_doctor(runner, capsys)

    assert report.code == 0
    assert report.checks == {
        "uv": (True, f"uv --version exited 0; {REQUIRED_UV}"),
        "docker daemon": (True, f"docker info exited 0; {REQUIRED_DOCKER}"),
        "docker memory": (
            True,
            f"25,769,803,776 bytes (24.00 GiB); {REQUIRED_MEMORY}",
        ),
        "docker cpus": (True, f"8 CPUs; {REQUIRED_CPUS}"),
    }
    assert runner.calls == [
        ("uv", "--version"),
        ("docker", "info", "--format", "{{json .}}"),
    ]


def test_memory_boundary_is_inclusive(capsys: pytest.CaptureFixture[str]) -> None:
    exact = run_doctor(
        FakeRunner(docker=completed(docker_info(mem_total=17_179_869_184))), capsys
    )
    below = run_doctor(
        FakeRunner(docker=completed(docker_info(mem_total=17_179_869_183))), capsys
    )

    assert exact.code == 0
    assert exact.checks["docker memory"] == (
        True,
        f"17,179,869,184 bytes (16.00 GiB); {REQUIRED_MEMORY}",
    )
    assert below.code == 1
    assert below.checks["docker memory"] == (
        False,
        f"17,179,869,183 bytes (15.99 GiB); {REQUIRED_MEMORY}",
    )


def test_missing_docker_binary(capsys: pytest.CaptureFixture[str]) -> None:
    missing = FileNotFoundError(2, "No such file or directory", "docker")

    report = run_doctor(FakeRunner(docker=missing), capsys)

    assert report.code == 1
    assert report.checks["uv"][0]
    assert report.checks["docker daemon"] == (
        False,
        f"docker not found; {REQUIRED_DOCKER}",
    )
    assert report.checks["docker memory"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_CPUS}",
    )


def test_docker_daemon_down(capsys: pytest.CaptureFixture[str]) -> None:
    down = completed(
        '{"ServerErrors": ["Cannot connect to the Docker daemon"]}',
        returncode=1,
        stderr="Cannot connect to the Docker daemon",
    )

    report = run_doctor(FakeRunner(docker=down), capsys)

    assert report.code == 1
    assert report.checks["docker daemon"] == (
        False,
        f"docker info exited 1; {REQUIRED_DOCKER}",
    )
    assert report.checks["docker memory"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_CPUS}",
    )


def test_docker_info_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    timeout = subprocess.TimeoutExpired(
        ["docker", "info"], 10, output=MARKER, stderr=MARKER
    )

    report = run_doctor(FakeRunner(docker=timeout), capsys)

    assert report.code == 1
    assert report.checks["docker daemon"] == (
        False,
        f"docker info timed out after 10 s; {REQUIRED_DOCKER}",
    )
    assert report.checks["docker memory"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_CPUS}",
    )
    assert MARKER not in report.text


def test_docker_cannot_be_started(capsys: pytest.CaptureFixture[str]) -> None:
    denied = PermissionError(13, MARKER, "docker")

    report = run_doctor(FakeRunner(docker=denied), capsys)

    assert report.code == 1
    assert report.checks["docker daemon"] == (
        False,
        f"docker could not be started; {REQUIRED_DOCKER}",
    )
    assert report.checks["docker memory"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (
        False,
        f"unknown, docker info failed; {REQUIRED_CPUS}",
    )
    assert MARKER not in report.text


def test_memory_below_minimum(capsys: pytest.CaptureFixture[str]) -> None:
    # The value ADR-001 measured on the human's laptop on 2026-10-20.
    info = docker_info(mem_total=8_217_407_488, ncpu=14)

    report = run_doctor(FakeRunner(docker=completed(info)), capsys)

    assert report.code == 1
    assert report.checks["docker memory"] == (
        False,
        f"8,217,407,488 bytes (7.65 GiB); {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (True, f"14 CPUs; {REQUIRED_CPUS}")


def test_cpus_below_minimum(capsys: pytest.CaptureFixture[str]) -> None:
    report = run_doctor(FakeRunner(docker=completed(docker_info(ncpu=2))), capsys)

    assert report.code == 1
    assert report.checks["docker memory"][0]
    assert report.checks["docker cpus"] == (False, f"2 CPUs; {REQUIRED_CPUS}")


def test_missing_uv(capsys: pytest.CaptureFixture[str]) -> None:
    missing = FileNotFoundError(2, "No such file or directory", "uv")

    report = run_doctor(FakeRunner(docker=completed(docker_info()), uv=missing), capsys)

    assert report.code == 1
    assert report.checks["uv"] == (False, f"uv not found; {REQUIRED_UV}")
    assert report.checks["docker daemon"][0]
    assert report.checks["docker memory"][0]
    assert report.checks["docker cpus"][0]


def test_docker_info_without_memtotal(capsys: pytest.CaptureFixture[str]) -> None:
    info = json.dumps({"NCPU": 8})

    report = run_doctor(FakeRunner(docker=completed(info)), capsys)

    assert report.code == 1
    assert report.checks["docker daemon"][0]
    assert report.checks["docker memory"] == (
        False,
        f"MemTotal missing or not an integer; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"][0]


def test_docker_info_without_ncpu(capsys: pytest.CaptureFixture[str]) -> None:
    info = json.dumps({"MemTotal": 24 * GIB})

    report = run_doctor(FakeRunner(docker=completed(info)), capsys)

    assert report.code == 1
    assert report.checks["docker memory"][0]
    assert report.checks["docker cpus"] == (
        False,
        f"NCPU missing or not an integer; {REQUIRED_CPUS}",
    )


def test_docker_info_empty_output(capsys: pytest.CaptureFixture[str]) -> None:
    report = run_doctor(FakeRunner(docker=completed("")), capsys)

    assert report.code == 1
    assert report.checks["docker memory"] == (
        False,
        f"invalid output; {REQUIRED_MEMORY}",
    )
    assert report.checks["docker cpus"] == (False, f"invalid output; {REQUIRED_CPUS}")


def test_no_command_output_is_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    uv = completed(MARKER, stderr=MARKER)
    cases = {
        "valid JSON": completed(
            docker_info(Name=MARKER, ServerVersion=MARKER), stderr=MARKER
        ),
        "non-zero exit": completed(MARKER, returncode=3, stderr=MARKER),
        "invalid JSON": completed(f"{{{MARKER}", stderr=MARKER),
    }

    reports = {
        case: run_doctor(FakeRunner(docker=docker, uv=uv), capsys)
        for case, docker in cases.items()
    }

    for case, report in reports.items():
        assert MARKER not in report.text, case
    assert reports["valid JSON"].code == 0
    assert reports["non-zero exit"].checks["docker daemon"] == (
        False,
        f"docker info exited 3; {REQUIRED_DOCKER}",
    )
    assert reports["invalid JSON"].checks["docker memory"] == (
        False,
        f"invalid output; {REQUIRED_MEMORY}",
    )
    assert reports["invalid JSON"].checks["docker cpus"] == (
        False,
        f"invalid output; {REQUIRED_CPUS}",
    )


def test_guard_blocks_real_runner() -> None:
    doctor = load_doctor()

    with pytest.raises(pytest.fail.Exception, match=r"real process.*'docker'"):
        doctor.run_command(("docker", "info", "--format", "{{json .}}"))


def test_flags_override_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    info = docker_info(mem_total=8 * GIB, ncpu=2)

    defaults = run_doctor(FakeRunner(docker=completed(info)), capsys)
    lowered = run_doctor(
        FakeRunner(docker=completed(info)),
        capsys,
        "--min-memory-gib",
        "8",
        "--min-cpus",
        "2",
    )

    assert defaults.code == 1
    assert lowered.code == 0
    assert lowered.checks["docker memory"] == (
        True,
        "8,589,934,592 bytes (8.00 GiB); "
        "required: at least 8 GiB (8,589,934,592 bytes)",
    )
    assert lowered.checks["docker cpus"] == (
        True,
        "2 CPUs; required: at least 2 CPUs",
    )
