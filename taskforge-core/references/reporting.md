# Shared report format (end of every skill execution)

Quote engine JSON output; never re-derive state from memory. Report:

1. **Task** — id + title.
2. **What happened** — one line per: mode/decision taken and why; artifacts
   produced (kind + version, from the apply output); tasks generated (id,
   relation, title); signal emitted.
3. **State now** — the task's new `status` and `readiness` (from apply
   output), and readiness of any generated tasks.
4. **Next** — name the skill the task's readiness calls for (or "waiting on
   TASK-x / a human"), then **stop**. Do not begin that skill, and do not
   start generated tasks.

Keep it short — the event history holds the detail.
