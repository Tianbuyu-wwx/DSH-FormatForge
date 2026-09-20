# Repository Instructions - DSH-FormatForge

Repository root: `D:\Deepseek-harness\DSH-FormatForge`

This is a separate Git repository nested inside the Deepseek-harness workspace.
Relative paths in this file are relative to this repository. The parent
`D:\Deepseek-harness\AGENTS.md` also applies.

These are policy rules. Use `README.md`, `CHANGELOG.md`, `pyproject.toml`, and
`packages/dsh-formatforge/skills/dsh-formatforge/SKILL.md` for procedures and
current behavior.

## Package and runtime

FormatForge converts supported local files into structured content for
DeepSeek Harness. The JavaScript plugin layer spawns the Python CLI as
`python -m formatforge`.

- Use the dedicated `.venv-fg` environment.
- At runtime, `FF_PYTHON` must point to
  `D:\Deepseek-harness\DSH-FormatForge\.venv-fg\Scripts\python.exe`.
- Do not assume that variable exists in persistent User or Machine scope. The
  parent `tools\start-web.ps1` supplies it to managed services when absent.
- The npm package is scoped as `@tianbuyu-wwx/dsh-formatforge`, while the host
  mounts `dsh-formatforge`. Keep the installed unscoped path as a directory
  junction to the scoped package and recreate it after an install prunes it.

## Code layout

- `parsers/`: format-specific parsers.
- `core/`: detection, pipeline, models, cache, and shared conversion logic.
- `formatforge/`: Python CLI entry points.
- `packages/dsh-formatforge/`: JavaScript plugin and host integration layer.
- `test/unit/`: Python unit and regression tests.

## Tests

Run the Python suite through the FormatForge venv. On this machine, enable the
Windows mkdir shim:

```powershell
$env:PYTHONPATH = 'D:\Deepseek-harness\tools\pytest-win-mkdir-shim'
$env:PYTEST_PLUGINS = 'pytest_win_mkdir_shim'
& '.\.venv-fg\Scripts\python.exe' -m pytest test/ -q --timeout=180
```

The temporary-directory ACL failure reproduces on Python 3.11 as well as 3.14.
It follows the creating process's sandbox token, not the Python version. Use
the parent workspace's `tools\fix-pytest-cache-acl.ps1` for recognized orphan
trees; it supports `-Roots`, `-DryRun`, and idempotent reruns.

## Contribution discipline

- Keep one fix per commit and use the repository's conventional subjects,
  including `fix(...)`, `test(...)`, and `docs(...)`.
- Add a focused regression test with every behavior fix.
- Keep commits local unless the user explicitly requests a push or pull
  request.
- Preserve the frozen v1 protocol and stdout JSON contract unless a planned
  protocol change explicitly updates their tests and documentation.

## Advertised formats must be honest

Do not advertise formats that the package cannot parse. Claims for `.doc`,
`.ppt`, and `.xlsb` were deliberately removed. OLE2 magic dispatch was removed
from `docx_parser.py`, `pptx_parser.py`, `xlsx_parser.py`, and
`email_parser.py`; do not restore those broad claims without real parser and
dependency support.

`test/unit/test_format_capabilities.py` checks advertised formats against
`DataFormat` and locks the removed claims. Update capability claims from the
authoritative registry, not a hand-maintained list.

## Cache safety

The content cache is JSON-only. Legacy `.pkl` entries are ignored and must
never be deserialized. No pickle migration is required. Do not reintroduce a
pickle read path for compatibility.

## Sandbox failures require outside verification

An in-sandbox corruption, permission, or missing-file report is not proof.
Re-run the check from a normal unsandboxed terminal. Never move aside, delete,
or recreate a data file until the fault is confirmed outside the sandbox and
the evidence has been reported. Contradictory output, such as an integrity
failure alongside `integrity ok`, is suspect and must not trigger repair.

## Upstream contribution

- `origin` is `Tianbuyu-wwx/DSH-FormatForge`.
- `fork` is `thebizguy/DSH-FormatForge`.
- Pull request #15 is open from `fix/atria-audit-2026-09` to upstream `main`.
- **Branch convention (this confuses people — read it):** local work happens on **`main`**, not on a
  local `fix/atria-audit-2026-09` branch. That name exists only as the *fork-side* PR branch. The two
  are the same line of history: the PR branch is an ancestor of local `main`, so publishing is a
  fast-forward — `git push fork main:fix/atria-audit-2026-09`. Do **not** create or switch to a local
  branch of that name; you would fork the history and have to reconcile it.

Do not push upstream `main`. Use the fork and follow the user's explicit PR
instructions.
