import re

_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CALL = re.compile(r"discount_applies\(\s*10\b")


def extract_function(text: str) -> str:
    text = _THINK.sub("", text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"\s*(async\s+)?def\s+\w+\s*\(", line)),
        None,
    )
    if start is None:
        raise ValueError("no function in text")
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    source = "\n".join(lines[start:end]).rstrip()
    if not _CALL.search(source):
        raise ValueError("function does not call discount_applies(10, ...)")
    return source
