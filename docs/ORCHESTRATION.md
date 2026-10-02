# Running many agents on VUD

This workspace is built so a lead agent (the *orchestrator*) can fan work out to many subagents that run
at the same time without stepping on each other:

* **Read-only views** (`voynich.duckdb`): any number of concurrent readers.
* **Append-only, file-locked writes**: `vud.contrib` (observations, hypotheses, reviews) and the task
  queue `vud task` (claims expire after 6 h).
* **Role definitions** in `.claude/agents/`: Claude Code picks these up automatically when a session is
  opened in this folder, so an orchestrator can spawn them by name.
* **Guard rails**: `.claude/settings.json` denies edits to `evidence/`, `data/`, `curation/` and the
  registry; the observation API rejects interpretive wording; the hypothesis API rejects train/held-out overlap.

| Role (subagent) | Use it for | Writes |
|---|---|---|
| `vud-analyst` | one quantitative experiment end-to-end | hypothesis + result, `experiments/<name>/` |
| `vud-palaeographer` | eyes on pixels; reviewing machine rows/alignments/objects | observations, reviews |
| `vud-transcriber` | adjudicating disputed readings against the image | `reading_check` observations |
| `vud-comparatist` | control distributions; Latin/vernacular/cipher/pseudo-text comparisons | experiments, hypotheses |
| `vud-historian` | provenance, codicology, literature, MS 408A papers — with citations | (mostly) reports |
| `vud-skeptic` | trying to break a claimed result before anyone believes it | verdict rows |

## Before you start

```bash
cd ~/Projects/voynich-unified
uv run vud build && uv run pytest -q          # everything green
uv run vud release 0.2.0                      # freeze the dataset version every agent will cite
```

Open Claude Code in `~/Projects/voynich-unified` (the agents and settings are project-scoped).

## The master prompt (paste into the orchestrator)

> You are the research director for the Voynich Unified Dataset in this folder. Read AGENTS.md and
> docs/ORCHESTRATION.md first. Run a research program in waves using the project subagents
> (vud-analyst, vud-palaeographer, vud-transcriber, vud-comparatist, vud-historian, vud-skeptic). Launch
> independent subagents in parallel, in the background, and give each a narrow, self-contained brief
> with: the question, the exact tables to use, the author name to use (e.g. `palaeo-03`), and the
> deliverable. Do not do the work yourself; coordinate, check, and synthesise.
>
> **Wave 0 — calibrate the machine layers (parallel):** 4 × vud-palaeographer, each taking 8 pages from
> `uv run vud task next --kind review_alignment`; 2 × vud-transcriber on `--kind disputed_loci` (5 pages
> each); 1 × vud-palaeographer on `--kind review_objects` (10 canvases). When they return, compute the
> acceptance rate per page type from `main.alignment_reviewed` and report where the spatial layer can be
> trusted.
>
> **Wave 1 — structure (parallel, one vud-analyst per question, each claims `experiment:<name>`):**
> (1) word-length and token-frequency distributions vs the full control panel; (2) positional constraints:
> line-initial, line-final, paragraph-initial glyph/token preferences, and whether they survive across
> witnesses; (3) robustness of the Currier A/B split with leave-one-quire-out validation;
> (4) physical word-gap distributions: are spaces bimodal, scribe-dependent, line-position-dependent?;
> (5) label vs paragraph vocabulary, and tokens near pigment regions (`observations.layout_relations`);
> (6) self-citation structure vs Timm's generator; (7) conditional entropy h1/h2/h3 per section and
> per witness, with alternatives and uncertain spaces varied. Each analyst must pre-register,
> use held-out pages, and run controls.
>
> **Wave 2 — audit:** for every hypothesis now marked `supported`, launch a vud-skeptic. Only results
> that survive the skeptic count.
>
> **Wave 3 — mechanisms (parallel):** from surviving Wave-1 findings, propose at most 5 generative
> hypotheses (e.g. verbose cipher, abbreviation system, table-and-grille, natural language with unusual
> orthography, meaningless generation). For each, one vud-analyst builds a falsifiable predictive test on
> held-out pages, and one vud-comparatist builds the matching control. Skeptic again.
>
> **Throughout:** one vud-historian answers any provenance/codicology question raised by others, with
> citations. Track everything in `uv run vud task board` and `hypotheses.hypotheses`.
>
> **Finish:** write `experiments/_synthesis/REPORT.md`: what is now established (with hypothesis ids,
> held-out numbers, controls), what was refuted, what the machine layers can and cannot be trusted for,
> and the next 10 experiments ranked by expected information gain. Cite the VUD release.

## Smaller prompts

* *Calibration only:* "Use 6 vud-palaeographer subagents in parallel to review the 48 worst spatial
  alignment pages from the task queue; then summarise acceptance rates by section from `main.alignment_reviewed`."
* *One question, done properly:* "Spawn a vud-analyst to test whether EVA `qo-` tokens prefer
  line-initial position more than chance, across zl3b, it2a and beva:GC2a_0, with held-out pages and the
  full control panel; then a vud-skeptic on its result."
* *History:* "Have a vud-historian list every documented owner of MS 408 with dates, citing the Marci letter
  canvases, the MS 408A provenance files and D'Imperio 1978 page numbers."
* *Disputed readings sprint:* "Run 5 vud-transcriber subagents on the disputed_loci queue for 3 pages each;
  report how often ZL3b vs IT2a is supported by the pixels."

## Practical notes

* Subagents start with no memory of your conversation — always put the question, tables and author name
  in the brief. They report back only what you ask for; ask for numbers and ids.
* Prefer many narrow agents over a few broad ones; ~5–8 in parallel is a good wave size.
* After a wave that wrote observations/hypotheses: `uv run vud build contrib && uv run vud build db`.
* Cut a new release (`uv run vud release 0.2.1`) before a wave whose results you want to cite.
