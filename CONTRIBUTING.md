# Contributing to stockpile

Contributions are welcome. Since this is a public repo, anyone can
fork it and open a pull request — no special permissions needed.

## Requirements

- Python 3.12+. If you don't have it, let uv manage it:
  ```bash
  uv python install 3.12
  ```
- [uv](https://docs.astral.sh/uv/):
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

## Fork → PR workflow

1. **Fork the repo** on GitHub (top-right "Fork" button).

2. **Clone your fork** and create a branch:
   ```bash
   git clone https://github.com/<your-username>/stockpile.git
   cd stockpile
   uv sync
   git checkout -b my-feature
   ```

3. **Make your changes**, then push. Sign off your commits with `-s` —
   this adds the `Signed-off-by` line the DCO requires (see "Licensing &
   sign-off" below):
   ```bash
   git add <files>
   git commit -s -m "describe your change"
   git push origin my-feature
   ```

4. **Open a Pull Request** on GitHub. Set the base repository to
   `medloh/stockpile` and base branch to `main`.

5. The repo owner reviews, leaves comments if needed, and merges
   when ready.

## Licensing & sign-off

This project is free under [CC BY-NC 4.0](LICENSE) for non-commercial
use, and the maintainer also offers paid **commercial** licenses. For
that to work, every contribution needs clear provenance and licensing
terms.

**By submitting a contribution (e.g. a pull request), you agree that:**

1. **You have the right to submit it** — you wrote it, or it is
   compatibly licensed work you are permitted to contribute (this is
   what the Developer Certificate of Origin below certifies).
2. **You keep your copyright**, but you license your contribution to the
   project under CC BY-NC 4.0 **and** grant the maintainer a perpetual,
   worldwide, irrevocable, royalty-free right to use, modify, sublicense,
   and **relicense your contribution under other terms, including
   commercial/proprietary licenses.** This lets stockpile be offered
   commercially without having to track down every contributor.

Certify this by **signing off each commit** with `git commit -s`, which
appends a line like:

```
Signed-off-by: Jane Doe <jane@example.com>
```

Use your real name and a working email. PRs without a sign-off will be
asked to add one before they can be merged.

### Developer Certificate of Origin 1.1

Sign-off certifies the following (full text at
<https://developercertificate.org>):

```
By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Adding dependencies

To add a package to a specific sub-project:

```bash
uv add plotly --project cost-basis-charts
```

Then run `uv sync` to update the lockfile. Prefer adding to the
narrowest sub-project that needs it — don't add to the root
`pyproject.toml` unless it's truly shared.

## Guidelines

- Keep PRs focused on one change — easier to review and less likely
  to conflict.
- If your branch falls behind `main`, rebase before opening the PR:
  ```bash
  git remote add upstream https://github.com/medloh/stockpile.git
  git fetch upstream
  git rebase upstream/main
  ```
- PRs that touch `shared/` affect all sub-projects — call that out
  in your PR description so it gets extra scrutiny.
- Always run via `uv run` from the repo root, never `python` directly.
