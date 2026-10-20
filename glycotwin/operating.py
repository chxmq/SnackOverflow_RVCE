"""Follow-up analyses after the main run (same folds, same parameters):

1. Alert trade-off: event recall vs false alert episodes per patient-day over a grid of thresholds.
2. Core EHR: 9 pre-specified clinical fields instead of all 33 (100 patients is few for 33 static fields).
3. Cold start: AUROC on day 1 of monitoring (twin memory still empty) vs later days.

Writes results/operating.json and figures/tradeoff.png, figures/coldstart.png.
"""
import json
import os

import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from glycotwin.data import CGM_FEATURES, EVENT_FEATURES, ROOT, TWIN_FEATURES, build_dataset
from glycotwin.train import VARIANTS, boot_auc_diff, event_metrics, oof_classifier

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import glycotwin.train as T  # noqa: E402

CORE_EHR = ["hba1c", "cpep_f", "homa_ir", "on_insulin", "on_sulfonylurea", "hypo_history", "dm_years", "bmi", "egfr"]
RUN = {
    "CGM only": VARIANTS["CGM only"],
    "Personal twin (CGM + events + memory)": CGM_FEATURES + EVENT_FEATURES + TWIN_FEATURES,
    "Personal twin + core EHR (9 fields)": CGM_FEATURES + EVENT_FEATURES + TWIN_FEATURES + CORE_EHR,
    "Full twin (+ EHR)": VARIANTS["Full twin (+ EHR)"],
}
THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6]


def main():
    df = build_dataset()
    day0 = df.groupby("record")["t"].transform("min").dt.normalize()
    df["mon_day"] = (df["t"] - day0).dt.days
    out = {}
    for label, kind in (("y_hyper", "hyper"), ("y_hypo", "hypo")):
        d0 = df[df[label].notna()].reset_index(drop=True)
        y, g = d0[label].values, d0["patient"].values
        preds, res = {}, {}
        for name, feats in RUN.items():
            T.VARIANTS = {**VARIANTS, "_cur": feats}  # contrib only computed for FULL; harmless here
            _, p, _ = oof_classifier(df, label, feats)
            preds[name] = p
            r = dict(auroc=float(roc_auc_score(y, p)), auprc=float(average_precision_score(y, p)))
            first = d0["mon_day"].values == 0
            later = ~first
            r["auroc_day1"] = float(roc_auc_score(y[first], p[first])) if 0 < y[first].sum() < first.sum() else None
            r["auroc_later"] = float(roc_auc_score(y[later], p[later]))
            r["n_day1"], r["pos_day1"] = int(first.sum()), int(y[first].sum())
            curve = []
            for th in THRESHOLDS:
                T.ALERT_P = th
                e = event_metrics(df, d0, p, kind)
                curve.append(dict(threshold=th, recall=e["recall"], false_per_day=e["false_alerts_per_day"],
                                  median_lead_min=e["median_lead_min"], events=e["events"]))
            T.ALERT_P = 0.5
            r["tradeoff"] = curve
            res[name] = r
            print(kind, name, {k: v for k, v in r.items() if k != "tradeoff"}, flush=True)
        names = list(RUN)
        res["ci_vs_cgm"] = {n: boot_auc_diff(y, preds[n], preds["CGM only"], g) for n in names[1:]}
        first = d0["mon_day"].values == 0
        res["ci_day1_core_vs_personal"] = boot_auc_diff(y[first], preds[names[2]][first], preds[names[1]][first], g[first])
        out[kind] = res
        pd.DataFrame({"record": d0["record"], "t": d0["t"], **{n: preds[n] for n in names}}).to_parquet(
            os.path.join(ROOT, "results", f"oof_{kind}.parquet"))
    with open(os.path.join(ROOT, "results", "operating.json"), "w") as f:
        json.dump(out, f, indent=2)

    plt.rcParams.update({"font.family": "Helvetica", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    colors = {"CGM only": "#9aa0a6", "Personal twin (CGM + events + memory)": "#1a6b54",
              "Personal twin + core EHR (9 fields)": "#c2571a", "Full twin (+ EHR)": "#2f5fb3"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    for ax, kind, title in ((axes[0], "hyper", "Highs: rise above 180 within 2 h"), (axes[1], "hypo", "Lows: fall below 70 within 2 h")):
        for n in RUN:
            c = out[kind][n]["tradeoff"]
            ax.plot([r["false_per_day"] for r in c], [r["recall"] for r in c], "o-", ms=4, color=colors[n], label=n)
            if n == "Personal twin (CGM + events + memory)":
                for r in c:
                    if r["threshold"] in (0.1, 0.2, 0.5):
                        ax.annotate(f"p≥{r['threshold']}", (r["false_per_day"], r["recall"]), textcoords="offset points", xytext=(6, -10), fontsize=9)
        ax.set_xlabel("False alert episodes per patient-day")
        ax.set_ylabel("Excursions caught before onset")
        ax.set_ylim(0, 1.02)
        ax.set_title(title, loc="left", fontsize=12)
    axes[1].legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "figures", "tradeoff.png"), dpi=200)
    plt.close(fig)
    print(json.dumps({k: {n: {kk: vv for kk, vv in v.items() if kk != "tradeoff"} if isinstance(v, dict) and "auroc" in v else v
                          for n, v in r.items()} for k, r in out.items()}, indent=1))


if __name__ == "__main__":
    main()
