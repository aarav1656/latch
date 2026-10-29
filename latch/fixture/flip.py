import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("billing.py")

STRICT = "    return seats >= 10"
LOOSE = "    return seats > 10"


def main(argv):
    if len(argv) != 2 or argv[1] not in ("flip", "restore"):
        return 2

    text = SOURCE.read_text(encoding="utf-8")
    lines = text.split("\n")
    strict_hits = [i for i, line in enumerate(lines) if line == STRICT]
    loose_hits = [i for i, line in enumerate(lines) if line == LOOSE]
    if argv[1] == "restore" and len(strict_hits) == 1 and not loose_hits:
        print("RESTORED")
        return 0
    if argv[1] == "flip":
        expected, replacement, status = STRICT, LOOSE, "FLIPPED"
    else:
        expected, replacement, status = LOOSE, STRICT, "RESTORED"

    hits = [i for i, line in enumerate(lines) if line == expected]
    if len(hits) != 1:
        return 2

    lines[hits[0]] = replacement
    SOURCE.write_text("\n".join(lines), encoding="utf-8")
    print(status)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
