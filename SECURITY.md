# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/hashirventhodi/taskforge-skills/security/advisories/new)
— the **Security** tab → *Report a vulnerability*. Do not open a public
issue for a security problem.

Please include reproduction steps, the affected version or commit, and what
an attacker gains. Expect an initial response within a week; this is a
volunteer-maintained project, not a staffed security team.

## What you are installing

**Skills execute with your agent's full permissions.** That is true of every
skill in the ecosystem, not just this one. A skill is instructions your
coding agent will follow, plus — here — a Python engine it will run. Read
the skills before installing them, and prefer pinning to a reviewed commit
over tracking `main` in environments that matter.

This project is deliberately dependency-free at runtime: the engine is
stdlib-only Python, so installing it pulls in no third-party packages and
there is no supply chain beneath it. The `skills` CLI used to install it is
a separate project with its own dependencies.

## The trust boundary

Worth understanding before you deploy this anywhere sensitive:

- **The engine writes only under the task store** (`.tasks/`, or
  `TASKFORGE_DIR`). It does not touch your source tree.
- **Skills invoke the engine; the engine validates every result** against
  per-actor capabilities before applying it. A skill cannot write an
  artifact kind it lacks capability for.
- **Task descriptions are untrusted input.** Intake pulls text from GitHub
  issues, Jira tickets and files, and that text reaches an agent's context.
  Treat imported task content as you would any untrusted input to an LLM: a
  hostile issue body can attempt prompt injection. The engine constrains
  what the *resulting* state transitions may be; it cannot constrain what a
  model does with adversarial text in its context.
- **Reviewer isolation is enforced by recording, not by trust.** Run
  registers the exact reviewer prompt before spawning the reviewer, and
  `tasks.py audit-review` verifies it contained the acceptance criteria and
  none of the implementation summary. Unrecorded reviews are flagged.

## Scope

In scope: engine flaws that corrupt or bypass task state, capability
enforcement bypass, reviewer-isolation bypass that lets a self-review be
recorded as independent, path traversal out of the task store.

Out of scope: an agent making a poor engineering judgment, prompt injection
via task content (documented above and inherent to the design), and
vulnerabilities in the `skills` CLI or in your agent — report those
upstream.
