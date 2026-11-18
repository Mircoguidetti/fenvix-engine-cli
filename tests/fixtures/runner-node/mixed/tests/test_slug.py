from pkg import slug


def test_slug():
    assert slug("Hello World") == "hello-world"


def test_slug_empty():
    assert slug("") == ""
