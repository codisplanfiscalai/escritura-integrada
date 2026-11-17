# Backend slowness: bounded PDF tables and account references

Synthetic-only verification on 2026-11-17. No deployment, real accounting data,
certificate, or production mutation.

## Reproduced causes and changes

* A single ReportLab LongTable repeatedly splits/copies its remaining tail on
  every page. Accounting reports also carry a potentially much larger field
  appendix. Build bounded 200-record tables, preserving every row, column,
  appendix field, total, order, and continuous page numbers. Headers repeat at
  chunk boundaries; exact pagination can change. Applied to accounting, fiscal
  and generic exports. No forced page breaks at chunk boundaries.
* Positive account IDs necessarily identify materialized company rows. Querying
  effective_accounts (a UNION with virtual shared-plan entries) scans irrelevant
  global definitions on each reference lookup. Use the equivalent indexed
  accounts/global-entry join, still scoped by company and preserving all
  coalesced attributes. Negative aliases and materialization unchanged.

## Evidence

Local single-run timings are indicative, not service-level guarantees:

| Synthetic workload | Before | After |
| --- | ---: | ---: |
| 2,000 accounting fixture rows, including all appendix fields | 29.716s | 11.977s |
| 1,000 positive reference lookups with 22,591 shared definitions | 1.226s | 0.0055s |

The PDF fixture is `tests/test_accounting_report_models.py:fixture` with
`kind='trial-balance', count=2000`. Time `accounting_pdf` with perf_counter.
Reference fixture: `scripts.benchmark_workspace.fixture_workspace()`; select
first positive accounts row and call resolve_account 1,000 times with its
company_id. Baseline renderer/account lookup from dev.49. Machine contention and
PDF metadata/pagination mean byte-for-byte output equality is not expected.

A separate 20,544-row synthetic trial balance completed in 49.462s after the
change; the baseline was interrupted after several minutes, so no exact speedup
is claimed for that sample. Large exports remain expensive.

Regression coverage checks all 401 record markers across chunk boundaries,
page numbering and totals; also exact positive-reference parity with the view
for local/shared materialized accounts, cross-company rejection, and absence of
the virtual view in the lookup query. Existing integration tests cover previews,
daily consolidation, idempotence and direct fiscal accounting.

## Limits

Read-only public health and static responses from the user instance also took
several seconds; TLS alone contributed seconds. No VPS resource, queue, database
lock or reverse-proxy logs were available. These changes address reproduced
application costs, not a proven explanation of every production stall. The
363-document live preview was not completed by this investigation. Production
acceptance, list/preview/print timings and load behavior still need verification.
