from datetime import date

from scripts.verify_private_ingestion import archive_day, eligible_files, verify

from .ingestion_builders import GA, ga_row, workbook


def test_reserved_files_never_opened(tmp_path, monkeypatch):
    source = tmp_path / "10-10-26" / "RUTAS" / "synthetic.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(workbook([("Acercamiento", [GA, ga_row()])]))
    reserved = tmp_path / "17-10-26" / "RUTAS" / "reserved.xlsx"
    reserved.parent.mkdir(parents=True)
    reserved.write_bytes(b"This deliberately cannot be opened as Excel")
    future = tmp_path / "24-10-26" / "Lo Blanco" / "RUTAS" / "reserved.xlsx"
    future.parent.mkdir(parents=True)
    future.write_bytes(b"Do not read")
    original_read = type(tmp_path).read_bytes

    def guarded_read(path):
        assert path not in {reserved, future}, "Reserved file was opened"
        return original_read(path)

    monkeypatch.setattr(type(tmp_path), "read_bytes", guarded_read)
    selected, counts = eligible_files(tmp_path)
    assert len(selected) == 1
    assert counts["reserved_originals_not_opened"] == 2
    result = verify(tmp_path)
    assert result["reserved_workbooks_opened"] == result["database_writes"] == 0
    assert result["counts"]["original_books_interpreted"] == 1
    assert result["originals_unchanged"]


def test_context_uses_folder_not_filename_and_skips_undated(tmp_path):
    filename = tmp_path / "2026-10-10" / "RUTAS" / "2026-10-25.xlsx"
    filename.parent.mkdir(parents=True)
    filename.write_bytes(b"synthetic")
    assert archive_day(filename, tmp_path) == date(2026, 10, 10)
    unknown = tmp_path / "unknown" / "RUTAS" / "2026-10-10.xlsx"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"synthetic")
    selected, counts = eligible_files(tmp_path)
    assert len(selected) == 1
    assert counts["files_without_verified_archive_date_skipped"] == 1
