from scout_email.crawl.extract import extract_page


def test_extract_page_reduces_boilerplate_and_keeps_conversion_signals():
    html = """
    <html>
      <head>
        <title>Acme Dental | Lahore</title>
        <meta name="description" content="Implants and cosmetic dentistry in Lahore">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="canonical" href="https://example.com/implants">
        <meta property="og:title" content="Dental Implants">
      </head>
      <body>
        <nav>Home Services About Contact</nav>
        <main>
          <h1>Dental implants in Lahore</h1>
          <p>Replace missing teeth with a fixed implant treatment plan.</p>
          <img src="/images/implant.webp" alt="Dental implant model" width="1200" height="800">
          <h2>Book a consultation</h2>
          <a href="/contact">Book appointment</a>
          <a href="https://instagram.com/acme">Instagram</a>
          <form action="/consultation" method="post">
            <input type="email" name="email">
            <button type="submit">Request consultation</button>
          </form>
        </main>
        <footer>Privacy Terms Copyright 2026</footer>
      </body>
    </html>
    """

    result = extract_page(html, "https://example.com/implants")

    assert result.title == "Acme Dental | Lahore"
    assert result.headings == ["Dental implants in Lahore", "Book a consultation"]
    assert "Replace missing teeth" in result.important_text
    assert "Privacy Terms" not in result.important_text
    assert "Home Services About Contact" not in result.important_text
    assert "Book appointment" in result.calls_to_action
    assert "Request consultation" in result.calls_to_action
    assert result.forms == [
        {
            "action": "https://example.com/consultation",
            "method": "post",
            "input_types": ["email"],
        }
    ]
    assert "https://example.com/contact" in result.links
    assert "https://instagram.com/acme" in result.links
    assert result.images == [
        {
            "src": "https://example.com/images/implant.webp",
            "alt": "Dental implant model",
            "width": 1200,
            "height": 800,
        }
    ]
    assert result.technical_signals["has_viewport"] is True
    assert result.technical_signals["meta_description"] == "Implants and cosmetic dentistry in Lahore"
    assert result.technical_signals["canonical"] == "https://example.com/implants"
    assert result.technical_signals["has_open_graph"] is True
