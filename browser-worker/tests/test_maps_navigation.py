from browser_worker.maps import _maps_search_url


def test_maps_search_url_encodes_query_as_path_segment():
    assert _maps_search_url("dentist Lahore") == "https://www.google.com/maps/search/dentist%20Lahore"
    assert _maps_search_url("dental clinic / Lahore") == "https://www.google.com/maps/search/dental%20clinic%20%2F%20Lahore"
