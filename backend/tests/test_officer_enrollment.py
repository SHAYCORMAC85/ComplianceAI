from backend import officers


def test_password_retry_keeps_officer_id(monkeypatch, tmp_path):
    monkeypatch.setattr(officers, "DATA_DIR", tmp_path)
    names = iter(["demo-officer"])
    entries = iter(["short", "first-test-password", "mismatched-entry",
                    "second-test-password", "second-test-password"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(names))
    monkeypatch.setattr(officers.getpass, "getpass", lambda prompt: next(entries))

    officers.enroll_interactively()
    assert officers.sign_in("demo-officer", "second-test-password")["officer_id"] == "demo-officer"
