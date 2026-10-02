# Repository Instructions - DSH-FormatForge

Policy rules for `D:\Deepseek-harness\DSH-FormatForge`, a separate Git repo nested in the Deepseek-harness workspace. Relative paths are from this repo. The parent `D:\Deepseek-harness\AGENTS.md` also applies.

- Procedures and current behavior: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `packages/dsh-formatforge/skills/dsh-formatforge/SKILL.md`.

## Package and runtime
- FormatForge converts supported local files into structured content for DeepSeek Harness. The JavaScript plugin layer spawns the Python CLI as `python -m formatforge`.
- Use the dedicated `.venv-fg` environment.
- `FF_PYTHON` must point to `D:\Deepseek-harness\DSH-FormatForge\.venv-fg\Scripts\python.exe`. It is not set in User or Machine scope; the parent `tools\start-web.ps1` supplies it to managed services when absent.
- The npm package is `@tianbuyu-wwx/dsh-formatforge`; the host mounts unscoped `dsh-formatforge`. That unscoped path must be a directory junction to the scoped package. Recreate it after an install prunes it.

## Code layout
- `parsers/`: format-specific parsers.
- `core/`: detection, pipeline, models, cache, and shared conversion logic.
- `formatforge/`: Python CLI entry points.
- `packages/dsh-formatforge/`: JavaScript plugin and host integration layer.
- `test/unit/`: Python unit and regression tests.

## Tests
Run the Python suite through the FormatForge venv with the Windows mkdir shim:

```powershell
$env:PYTHONPATH = 'D:\Deepseek-harness\tools\pytest-win-mkdir-shim'
$env:PYTEST_PLUGINS = 'pytest_win_mkdir_shim'
& '.\.venv-fg\Scripts\python.exe' -m pytest test/ -q --timeout=180
```

- Temp-dir ACL failures follow the creating process's sandbox token, not the Python version (they reproduce on 3.11 too). For recognized orphan trees, use the parent's `tools\fix-pytest-cache-acl.ps1` (`-Roots`, `-DryRun`; safe to rerun).

## Contribution rules
- One fix per commit, with conventional subjects such as `fix(...)`, `test(...)`, `docs(...)`.
- Every behavior fix gets a focused regression test.
- Commits stay local unless the user asks for a push or pull request.
- Keep the frozen v1 protocol and stdout JSON contract. Change them only in a planned protocol change that also updates their tests and docs.

## Advertised formats must be honest
- Never advertise a format the package cannot parse. Claims for `.doc`, `.ppt`, and `.xlsb` were removed on purpose, as was OLE2 magic dispatch in `docx_parser.py`, `pptx_parser.py`, `xlsx_parser.py`, and `email_parser.py`. Restore them only with real parser and dependency support.
- `test/unit/test_format_capabilities.py` checks advertised formats against `DataFormat` and locks the removed claims. Derive capability claims from that registry, not a hand-maintained list.

## Cache safety
- The content cache is JSON-only. Legacy `.pkl` entries are ignored and must never be deserialized. Never add a pickle read path, even for compatibility.

## Sandbox failures require outside verification
- An in-sandbox corruption, permission, or missing-file report is not proof. Re-run unsandboxed, and never move aside, delete, or recreate a data file until the fault is confirmed outside the sandbox and the evidence is reported. Contradictory output (an integrity failure plus `integrity ok`) must not trigger repair.

## Upstream contribution
- `origin` is `Tianbuyu-wwx/DSH-FormatForge`; `fork` is `thebizguy/DSH-FormatForge`. Never push upstream `main`. Use the fork and follow the user's explicit PR instructions.
- Pull request #15 is open from fork branch `fix/atria-audit-2026-09` to upstream `main`.
- Work on local `main`. The PR branch exists only on the fork and is an ancestor of local `main`, so publishing is a fast-forward: `git push fork main:fix/atria-audit-2026-09`. Never create a local branch with that name; it would split the history.
