import pytest

from browser_worker.maps import _find_search_input


class FakeInput:
    def __init__(self, name: str, *, visible: bool = True, dom_type: str = "text"):
        self.name = name
        self.visible = visible
        self.dom_type = dom_type

    async def count(self):
        return 1

    async def is_visible(self):
        return self.visible

    async def evaluate(self, expression: str):
        assert "type" in expression
        return self.dom_type


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
    def __init__(self, known=None, inputs=None, typed_selector_inputs=None):
        self.known = known
        self.inputs = list(inputs or [])
        self.typed_selector_inputs = list(typed_selector_inputs or [])

    def locator(self, selector: str):
        if selector == "KNOWN" and self.known is not None:
            return FakeCollection([self.known])
        if selector == "input":
            return FakeCollection(self.inputs)
        if selector == 'input[type="text"], input[type="search"]':
            return FakeCollection(self.typed_selector_inputs)
        return FakeCollection([])


@pytest.mark.asyncio
async def test_known_maps_selector_wins():
    known = FakeInput("known")
    generic = FakeInput("generic")
    result = await _find_search_input(FakePage(known=known, inputs=[generic]), selectors=("KNOWN",))
    assert result is known


@pytest.mark.asyncio
async def test_default_text_input_without_type_attribute_is_safe_fallback():
    # This reproduces the live Maps DOM: outerHTML has no type attribute,
    # while the element's DOM `type` property is the browser default "text".
    only = FakeInput("anonymous-default-text", dom_type="text")
    page = FakePage(inputs=[only], typed_selector_inputs=[])
    result = await _find_search_input(page, selectors=("MISSING",))
    assert result is only


@pytest.mark.asyncio
async def test_non_text_inputs_are_ignored():
    result = await _find_search_input(
        FakePage(inputs=[FakeInput("hidden", dom_type="hidden")]),
        selectors=("MISSING",),
    )
    assert result is None


@pytest.mark.asyncio
async def test_multiple_visible_text_inputs_are_ambiguous():
    result = await _find_search_input(
        FakePage(inputs=[FakeInput("one"), FakeInput("two")]),
        selectors=("MISSING",),
    )
    assert result is None
