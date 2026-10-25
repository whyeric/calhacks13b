"""C4-A33: the system prompt carries all eight rules and no figures."""

import re

from app.agent import prompts


def test_A33_eight_rules_no_numbers():
    s = prompts.SYSTEM
    for i, rule in enumerate(prompts.RULES, start=1):
        assert f"{i}. {rule}" in s
    assert len(prompts.RULES) == 8
    for phrase in ("risk desk", "come from a tool result", "speculation", "checks failed", "Premiums are a cost",
                   "pending_approval", "real and what's estimated", "One or two sentences"):
        assert phrase in s
    assert "$" not in s and "%" not in s and "¢" not in s
    body = re.sub(r"(?m)^\d\. ", "", s)  # rule numbering is the only allowed digit
    assert not re.search(r"\d", body)
    assert not re.search(r"\b(profit|earn|gain)\b", s, re.IGNORECASE)
    assert "not instructions" in s  # G15
