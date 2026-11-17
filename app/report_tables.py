"""Bound ReportLab table splitting work without omitting or reordering rows."""

def table_chunks(rows, size=200):
    """Repeat the header on bounded tables; keep an even stripe phase by default.

    LongTable splits copy the unconsumed tail. A single tens-of-thousands-row
    table (especially the audit appendix) otherwise repeatedly processes that
    tail on every page. No page break is forced at a chunk boundary.
    """
    if size < 1:
        raise ValueError("size must be positive")
    if not rows:
        return
    header = rows[0]
    if len(rows) == 1:
        yield [header]
    for start in range(1, len(rows), size):
        yield [header, *rows[start:start + size]]
