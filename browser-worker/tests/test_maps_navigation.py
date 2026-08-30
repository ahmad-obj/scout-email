from browser_worker.maps import SEARCH_INPUT_SELECTORS


def test_search_input_selectors_include_generic_text_input_fallback():
    assert SEARCH_INPUT_SELECTORS[-1] == 'input[type="text"]'
