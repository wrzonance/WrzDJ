"""CSV safety helpers shared across all CSV exports.

The stdlib ``csv`` module handles RFC 4180 quoting/escaping but does NOT defend
against spreadsheet *formula injection* (a.k.a. CSV injection) — that is an
application-layer concern, so it lives here as a single shared primitive rather
than being re-implemented per endpoint.
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_value(value: str | None) -> str:
    """Neutralize CSV/spreadsheet formula injection.

    Spreadsheet apps (Excel, Google Sheets, LibreOffice) interpret cells starting
    with ``=``, ``+``, ``-``, ``@``, tab, or CR as formulas, which can be exploited
    when an exported file is opened. Prefixing such a cell with a single quote
    forces it to render as literal text.
    """
    if not value:
        return ""
    if value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value
