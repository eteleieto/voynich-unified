"""Template experiment: are transcribed 'uncertain spaces' (,) physically narrower than certain ones (.)?

Shows the full VUD discipline: fixed train/held-out split decided before looking, two independent
witnesses, machine-observation confidence filter, and (optionally) pre-registration + result recording.

    uv run python experiments/_example_gap_widths/run.py              # just compute
    uv run python experiments/_example_gap_widths/run.py --register --author my-agent
"""
import argparse
import glob
import os

import duckdb
from scipy.stats import mannwhitneyu

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
con = duckdb.connect(os.path.join(ROOT, "voynich.duckdb"), read_only=True)

# 1. split fixed in advance: odd binding position = train, even = held-out
pages = con.sql("select page_id, ivtff_order from codicology.pages").fetchall()
train = [p for p, o in pages if o % 2 == 1]
held = [p for p, o in pages if o % 2 == 0]


def gaps(witness, page_set, kind):
    return [r[0] for r in con.sql(
        """select b.gap_norm from observations.spatial_boundary_gaps b
           join observations.spatial_locus_alignment a using (locus_id, row_id)
           where b.witness_id = ? and b.boundary_kind = ? and a.confidence > 0.6
             and a.page_id in (select unnest(?::varchar[]))""", params=[witness, kind, page_set]).fetchall()]


def report(witness, page_set, label):
    sp, un = gaps(witness, page_set, "space"), gaps(witness, page_set, "uncertain_space")
    if len(un) < 20:
        return None
    u = mannwhitneyu(un, sp, alternative="less")
    med = lambda x: sorted(x)[len(x) // 2]  # noqa: E731
    print(f"{witness:8s} {label:9s} n(.)={len(sp):5d} n(,)={len(un):4d}  median gap/Hm  .={med(sp):.2f}  ,={med(un):.2f}  "
          f"MWU p={u.pvalue:.2e}")
    return u.pvalue


ap = argparse.ArgumentParser()
ap.add_argument("--register", action="store_true")
ap.add_argument("--author", default="example")
a = ap.parse_args()

release = sorted(glob.glob(os.path.join(ROOT, "releases", "VUD-*.json")))
print("VUD release:", os.path.basename(release[-1]) if release else "(none cut yet)")
if a.register:
    import sys
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from vud import contrib
    hid = contrib.add_hypothesis(
        author=a.author, type="segmentation", status="testing",
        title="Uncertain spaces are physically narrower than certain spaces",
        claim="Median ink gap at boundaries transcribed ',' is smaller than at '.' (gap in units of page glyph height).",
        falsification_test="Refuted if on held-out pages either zl3b or gc2a shows no one-sided MWU effect at p<0.01.",
        train_pages=train, held_out_pages=held,
        evidence=["observations.spatial_boundary_gaps", "observations.spatial_locus_alignment"])
results = {}
for w in ("zl3b", "gc2a"):
    for label, ps in (("train", train), ("held-out", held)):
        results[(w, label)] = report(w, ps, label)
if a.register:
    ok = all(results[(w, "held-out")] is not None and results[(w, "held-out")] < 0.01 for w in ("zl3b", "gc2a"))
    contrib.update_hypothesis_status(author=a.author, hypothesis_id=hid, status="supported" if ok else "refuted",
                                     result_summary=f"held-out p: zl3b={results[('zl3b','held-out')]}, gc2a={results[('gc2a','held-out')]}")
    print("recorded", hid)
