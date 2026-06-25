# README + top-level link cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix repo-relative and bare-`.md` links in README + CONTRIBUTING so they work on PyPI and route to the rendered docs site, plus a one-shot link audit of the built `docs/` site to catch any other stale URLs.

**Architecture:** Three single-line edits across two top-level files, then run an external-link checker against the built site, triage findings, fix in place. Ship as one PR. No CI changes, no docs content edits.

**Tech Stack:** mkdocs (already in use), `lychee` (Rust link checker, available via `uvx`) — with `linkchecker` fallback if `lychee` isn't reachable.

**Spec:** [`planning/specs/2026-06-08-readme-link-cleanup-design.md`](../specs/2026-06-08-readme-link-cleanup-design.md)

---

## Working assumptions

- Working on a branch off `main` (NOT directly on `main`). If unsure, create one: `git checkout -b docs/readme-link-cleanup`.
- `uv`, `uvx`, `just`, `git` available. The `lychee` Rust binary will be fetched on demand via `uvx --from lychee-link-checker`.
- Current working directory throughout: `/Users/kevinsmith/src/pypi/httpware`.
- The migration to GitHub Pages (PR #38) is already live — `https://httpware.modern-python.org/middleware/` returns 200.

## File map

**Modify:**
- `README.md` — two single-line edits (lines 91 and 142).
- `CONTRIBUTING.md` — one single-line edit (line 6).
- Possibly `docs/**/*.md` — only if the link audit surfaces broken external URLs. None expected based on the 2026-06-07 deep audit.

**No deletions, no new files.**

---

## Task 1: Branch and capture baseline

**Files:** none (git operations only)

- [ ] **Step 1: Confirm on main with a clean tree**

```bash
git status
git rev-parse --abbrev-ref HEAD
```
Expected: clean tree; branch is `main`.

- [ ] **Step 2: Create the branch**

```bash
git checkout -b docs/readme-link-cleanup
git log -1 --format="%H"
```
Capture the SHA for later — this is your base.

---

## Task 2: Fix README.md:91 (Middleware guide link)

**Files:**
- Modify: `README.md` line 91

- [ ] **Step 1: Verify the current state**

Run:
```bash
sed -n '91p' README.md
```
Expected output (one line):
```
Need a custom middleware (auth, tracing, request-ID propagation, etc.)? See the [Middleware guide](docs/middleware.md).
```

If the output differs, STOP and report — line numbers may have drifted; locate by string match instead.

- [ ] **Step 2: Edit the line**

Change `(docs/middleware.md)` to `(https://httpware.modern-python.org/middleware/)`:

The new line 91 must read exactly:
```
Need a custom middleware (auth, tracing, request-ID propagation, etc.)? See the [Middleware guide](https://httpware.modern-python.org/middleware/).
```

- [ ] **Step 3: Verify the URL serves**

```bash
curl -sI -o /dev/null -w "%{http_code}\n" https://httpware.modern-python.org/middleware/
```
Expected: `200`.

- [ ] **Step 4: Confirm no other `docs/*.md` repo-relative links snuck into README**

```bash
grep -nE '\]\(docs/[^)]*\.md[^)]*\)' README.md
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): link Middleware guide at rendered docs URL"
```

---

## Task 3: Fix README.md:142 (License link)

**Files:**
- Modify: `README.md` line 142

- [ ] **Step 1: Verify the current state**

```bash
sed -n '142p' README.md
```
Expected output:
```
## 📝 [License](./LICENSE)
```

- [ ] **Step 2: Edit the line**

Change `(./LICENSE)` to the absolute GitHub blob URL so PyPI also resolves it.

The new line 142 must read exactly:
```
## 📝 [License](https://github.com/modern-python/httpware/blob/main/LICENSE)
```

- [ ] **Step 3: Verify the URL serves**

```bash
curl -sI -o /dev/null -w "%{http_code}\n" -L https://github.com/modern-python/httpware/blob/main/LICENSE
```
Expected: `200`.

- [ ] **Step 4: Confirm no other relative-path links in README**

```bash
grep -nE '\]\(\./[^)]+\)' README.md
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): use absolute GitHub URL for LICENSE link"
```

---

## Task 4: Fix CONTRIBUTING.md:6 (Source pointer)

**Files:**
- Modify: `CONTRIBUTING.md` line 6

- [ ] **Step 1: Verify the current state**

```bash
sed -n '6p' CONTRIBUTING.md
```
Expected output:
```
Source: [`docs/dev/contributing.md`](docs/dev/contributing.md).
```

- [ ] **Step 2: Edit the line**

Change the link target to an absolute GitHub URL (keep the inline-code display text):

The new line 6 must read exactly:
```
Source: [`docs/dev/contributing.md`](https://github.com/modern-python/httpware/blob/main/docs/dev/contributing.md).
```

- [ ] **Step 3: Verify the URL serves**

```bash
curl -sI -o /dev/null -w "%{http_code}\n" -L https://github.com/modern-python/httpware/blob/main/docs/dev/contributing.md
```
Expected: `200`.

- [ ] **Step 4: Confirm no remaining repo-relative `.md` links in CONTRIBUTING.md**

```bash
grep -nE '\]\([^)h][^)]*\.md[^)]*\)' CONTRIBUTING.md
```
Expected: no output. (The `[^)h]` after `(` rejects links starting with `(h` — i.e., `(https://...)` is kept, `(./foo.md)` is flagged.)

- [ ] **Step 5: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): use absolute GitHub URL for source pointer"
```

---

## Task 5: Build the docs site for the link audit

**Files:** none (produces `/tmp/httpware-site-for-audit/`)

- [ ] **Step 1: Build the site**

```bash
rm -rf /tmp/httpware-site-for-audit
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-site-for-audit
```
Expected: exit 0, `INFO    -  Documentation built in <N>s`. No new warnings vs the post-PR-38 baseline. (You will see the mkdocs-material vendor banner about MkDocs 2.0 — that's not a warning, ignore.)

- [ ] **Step 2: Confirm the site contains the new README link targets**

```bash
test -f /tmp/httpware-site-for-audit/middleware/index.html && echo "middleware page present"
```
Expected: `middleware page present`.

---

## Task 6: Run the external-link audit

**Files:** none (produces stdout + saved report)

The goal here is to catch broken external URLs in the built site. Internal mkdocs links are already validated by `--strict`. Try `lychee` first; if it isn't available via `uvx`, fall back to `linkchecker`.

- [ ] **Step 1: Try `lychee` via uvx**

```bash
uvx --from lychee-link-checker lychee --version 2>&1 | head -1
```

If exit 0 and you see a version: proceed with `lychee` in Step 2A. Otherwise: skip to Step 2B.

- [ ] **Step 2A: Run `lychee` against the built site (preferred)**

```bash
uvx --from lychee-link-checker lychee \
  --no-progress \
  --max-concurrency 8 \
  --timeout 10 \
  --accept '200..=299,403,429' \
  --exclude 'localhost|127\.0\.0\.1|example\.(com|test|org)|api\.example\.com|myapp\.' \
  /tmp/httpware-site-for-audit \
  > /tmp/httpware-lychee-report.txt 2>&1
echo "lychee exit: $?"
```

The `--accept` list:
- `200..=299` — normal success.
- `403` — many sites (Cloudflare, GitHub anon-rate-limit) reject HEAD bot probes with 403; treat as OK.
- `429` — transient rate limiting; treat as OK (link itself is fine).

The `--exclude` list filters out documentation placeholder hostnames (`example.com`, `myapp.*`) that appear in code samples — those aren't real links.

Then go to Step 3.

- [ ] **Step 2B: Fallback to `linkchecker` if `lychee` not available**

```bash
uvx --from linkchecker linkchecker --version 2>&1 | head -1
```

If `linkchecker` is also unavailable, the audit can't run — skip directly to Task 8 (the three link edits will be the entirety of the PR; note in the PR body that the external-link audit couldn't be performed and why).

If `linkchecker` runs:

```bash
uvx --from linkchecker linkchecker \
  --check-extern \
  --no-warnings \
  --ignore-url '(localhost|127\.0\.0\.1|example\.(com|test|org)|api\.example\.com|myapp\.)' \
  --recursion-level 2 \
  --output text \
  /tmp/httpware-site-for-audit/index.html \
  > /tmp/httpware-linkchecker-report.txt 2>&1 || true
```

`|| true` is intentional — `linkchecker` exits non-zero on the first broken URL; the report is what matters.

- [ ] **Step 3: Triage the report**

Read the report (`cat /tmp/httpware-lychee-report.txt` or `/tmp/httpware-linkchecker-report.txt`). Categorize each non-success line:

- **REAL broken** (404, DNS NXDOMAIN on a domain that isn't a placeholder, permanent redirect to nowhere): record file + URL.
- **FALSE POSITIVE** (transient timeout, 403/429 not auto-accepted, link to a private/login-required URL): skip.
- **PLACEHOLDER** (example.com / api.example.com / similar in code samples — should have been excluded; tighten the exclude list if any leaked through): skip.

Write a short triage note in the commit message of Task 7 if any links need fixing.

If the report is clean (only excluded URLs and 2xx/3xx/403/429): skip Task 7 entirely, jump to Task 8.

---

## Task 7: Fix surfaced broken links (only if Task 6 found any)

**Files:** `docs/**/*.md` (depending on what surfaced)

- [ ] **Step 1: For each REAL broken link found in triage**

Find the source markdown file containing it:
```bash
grep -rn "<broken-url>" docs/ planning/
```
(Search `planning/` too in case a planning file embeds the URL via copy/paste, though planning is not in the published site.)

Edit each occurrence. Possible fixes:
- The page has moved → update URL.
- The page is gone → remove the link or substitute with the next-best authoritative source.
- Domain itself is dead → remove the link.

- [ ] **Step 2: Rebuild and re-audit**

```bash
rm -rf /tmp/httpware-site-for-audit
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-site-for-audit
# repeat the lychee/linkchecker invocation from Task 6
```

Expected: clean report.

- [ ] **Step 3: Commit (if files were changed)**

```bash
git add docs/
git commit -m "docs(links): fix broken external URLs surfaced by link audit

Audit summary:
- <one-line description per fix, e.g., 'foo.example moved to bar.example/new-path'>
"
```

---

## Task 8: Final mkdocs strict build sanity check

**Files:** none

- [ ] **Step 1: Final build**

```bash
rm -rf /tmp/httpware-site-final
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-site-final
```
Expected: exit 0, no warnings.

- [ ] **Step 2: Confirm the three new link targets render correctly in README (rendered preview)**

The README isn't built by mkdocs (it's GitHub/PyPI), so this is a one-time visual check. Use whichever you have:
- VS Code's built-in Markdown preview, OR
- `gh repo view --web` after pushing (Step 9), OR
- `grip README.md` if `grip` is installed.

For each of the three edits, click the link and confirm it loads the right target.

If you can't render-preview, this is a no-op step.

---

## Task 9: Push the branch and open the PR

**Files:** none

- [ ] **Step 1: Push**

```bash
git push -u origin HEAD
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "docs: fix repo-relative links in README + CONTRIBUTING, audit external links" --body "$(cat <<'EOF'
## Summary

- `README.md:91` — Middleware guide link now points at `https://httpware.modern-python.org/middleware/` (was the repo-relative `docs/middleware.md` which breaks on PyPI).
- `README.md:142` — License link is now an absolute GitHub URL (was `./LICENSE`, also broken on PyPI).
- `CONTRIBUTING.md:6` — Source-pointer link is now an absolute GitHub URL (was a repo-relative `.md` link).
- Ran a one-shot `lychee` audit against the built docs site. <Fill in: "No findings." OR "Fixed N broken URLs — see commit history.">

Spec: `planning/specs/2026-06-08-readme-link-cleanup-design.md`

## Not changed

- Intra-`docs/*.md` links (`[Errors reference](errors.md)` style) — these are the standard mkdocs convention; mkdocs rewrites them to clean URLs at build. Changing them would break `mkdocs serve`.
- `CLAUDE.md` planning-file links — internal AI-guidance only, not user-facing.
- `docs/index.md:174` Engineering Notes — already an absolute GitHub URL by design (planning/engineering.md isn't in the published site).

## Test plan

- [x] `mkdocs build --strict` passes (no docs content changed).
- [x] `curl -sI` returns 200 on each of the three new link targets.
- [x] No remaining `(docs/*.md)` or `(./*)` repo-relative links in README.md.
- [x] No remaining repo-relative `.md` links in CONTRIBUTING.md.
- [x] `lychee` (or fallback) audit produced a clean report (or all surfaced links fixed).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Edit the `<Fill in: …>` placeholder in the PR body before submitting (or after via `gh pr edit`).

- [ ] **Step 3: Sanity-check the PR diff**

```bash
gh pr diff --name-only
```
Expected files (no link-audit findings):
- `CONTRIBUTING.md`
- `README.md`
- `planning/plans/2026-06-08-readme-link-cleanup-plan.md` (this plan, if it's on the branch)
- `planning/specs/2026-06-08-readme-link-cleanup-design.md` (the spec, if it's on the branch)

(Plus any `docs/` files from Task 7 if the audit surfaced findings.)

If files outside this list show up, STOP and investigate before proceeding.

---

## Post-PR

- Wait for review and merge.
- After merge, `gh-pages` is unaffected (no `docs/` content changed in the README-only path), so no docs redeploy is triggered. If Task 7 modified `docs/`, the `Deploy Docs` workflow re-runs on `main` push.
