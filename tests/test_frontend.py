"""Frontend regression: decorator chain guards (round-player duplication bug).

Bug: sputnik.js and tg.js both wrapped K.chat._messageHtml guarded only by
their own flag, so every autoWire() added another layer and every round
message rendered N players. Both must share the _spChain guard.
"""

import re


def _src(name):
    with open(f"static/js/k/{name}", encoding="utf-8") as f:
        return f.read()


class TestDecoratorChain:
    def test_shared_chain_guard(self):
        for name in ("sputnik.js", "tg.js"):
            src = _src(name)
            assert "_spChain" in src, name
            assert "includes(" in src, name

    def test_single_click_listener(self):
        src = _src("sputnik.js")
        assert "_spClickBound" in src

    def test_no_unconditional_wrap(self):
        for name, own in (("sputnik.js", "sputnik"), ("tg.js", "tg")):
            src = _src(name)
            # the ONLY assignment of the render fn must be behind the chain check
            assigns = [m.start() for m in re.finditer(r"K\.chat\._messageHtml = wrapped", src)]
            assert len(assigns) == 1, name
            guard = src.find(f"includes('{own}')")
            assert 0 < guard < assigns[0], name
