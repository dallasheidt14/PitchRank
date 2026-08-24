"""PostToolUse advisory for Edit with replace_all.

Reads the hook payload on stdin because shell transport corrupts the needle:
command substitution strips trailing newlines from new_string and Windows jq
emits CRLF for embedded ones. Stdin is decoded as UTF-8 explicitly because the
payload arrives as raw UTF-8 while a stock Windows Python would decode the
locale codepage. Reports how many occurrences of the replacement the edit
left, so each site gets verified instead of trusted. Advisory: anything
unresolvable stays silent.
"""

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        return 0
    rel, root = sys.argv[1], sys.argv[2]
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("replace_all") is not True:
        return 0
    new_string = tool_input.get("new_string")
    if not new_string or not isinstance(new_string, str):
        return 0
    try:
        text = (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    # read_text normalizes the file's line endings to \n; do the same to the needle.
    needle = new_string.replace("\r\n", "\n").replace("\r", "\n")
    count = text.count(needle)
    if count > 1:
        sys.stdout.buffer.write(
            (
                f"replace_all applied; the edit left {count} occurrences of the replacement "
                f"in {rel} - re-read the file and verify each site."
            ).encode("utf-8")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
