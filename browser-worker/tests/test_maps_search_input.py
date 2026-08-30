import pytest

from browser_worker.maps import _find_search_input


class FakeInput:
    def __init__(self, name: str, *, visible: bool = True):
        self.name = name
        self.visible = visible

    async def count(self):
        return 1

    async def is_visible(self):
        return self.visible


class FakeCollection:
    def __init__(self, items):
        self.items = list(items)
        self.first = self.items[0] if self.items else FakeEmpty()

    async def count(self):
        return len(self.items)

    def nth(self, index: int):
        return self.items[index]


class FakeEmpty:
    first = None

    async def count(self):
        return 0

    async def is_visible(self):
        return False


class FakePage:
    def __init__(self, known=None, generic=None):
        self.known = known
        self.generic = list(generic or [])

    def locator(self, selector: str):
        if selector == "KNOWN" and self.known is not None:
            return FakeCollection([self.known])
        if selector == 'input[type="text"], input[type="search"]':
            return FakeCollection(self.generic)
        return FakeCollection([])


@pytest.mark.asyncio
async def test_known_maps_selector_wins():
    known = FakeInput("known")
    generic = FakeInput("generic")
    result = await _find_search_input(FakePage(known=known, generic=[generic]), selectors=("KNOWN",))
    assert result is known


@pytest.mark.asyncio
async def test_one_visible_bare_text_input_is_safe_fallback():
    only = FakeInput("bare")
    result = await _find_search_input(FakePage(generic=[only]), selectors=("MISSING",))
    assert result is only


@pytest.mark.asyncio
async def test_multiple_visible_bare_inputs_are_ambiguous():
    result = await _find_search_input(
        FakePage(generic=[FakeInput("one"), FakeInput("two")]),
        selectors=("MISSING",),
    )
    assert result is None
