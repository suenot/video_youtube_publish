from verify_result import parse_status

T = "Building a Market Making Algorithm"


def test_absent_when_title_missing():
    assert parse_status("some other content", T) == ("absent", "")


def test_failed_on_abandoned():
    txt = f"{T} | Processing abandoned Video is too long"
    status, note = parse_status(txt, T)
    assert status == "failed" and "too long" in note.lower()


def test_processing():
    assert parse_status(f"{T} | Checking...", T) == ("processing", "")


def test_present():
    assert parse_status(f"{T} | Private | 0 views", T) == ("present", "")
