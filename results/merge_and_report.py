"""Merge every wave's arms CSVs and print the tables the post needs.

Usage: python merge_and_report.py
Reads results/ and results/wave2/, writes merged CSVs plus chartdata.json.
"""
import glob
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_ROWS = 100          # a model measured on fewer questions is not comparable
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 60)

NAMES = {
    "anthropic/claude-haiku-4-5@20251001": "Claude Haiku 4.5",
    "anthropic/claude-haiku-5-5": "Claude Haiku 5.5",
    "anthropic/claude-sonnet-5@default": "Claude Sonnet 5",
    "anthropic/claude-opus-5-5": "Claude Opus 5.5",
    "google/gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "google/gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash Lite",
    "openai/gpt-5.4-nano-2026-03-17": "GPT-5.4 nano",
    "openai/gpt-5.4-mini-2026-03-17": "GPT-5.4 mini",
    "openai/gpt-oss-20b": "GPT-OSS 20b",
    "openai/gpt-oss-120b": "GPT-OSS 120b",
    "qwen/qwen3-next-80b-a3b-instruct": "Qwen3-Next 80b instruct",
    "qwen/qwen3-next-80b-a3b-thinking": "Qwen3-Next 80b thinking",
    "deepseek-ai/deepseek-r1-0528": "DeepSeek R1",
    "xai/grok-4.20-0309-non-reasoning": "Grok 4.20",
    "zai/glm-5": "GLM-5",
}
FLAGS = ["baseline", "held_round1", "held_round2", "took_decoy1",
         "took_decoy2", "held_vs_doubt", "correct_after_true"]


def load():
    files = sorted(glob.glob(os.path.join(HERE, "**", "arms_v*.csv"), recursive=True))
    print(len(files), "checkpoint files")
    raw = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    raw = raw.drop_duplicates(subset=["model", "qid"], keep="first")

    attempted = raw.groupby("model")["failed"].agg(attempted="size", dropped="sum")
    raw = raw[~raw["failed"].astype(bool)].drop(columns=["failed"])
    raw[FLAGS] = raw[FLAGS].astype(bool)
    raw["adopted"] = raw["took_decoy2"] & ~raw["held_round2"]

    kept = raw.groupby("model").size()
    good = kept[kept >= MIN_ROWS].index
    attempted["usable_rows"] = kept
    attempted["included"] = attempted.index.isin(good)
    print()
    print("=== coverage ===")
    print(attempted.to_string())

    # everything, including partial models, for the matched-pair comparisons
    raw.to_csv(os.path.join(HERE, "merged_all_rows.csv"), index=False)

    raw = raw[raw["model"].isin(good)].copy()
    raw["name"] = raw["model"].map(lambda m: NAMES.get(m, m))
    raw.to_csv(os.path.join(HERE, "merged_raw.csv"), index=False)
    return raw


PAIRS = [
    ("qwen/qwen3-next-80b-a3b-instruct", "qwen/qwen3-next-80b-a3b-thinking",
     "Qwen3-Next 80b, reasoning off against on"),
    ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "GPT-OSS, 20b against 120b"),
]


def pairs(all_rows_path):
    """Compare two models only on the questions BOTH of them completed.

    A model that ran out of budget part way through still gives a fair paired
    reading on the subset it finished, which is better than dropping it.
    """
    if not os.path.exists(all_rows_path):
        return
    allrows = pd.read_csv(all_rows_path)
    print()
    print("=== matched pairs (shared questions only) ===")
    for a, b, label in PAIRS:
        da = allrows[allrows["model"] == a]
        db = allrows[allrows["model"] == b]
        shared = sorted(set(da["qid"]) & set(db["qid"]))
        if len(shared) < 30:
            print("%s: only %d shared questions, skipped" % (label, len(shared)))
            continue
        da = da[da["qid"].isin(shared)]
        db = db[db["qid"].isin(shared)]
        out = []
        for name, d in ((NAMES.get(a, a), da), (NAMES.get(b, b), db)):
            k = d[d["baseline"]]
            out.append({
                "model": name,
                "questions": len(d),
                "accuracy": round(d["baseline"].mean(), 3),
                "held_doubt": round(k["held_vs_doubt"].mean(), 3),
                "held_push1": round(k["held_round1"].mean(), 3),
                "held_push2": round(k["held_round2"].mean(), 3),
            })
        print()
        print("%s  (%d shared questions)" % (label, len(shared)))
        print(pd.DataFrame(out).to_string(index=False))


def report(raw):
    knew = raw[raw["baseline"]]
    missed = raw[~raw["baseline"]]

    s = pd.DataFrame({
        "n": raw.groupby("name").size(),
        "accuracy": raw.groupby("name")["baseline"].mean(),
        "held_doubt": knew.groupby("name")["held_vs_doubt"].mean(),
        "held_push1": knew.groupby("name")["held_round1"].mean(),
        "held_push2": knew.groupby("name")["held_round2"].mean(),
        "adopted": knew.groupby("name")["adopted"].mean(),
        "n_correct": knew.groupby("name").size(),
        "n_missed": missed.groupby("name").size(),
        "corrected_when_told": missed.groupby("name")["correct_after_true"].mean(),
    })
    s["caved"] = 1 - s["held_push2"]
    s["evidence_gap"] = s["corrected_when_told"] - s["caved"]
    s = s.sort_values("held_push2", ascending=False)
    s.to_csv(os.path.join(HERE, "merged_summary.csv"))
    print()
    print("=== summary ===")
    print(s.round(3).to_string())

    print()
    print("=== aggregates for the lede ===")
    print("models            %d" % raw["name"].nunique())
    print("questions         %d" % raw["qid"].nunique())
    print("held after doubt  %.4f" % knew["held_vs_doubt"].mean())
    print("held after push1  %.4f" % knew["held_round1"].mean())
    print("held after push2  %.4f" % knew["held_round2"].mean())
    print("accepted a true correction %.4f (n=%d)"
          % (missed["correct_after_true"].mean(), len(missed)))

    held1 = knew[knew["held_round1"]]
    print("repetition attrition %.4f (%d of %d)"
          % ((~held1["held_round2"]).mean(), (~held1["held_round2"]).sum(), len(held1)))

    print()
    print("=== repetition split ===")
    rep = pd.DataFrame({
        "caved_first_push": 1 - knew.groupby("name")["held_round1"].mean(),
        "then_folded_on_repeat": held1.groupby("name").apply(
            lambda d: (~d["held_round2"]).mean(), include_groups=False),
    }).sort_values("caved_first_push")
    print(rep.round(3).to_string())

    print()
    print("=== adoption share of caves ===")
    sh = knew.groupby("name").apply(
        lambda d: d["adopted"].mean() / (1 - d["held_round2"].mean())
        if d["held_round2"].mean() < 1 else float("nan"), include_groups=False)
    print(sh.round(3).to_string())

    diff = raw.groupby("qid")["baseline"].mean()
    k = knew.copy()
    k["perfect"] = k["qid"].map(diff) == 1
    print()
    print("=== difficulty split ===")
    print(k.groupby("perfect").agg(questions=("qid", "nunique"),
                                   hold=("held_round2", "mean")).round(4).to_string())

    print()
    print("=== accuracy vs holding correlation ===")
    print("all models      %.3f" % s["accuracy"].corr(s["held_push2"]))
    if "Grok 4.20" in s.index:
        d = s.drop("Grok 4.20")
        print("without Grok    %.3f" % d["accuracy"].corr(d["held_push2"]))

    bycat = knew.groupby(["name", "cat"])["held_round2"].mean().unstack()
    bycat.to_csv(os.path.join(HERE, "merged_by_category.csv"))
    print()
    print("=== by category ===")
    print("questions per category:")
    print(raw.groupby("cat")["qid"].nunique().to_string())
    print(bycat.round(2).to_string())

    pairs(os.path.join(HERE, "merged_all_rows.csv"))

    esc = knew.groupby("name")[["held_vs_doubt", "held_round1", "held_round2"]].mean()
    acc = raw.groupby("name")["baseline"].mean()
    data = {
        "escalation": [{"name": i, "doubt": round(r.held_vs_doubt, 4),
                        "push1": round(r.held_round1, 4), "push2": round(r.held_round2, 4)}
                       for i, r in esc.iterrows()],
        "scatter": [{"name": i, "accuracy": round(acc[i], 4),
                     "held": round(esc.loc[i, "held_round2"], 4)} for i in esc.index],
        "categories": list(bycat.columns),
        "cat_n": {k2: int(v) for k2, v in raw.groupby("cat")["qid"].nunique().items()},
        "heat": [{"name": i, "vals": [None if pd.isna(v) else round(v, 4)
                                      for v in bycat.loc[i]]} for i in bycat.index],
    }
    json.dump(data, open(os.path.join(HERE, "chartdata.json"), "w"), indent=1)
    print()
    print("wrote merged_raw.csv, merged_summary.csv, merged_by_category.csv, chartdata.json")


if __name__ == "__main__":
    report(load())
