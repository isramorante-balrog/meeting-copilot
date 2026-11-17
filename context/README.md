# /context — your local knowledge base

Preferred: use the 📄 **Context & Playbook** panel in the HUD. It parses PDF/DOCX/TXT/MD files into
`01_role/`, `02_profile/`, `03_experience/`, `04_playbook/` and keeps `manifest.json` up to date — do not
edit those folders by hand. Everything below still applies to loose files you drop directly in this folder
(they are injected as `<notes>`).

Every `.md` / `.txt` file in this folder (recursively) is injected into the LLM prompt
on every answer, so talking points are grounded in *your* experience and voice.
Files are hot-reloaded when they change (no restart needed).

Suggested files (one topic per file keeps things scannable for the model):

| File | Contents |
|------|----------|
| `00_profile.md` | Who you are, role, certifications, how you like to phrase things |
| `10_project_<name>.md` | One file per flagship project: Situation / Action / Impact / Metrics |
| `20_architecture_<topic>.md` | Reference architectures, design principles, trade-offs you defend |
| `30_vendor_<name>.md` | Evaluation criteria, known gaps, questions you always ask vendors |
| `40_scenarios.md` | Canned answers to recurring questions (STAR format) |

Guidelines
- Lead with numbers (users, apps, forests, % reduction, timelines) — the model surfaces them.
- Mark anything confidential as `[confidential: say only at a high level]`; the prompt tells the model to respect it.
- Budget is `context.max_chars` in `config.json` (default 60,000 chars ≈ 15k tokens). Files load in
  alphabetical order and are truncated past the limit — number your files by priority.
- Delete the two `example_*.md` files once you have your own.
