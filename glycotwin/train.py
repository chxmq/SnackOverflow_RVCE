"""Patient-held-out evaluation of the twin's 2-hour risk heads and glucose forecaster.

5-fold GroupKFold by patient: no patient ever appears in both train and test.
Writes results/metrics.json, results/oof.parquet, figures/*.png and docs/twin_data.json.
"""
from __future__ import annotations

import json
import os

import lightgbm as lgb
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

from glycotwin.data import (CGM_FEATURES, EHR_FEATURES, EVENT_FEATURES, HORIZON_MIN, HYPER, HYPO,
                            ROOT, STEP_MIN, TWIN_FEATURES, build_dataset)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SEED = 7
FOLDS = 5
VARIANTS = {
    "EHR only": EHR_FEATURES + ["tod_sin", "tod_cos"],
    "CGM only": CGM_FEATURES,
    "CGM + events": CGM_FEATURES + EVENT_FEATURES,
    "CGM + events + twin memory": CGM_FEATURES + EVENT_FEATURES + TWIN_FEATURES,
    "Full twin (+ EHR)": CGM_FEATURES + EVENT_FEATURES + TWIN_FEATURES + EHR_FEATURES,
}
FULL = "Full twin (+ EHR)"
PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=100,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
              random_state=SEED, verbose=-1)
ALERT_P = 0.5  # fixed before looking at test folds


def folds(df):
    return list(GroupKFold(n_splits=FOLDS).split(df, groups=df["patient"]))


def oof_classifier(df, label, feats):
    d = df[df[label].notna()].reset_index(drop=True)
    p = np.zeros(len(d))
    contrib = np.zeros((len(d), len(feats))) if feats == VARIANTS[FULL] else None
    for tr, te in folds(d):
        m = lgb.LGBMClassifier(**PARAMS).fit(d.loc[tr, feats], d.loc[tr, label])
        p[te] = m.predict_proba(d.loc[te, feats])[:, 1]
        if contrib is not None:
            contrib[te] = m.predict(d.loc[te, feats], pred_contrib=True)[:, :-1]
    return d, p, contrib


def rule_score(d, label):
    # clinician's rule of thumb: extrapolate the last 30-min trend 60 min ahead
    s = d["g_now"] + 2 * d["d30"].fillna(0)
    return s if label == "y_hyper" else -s


def boot_auc_diff(y, a, b, groups, n=500, rng=np.random.default_rng(SEED)):
    ug = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in ug}
    diffs = []
    for _ in range(n):
        pick = rng.choice(ug, size=len(ug), replace=True)
        ii = np.concatenate([idx_by[g] for g in pick])
        if y[ii].min() == y[ii].max():
            continue
        diffs.append(roc_auc_score(y[ii], a[ii]) - roc_auc_score(y[ii], b[ii]))
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def event_metrics(df, d, p, kind):
    """Event-level view a clinician cares about: onsets caught, lead time, false alarms per day."""
    thr_cross = (lambda g: g >= HYPER) if kind == "hyper" else (lambda g: g < HYPO)
    pmap = pd.Series(p, index=pd.MultiIndex.from_frame(d[["record", "t"]]))
    caught, leads, n_events, false_eps, days = 0, [], 0, 0, 0.0
    w = HORIZON_MIN // STEP_MIN
    for rec, g in df.groupby("record", sort=False):
        g = g.reset_index(drop=True)
        days += len(g) * STEP_MIN / 1440
        risk = pmap.reindex(pd.MultiIndex.from_arrays([g["record"], g["t"]])).values
        alert = np.nan_to_num(risk) >= ALERT_P
        inside = thr_cross(g["cgm"].values)
        onsets = [i for i in range(1, len(g)) if inside[i] and not inside[i - 1] and not np.isnan(g["cgm"].values[i - 1])]
        for o in onsets:
            n_events += 1
            win = range(max(0, o - w), o - 0)  # alerts strictly before the crossing
            fired = [i for i in win if alert[i]]
            if fired:
                caught += 1
                leads.append((o - fired[0]) * STEP_MIN)
        # false alert episodes: an alert run with no crossing in the following 2 h
        i = 0
        while i < len(g):
            if alert[i]:
                j = i
                while j + 1 < len(g) and alert[j + 1]:
                    j += 1
                if not inside[i : min(len(g), i + w + 1)].any():
                    false_eps += 1
                i = j + 1
            else:
                i += 1
    return dict(events=n_events, caught=caught, recall=caught / max(n_events, 1),
                median_lead_min=float(np.median(leads)) if leads else None,
                false_alerts_per_day=false_eps / days, monitored_days=days)


def forecaster(df):
    out, rows = {}, {}
    for h in (30, 60, 90, 120):
        col = f"g_fut{h}"
        d = df[df[col].notna() & df["g_now"].notna()].reset_index(drop=True)
        feats = VARIANTS[FULL]
        pred = np.zeros(len(d))
        for tr, te in folds(d):
            m = lgb.LGBMRegressor(**PARAMS).fit(d.loc[tr, feats], d.loc[tr, col])
            pred[te] = m.predict(d.loc[te, feats])
        err = pred - d[col]
        pers = d["g_now"] - d[col]
        out[h] = dict(mae=float(err.abs().mean()), rmse=float(np.sqrt((err ** 2).mean())),
                      persistence_mae=float(pers.abs().mean()),
                      persistence_rmse=float(np.sqrt((pers ** 2).mean())), n=int(len(d)))
        rows[h] = pd.Series(pred, index=pd.MultiIndex.from_frame(d[["record", "t"]]))
    return out, rows


def main():
    os.makedirs(os.path.join(ROOT, "figures"), exist_ok=True)
    df = build_dataset()
    metrics = {"dataset": dict(records=int(df["record"].nunique()), patients=int(df["patient"].nunique()),
                               cgm_points=int(df["cgm_raw"].notna().sum()),
                               patient_days=float(len(df) * STEP_MIN / 1440))}
    oof = {}
    for label, kind in (("y_hyper", "hyper"), ("y_hypo", "hypo")):
        res = {}
        d0 = df[df[label].notna()].reset_index(drop=True)
        y = d0[label].values
        res["prevalence"] = float(y.mean())
        res["n_windows"] = int(len(y))
        rs = rule_score(d0, label).values
        res["Trend rule (no ML)"] = dict(auroc=float(roc_auc_score(y, rs)), auprc=float(average_precision_score(y, rs)))
        preds = {}
        for name, feats in VARIANTS.items():
            d, p, contrib = oof_classifier(df, label, feats)
            preds[name] = p
            res[name] = dict(auroc=float(roc_auc_score(y, p)), auprc=float(average_precision_score(y, p)))
            print(kind, name, res[name], flush=True)
            if contrib is not None:
                imp = pd.Series(np.abs(contrib).mean(0), index=feats).sort_values(ascending=False)
                res["top_features"] = {k: float(v) for k, v in imp.head(15).items()}
                oof[kind] = (d, p, contrib)
        g = d0["patient"].values
        res["full_minus_cgm_auroc_ci95"] = boot_auc_diff(y, preds[FULL], preds["CGM only"], g)
        res["full_minus_rule_auroc_ci95"] = boot_auc_diff(y, preds[FULL], rs, g)
        res["events_full_twin"] = event_metrics(df, d0, preds[FULL], kind)
        res["events_cgm_only"] = event_metrics(df, d0, preds["CGM only"], kind)
        metrics[kind] = res
        # per-patient AUROC spread for the full twin
        pp = []
        for pid, idx in d0.groupby("patient").groups.items():
            yy = y[idx]
            if 0 < yy.sum() < len(yy):
                pp.append(roc_auc_score(yy, preds[FULL][idx]))
        res["per_patient_auroc"] = dict(n=len(pp), median=float(np.median(pp)),
                                        q25=float(np.percentile(pp, 25)), q75=float(np.percentile(pp, 75)))
        # reliability
        bins = np.linspace(0, 1, 11)
        b = np.digitize(preds[FULL], bins) - 1
        res["calibration"] = [dict(bin=float(bins[i]), mean_pred=float(preds[FULL][b == i].mean()),
                                   obs=float(y[b == i].mean()), n=int((b == i).sum()))
                              for i in range(10) if (b == i).sum() > 50]

    fc, fc_rows = forecaster(df)
    metrics["forecast"] = fc
    with open(os.path.join(ROOT, "results", "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    figures(metrics)
    export_dashboard(df, oof, fc_rows)
    print(json.dumps(metrics, indent=1)[:4000])


def figures(m):
    plt.rcParams.update({"font.family": "Helvetica", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False})
    names = ["Trend rule (no ML)", "EHR only", "CGM only", "CGM + events", "CGM + events + twin memory", FULL]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, kind, title in ((axes[0], "hyper", "Rise above 180 mg/dL within 2 h"),
                            (axes[1], "hypo", "Fall below 70 mg/dL within 2 h")):
        v = [m[kind][n]["auroc"] for n in names]
        cols = ["#9aa0a6"] * 5 + ["#1a6b54"]
        ax.barh(range(len(names)), v, color=cols)
        for i, x in enumerate(v):
            ax.text(x + 0.005, i, f"{x:.3f}", va="center", fontsize=10)
        ax.set_yticks(range(len(names)), names if kind == "hyper" else [""] * len(names))
        ax.set_xlim(0.5, 1.0)
        ax.invert_yaxis()
        ax.set_xlabel("AUROC, patient-held-out (5-fold)")
        ax.set_title(title, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "figures", "ablation_auroc.png"), dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, kind in ((axes[0], "hyper"), (axes[1], "hypo")):
        c = m[kind]["calibration"]
        ax.plot([0, 1], [0, 1], color="#bbb", lw=1)
        ax.plot([r["mean_pred"] for r in c], [r["obs"] for r in c], "o-", color="#1a6b54")
        ax.set_xlabel("Predicted risk")
        ax.set_ylabel("Observed rate")
        ax.set_title({"hyper": "Hyperglycaemia head", "hypo": "Hypoglycaemia head"}[kind], loc="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "figures", "calibration.png"), dpi=200)
    plt.close(fig)

    fc = m["forecast"]
    hs = sorted(int(h) for h in fc)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    ax.plot(hs, [fc[h]["persistence_mae"] for h in hs], "o-", color="#9aa0a6", label="Persistence (no change)")
    ax.plot(hs, [fc[h]["mae"] for h in hs], "o-", color="#1a6b54", label="Twin forecaster")
    ax.set_xlabel("Minutes ahead")
    ax.set_ylabel("MAE (mg/dL)")
    ax.set_xticks(hs)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "figures", "forecast_mae.png"), dpi=200)
    plt.close(fig)


PRETTY = {
    "g_now": "Current glucose", "d15": "15-min trend", "d30": "30-min trend", "d60": "60-min trend",
    "accel": "Trend acceleration", "mean_2h": "2 h mean glucose", "sd_2h": "2 h glucose variability",
    "min_2h": "2 h minimum", "max_2h": "2 h maximum", "mean_6h": "6 h mean glucose",
    "tod_sin": "Time of day", "tod_cos": "Time of day", "min_since_meal": "Time since last meal",
    "last_meal_g": "Size of last meal", "meal_g_2h": "Food logged in last 2 h",
    "ins_sc_4h": "Insulin (s.c.) last 4 h", "ins_bolus_2h": "Bolus insulin last 2 h",
    "basal_rate": "Pump basal rate", "oral_4h": "Oral agent in last 4 h",
    "twin_mean": "Personal mean glucose (learned)", "twin_tar": "Personal time above range (learned)",
    "twin_cv": "Personal variability (learned)", "twin_meal_rise": "Personal post-meal rise (learned)",
    "twin_meal_habit": "Usual meal in next 2 h (learned)", "hba1c": "HbA1c", "homa_ir": "HOMA-IR",
    "cpep_f": "Fasting C-peptide", "cpep_2h": "2 h C-peptide", "on_insulin": "On insulin (EHR)",
    "on_sulfonylurea": "On sulfonylurea (EHR)", "hypo_history": "Past hypoglycaemia (EHR)",
    "egfr": "eGFR", "dm_years": "Years with diabetes", "bmi": "BMI", "age": "Age", "ga": "Glycated albumin",
    "fpg": "Fasting plasma glucose", "ppg2h": "2 h post-meal glucose", "ins_f": "Fasting insulin",
}


def export_dashboard(df, oof, fc_rows):
    """Three held-out patients for the doctor-facing UI (all numbers are out-of-fold)."""
    dh, ph, ch = oof["hyper"]
    do, po, co = oof["hypo"]
    feats = VARIANTS[FULL]
    rh = pd.Series(ph, index=pd.MultiIndex.from_frame(dh[["record", "t"]]))
    ro = pd.Series(po, index=pd.MultiIndex.from_frame(do[["record", "t"]]))
    ch_df = pd.DataFrame(ch, index=rh.index, columns=feats)
    co_df = pd.DataFrame(co, index=ro.index, columns=feats)
    # pick records with both kinds of events and good coverage
    stats = df.groupby("record").agg(hypo=("y_hypo", "sum"), hyper=("y_hyper", "sum"), n=("cgm", "count"))
    stats = stats[(stats.n > 800)]
    picks = list(stats.sort_values("hypo", ascending=False).index[:2]) + \
        list(stats[stats.hypo == 0].sort_values("hyper", ascending=False).index[:1])
    out = []
    for rec in picks:
        g = df[df.record == rec].reset_index(drop=True)
        g = g.iloc[-4 * 24 * 3:].reset_index(drop=True)  # last 3 days
        idx = pd.MultiIndex.from_arrays([g["record"], g["t"]])

        def top(cdf, i):
            if idx[i] not in cdf.index:
                return []
            row = cdf.loc[idx[i]]
            agg = {}
            for k, v in row.items():
                agg[PRETTY.get(k, k)] = agg.get(PRETTY.get(k, k), 0) + v
            s = pd.Series(agg).sort_values(key=np.abs, ascending=False).head(5)
            return [[k, round(float(v), 3)] for k, v in s.items()]

        pts = []
        for i in range(len(g)):
            r = g.iloc[i]
            pts.append(dict(
                t=r["t"].strftime("%Y-%m-%d %H:%M"),
                g=None if pd.isna(r["cgm_raw"]) else round(float(r["cgm_raw"]), 1),
                hyper=None if idx[i] not in rh.index else round(float(rh.loc[idx[i]]), 3),
                hypo=None if idx[i] not in ro.index else round(float(ro.loc[idx[i]]), 3),
                fc=[None if idx[i] not in fc_rows[h].index else round(float(fc_rows[h].loc[idx[i]]), 1)
                    for h in (30, 60, 90, 120)],
                meal=r["meal_text"] or None,
                ins=round(float(r["ins_sc"] + r["ins_bolus"]), 1) or None,
                oral=int(r["oral"]) or None,
                why_hyper=top(ch_df, i), why_hypo=top(co_df, i),
                twin=dict(meal_rise=None if pd.isna(r["twin_meal_rise"]) else round(float(r["twin_meal_rise"]), 1),
                          habit=None if pd.isna(r["twin_meal_habit"]) else round(float(r["twin_meal_habit"]), 2),
                          mean=None if pd.isna(r["twin_mean"]) else round(float(r["twin_mean"]), 1),
                          tar=None if pd.isna(r["twin_tar"]) else round(float(r["twin_tar"]), 3)),
            ))
        s = g.iloc[0]
        ehr = dict(record=rec, sex="F" if s["female"] else "M", age=int(s["age"]), bmi=s["bmi"],
                   dm_years=s["dm_years"], hba1c_mmol=s["hba1c"],
                   hba1c_pct=None if pd.isna(s["hba1c"]) else round(s["hba1c"] / 10.929 + 2.15, 1),
                   cpep_f=s["cpep_f"], egfr=s["egfr"], homa_ir=None if pd.isna(s["homa_ir"]) else round(s["homa_ir"], 1),
                   hypo_history=int(s["hypo_history"]),
                   agents=[k.replace("on_", "") for k in ("on_insulin", "on_metformin", "on_sulfonylurea",
                                                           "on_acarbose", "on_dpp4", "on_sglt2", "on_glp1") if s[k]],
                   n_macro=int(s["n_macro"]), n_micro=int(s["n_micro"]), n_comorb=int(s["n_comorb"]))
        ehr = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in ehr.items()}
        out.append(dict(ehr=ehr, points=pts))
    with open(os.path.join(ROOT, "docs", "twin_data.json"), "w") as f:
        json.dump(dict(alert_p=ALERT_P, patients=out), f)


if __name__ == "__main__":
    main()
