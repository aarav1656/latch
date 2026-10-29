import html


def _yn(flag: bool) -> str:
    return "yes" if bool(flag) else "no"


def render(state: dict) -> str:
    weak_green = bool(state.get("weak_green"))
    mutant_still_green = bool(state.get("mutant_still_green"))
    kill_failed = bool(state.get("kill_failed"))
    restored_passed = bool(state.get("restored_passed"))
    assertion = html.escape(str(state.get("assertion", "")))

    status = "Open" if (kill_failed and restored_passed) else "Shut"
    killing_assertion = _yn(kill_failed and restored_passed)
    reason = str(state.get("reason") or "")
    http_status = state.get("http_status")
    extra = ""
    if reason:
        extra += f"<p id=\"reason\">{html.escape(reason)}</p>\n"
    if status == "Shut" and http_status is not None:
        extra += f"<p id=\"http\">{html.escape(str(http_status))}</p>\n"

    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>Latch</title>\n"
        "<style>\n"
        "body { background: #111111; color: #f4f4f5; font-family: Georgia, ui-serif, serif; margin: 2rem; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<p id=\"latch\">{status}</p>\n"
        f"<p>Weak test green: {_yn(weak_green)}</p>\n"
        f"<p>Mutant still green: {_yn(mutant_still_green)}</p>\n"
        f"<p>Killing assertion: {killing_assertion}</p>\n"
        f"<pre>{assertion}</pre>\n"
        f"{extra}"
        "</body>\n"
        "</html>\n"
    )
