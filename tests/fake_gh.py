"""Fake gh for tests/test_set_rulesets.py: logs every call and keeps rulesets.

Usage: fake_gh.py STATE_DIR api ENDPOINT [--method M] [--paginate] [--jq X] [--input -]

Each call is appended to STATE_DIR/calls.jsonl as {argv, method, endpoint, body}.
Rulesets live in STATE_DIR/rulesets.json as {id: ruleset}. Only the calls that
set-rulesets.sh --apply makes are supported: the exact listing, POST to create a
ruleset and PUT to update an existing one. Any other call exits 1, so an
unexpected call fails the script instead of passing silently. The file
STATE_DIR/fail-listing makes the listing fail.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

LIST_JQ = ".[] | [.id, .name] | @tsv"
REPO = r"repos/[^/?]+/[^/?]+"
LISTING = re.compile(rf"{REPO}/rulesets\?includes_parents=false")
CREATE = re.compile(rf"{REPO}/rulesets")
UPDATE = re.compile(rf"{REPO}/rulesets/(\d+)")

Call = dict[str, Any]
Rulesets = dict[str, dict[str, Any]]


def parse(args: list[str]) -> Call | None:
    """The api call in args, or None if this fake does not understand it."""
    if len(args) < 2 or args[0] != "api":
        return None
    call: Call = {
        "endpoint": args[1],
        "method": "GET",
        "paginate": False,
        "jq": None,
        "input": None,
    }
    rest = args[2:]
    while rest:
        flag = rest.pop(0)
        if flag == "--paginate":
            call["paginate"] = True
        elif flag in ("--method", "--jq", "--input") and rest:
            call[flag.removeprefix("--")] = rest.pop(0)
        else:
            return None
    return call


def load(state: Path) -> Rulesets:
    path = state / "rulesets.json"
    return json.loads(path.read_text()) if path.exists() else {}


def fail(message: str) -> int:
    print(f"fake gh: {message}", file=sys.stderr)
    return 1


def main() -> int:
    state = Path(sys.argv[1])
    args = sys.argv[2:]
    call = parse(args)
    body: Any = None
    if call is not None and call["input"] == "-":
        text = sys.stdin.read()
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text

    entry = {"argv": args, "method": None, "endpoint": None, "body": body}
    if call is not None:
        entry.update(method=call["method"], endpoint=call["endpoint"])
    with (state / "calls.jsonl").open("a") as log:
        log.write(json.dumps(entry) + "\n")
    if call is None:
        return fail(f"unsupported call: {args}")

    rulesets = load(state)
    method, endpoint = call["method"], call["endpoint"]
    is_listing = (
        method == "GET"
        and LISTING.fullmatch(endpoint) is not None
        and call["paginate"]
        and call["jq"] == LIST_JQ
        and call["input"] is None
    )
    is_write = (
        not call["paginate"]
        and call["jq"] is None
        and call["input"] == "-"
        and isinstance(body, dict)
    )
    update = UPDATE.fullmatch(endpoint)

    if is_listing:
        if (state / "fail-listing").exists():
            return fail("listing failed")
        for ruleset_id, ruleset in rulesets.items():
            print(f"{ruleset_id}\t{ruleset.get('name', '')}")
        return 0
    if method == "POST" and CREATE.fullmatch(endpoint) and is_write:
        ruleset_id = str(max(map(int, rulesets), default=0) + 1)
        rulesets[ruleset_id] = body
    elif method == "PUT" and update and update[1] in rulesets and is_write:
        ruleset_id = update[1]
        # Fields the body leaves out are kept, so bypass_actors must be sent.
        rulesets[ruleset_id] = {**rulesets[ruleset_id], **body}
    else:
        return fail(f"unsupported call: {args}")

    (state / "rulesets.json").write_text(json.dumps(rulesets))
    print(json.dumps({"id": int(ruleset_id), **rulesets[ruleset_id]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
