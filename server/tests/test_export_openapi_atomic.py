import os
import stat

import pytest

from scripts import export_openapi


def test_export_keeps_previous_file_when_temp_write_fails(tmp_path, monkeypatch):
    output = tmp_path / "openapi.json"
    output.write_text("previous contract", encoding="utf-8")
    monkeypatch.setattr(export_openapi, "SERVER_ROOT", tmp_path)
    monkeypatch.setattr("app.main.app.openapi", lambda: {"openapi": "3.1.0"})

    fdopen = os.fdopen

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self.stream.close()

        def write(self, contents):
            self.stream.write(contents[:1])
            raise OSError("disk full")

        def fileno(self):
            return self.stream.fileno()

    monkeypatch.setattr(
        os,
        "fdopen",
        lambda *args, **kwargs: FailingWriter(fdopen(*args, **kwargs)),
    )

    with pytest.raises(OSError, match="disk full"):
        export_openapi.export()

    assert output.read_text(encoding="utf-8") == "previous contract"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("existing_mode", [None, 0o640])
def test_export_preserves_or_sets_public_artifact_mode(tmp_path, existing_mode):
    output = tmp_path / "openapi.json"
    if existing_mode is not None:
        output.write_text("previous contract", encoding="utf-8")
        output.chmod(existing_mode)

    export_openapi._write_atomically(output, "new contract")

    expected_mode = existing_mode if existing_mode is not None else 0o644
    assert stat.S_IMODE(output.stat().st_mode) == expected_mode
    assert output.read_text(encoding="utf-8") == "new contract"
