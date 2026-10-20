"""Load ShanghaiT2DM and build the two input streams of the twin.

Static stream  : one EHR-style record per monitoring period (Shanghai_T2DM_Summary.xlsx)
Dynamic stream : 15-min CGM plus logged meals, insulin and oral agents (one file per period)

Every feature at time t uses only data at or before t. Labels look at (t, t+120 min].
"""
from __future__ import annotations

import glob
import os
import re

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

STEP_MIN = 15          # CGM sampling interval in this dataset
HORIZON_MIN = 120      # prediction horizon
HYPER = 180.0          # mg/dL, ADA time-in-range upper bound
HYPO = 70.0            # mg/dL, ADA level-1 hypoglycaemia

LAB_COLS = {
    "Fasting Plasma Glucose (mg/dl)": "fpg",
    "2-hour Postprandial Plasma Glucose (mg/dl)": "ppg2h",
    "Fasting C-peptide (nmol/L)": "cpep_f",
    "2-hour Postprandial C-peptide (nmol/L)": "cpep_2h",
    "Fasting Insulin (pmol/L)": "ins_f",
    "2-hour Postprandial insulin (pmol/L)": "ins_2h",
    "HbA1c (mmol/mol)": "hba1c",
    "Glycated Albumin (%)": "ga",
    "Total Cholesterol (mmol/L)": "tc",
    "Triglyceride (mmol/L)": "tg",
    "High-Density Lipoprotein Cholesterol (mmol/L)": "hdl",
    "Low-Density Lipoprotein Cholesterol (mmol/L)": "ldl",
    "Creatinine (umol/L)": "creat",
    "Estimated Glomerular Filtration Rate  (ml/min/1.73m2) ": "egfr",
    "Uric Acid (mmol/L)": "ua",
    "Blood Urea Nitrogen (mmol/L)": "bun",
}

AGENTS = {
    "on_insulin": r"insulin|humulin|novolin|gansulin|glargine|detemir|degludec|lispro|aspart",
    "on_metformin": r"metformin",
    "on_sulfonylurea": r"glimepiride|gliclazide|glipizide|glibenclamide|gliquidone",
    "on_acarbose": r"acarbose|voglibose",
    "on_dpp4": r"gliptin",
    "on_sglt2": r"gliflozin",
    "on_glp1": r"glutide|exenatide|glp",
}


def _num(x):
    try:
        return float(str(x).strip())
    except ValueError:
        return np.nan


def _count_items(x):
    s = str(x).strip().lower()
    if s in ("", "none", "nan"):
        return 0
    return len([p for p in re.split(r"[,;]", s) if p.strip()])


def load_static() -> pd.DataFrame:
    s = pd.read_excel(os.path.join(RAW, "Shanghai_T2DM_Summary.xlsx"))
    out = pd.DataFrame({"record": s["Patient Number"].astype(str).str.strip()})
    out["patient"] = out["record"].str.split("_").str[0]
    out["female"] = (s["Gender (Female=1, Male=2)"] == 1).astype(int)
    out["age"] = s["Age (years)"]
    out["bmi"] = s["BMI (kg/m2)"]
    out["smoking_py"] = s["Smoking History (pack year)"]
    out["drinker"] = (s["Alcohol Drinking History (drinker/non-drinker)"].astype(str).str.strip() == "drinker").astype(int)
    out["dm_years"] = s["Duration of diabetes (years)"]
    out["n_macro"] = s["Diabetic Macrovascular  Complications"].map(_count_items)
    out["n_micro"] = s["Diabetic Microvascular Complications"].map(_count_items)
    out["n_comorb"] = s["Comorbidities"].map(_count_items)
    out["hypo_history"] = (s["Hypoglycemia (yes/no)"].astype(str).str.strip() == "yes").astype(int)
    agents = s["Hypoglycemic Agents"].astype(str).str.lower()
    for k, pat in AGENTS.items():
        out[k] = agents.str.contains(pat).astype(int)
    for src, dst in LAB_COLS.items():
        out[dst] = s[src].map(_num)
    # HOMA-IR from fasting glucose (mg/dL) and fasting insulin (pmol/L -> uU/mL /6)
    out["homa_ir"] = (out["fpg"] / 18.0) * (out["ins_f"] / 6.0) / 22.5
    return out


def _col(d: pd.DataFrame, key: str):
    for c in d.columns:
        if key.lower() in str(c).lower():
            return c
    return None


def _grams(text) -> float:
    if not isinstance(text, str):
        return 0.0
    return float(sum(float(g) for g in re.findall(r"(\d+(?:\.\d+)?)\s*g\b", text)))


def _iu(text) -> float:
    if isinstance(text, (int, float)):
        return 0.0 if pd.isna(text) else float(text)
    if not isinstance(text, str):
        return 0.0
    return float(sum(float(u) for u in re.findall(r"(\d+(?:\.\d+)?)\s*IU", text, flags=re.I)))


def load_dynamic(record: str) -> pd.DataFrame:
    """One monitoring period on a regular 15-min grid."""
    path = [p for p in glob.glob(os.path.join(RAW, "Shanghai_T2DM", record + ".*"))][0]
    d = pd.read_excel(path)
    t = pd.to_datetime(d["Date"])
    cgm = pd.to_numeric(d[_col(d, "CGM")], errors="coerce")
    meal = d[_col(d, "Dietary intake")]
    sc = d[_col(d, "Insulin dose - s.c")]
    oral = d[_col(d, "Non-insulin")]
    bolus = d[_col(d, "bolus")] if _col(d, "bolus") else pd.Series(np.nan, index=d.index)
    basal = d[_col(d, "basal")] if _col(d, "basal") else pd.Series(np.nan, index=d.index)
    iv = d[_col(d, "i.v")]

    ev = pd.DataFrame({
        "t": t.dt.round(f"{STEP_MIN}min"),
        "cgm": cgm,
        "meal_g": meal.map(_grams),
        "meal": meal.notna().astype(int),
        "ins_sc": sc.map(_iu),
        "ins_bolus": pd.to_numeric(bolus, errors="coerce").fillna(0) + iv.map(_iu),
        "basal_rate": pd.to_numeric(basal, errors="coerce"),
        "oral": oral.notna().astype(int),
        "meal_text": meal.where(meal.notna(), ""),
    })
    agg = ev.groupby("t").agg(
        cgm=("cgm", "mean"), meal_g=("meal_g", "sum"), meal=("meal", "max"),
        ins_sc=("ins_sc", "sum"), ins_bolus=("ins_bolus", "sum"),
        basal_rate=("basal_rate", "max"), oral=("oral", "max"),
        meal_text=("meal_text", lambda x: " | ".join(s for s in x if s)),
    )
    grid = pd.date_range(agg.index.min(), agg.index.max(), freq=f"{STEP_MIN}min")
    g = agg.reindex(grid)
    g.index.name = "t"
    for c in ("meal_g", "meal", "ins_sc", "ins_bolus", "oral"):
        g[c] = g[c].fillna(0)
    g["meal_text"] = g["meal_text"].fillna("")
    g["basal_rate"] = g["basal_rate"].ffill().fillna(0)
    # fill CGM dropouts up to 30 min by linear interpolation; longer gaps stay missing
    g["cgm_raw"] = g["cgm"]
    g["cgm"] = g["cgm"].interpolate(limit=2, limit_area="inside")
    g = g.reset_index()
    g["record"] = record
    return g


def _rolling_sum(x: pd.Series, steps: int) -> pd.Series:
    return x.rolling(steps, min_periods=1).sum()


def build_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    c = g["cgm"]
    per_h = 60 // STEP_MIN
    for k in (1, 2, 3, 4, 6, 8):
        g[f"g_lag{k * STEP_MIN}"] = c.shift(k)
    g["g_now"] = c
    g["d15"] = c - c.shift(1)
    g["d30"] = c - c.shift(2)
    g["d60"] = c - c.shift(4)
    g["accel"] = g["d15"] - g["d15"].shift(1)
    roll = c.rolling(2 * per_h, min_periods=4)
    g["mean_2h"], g["sd_2h"], g["min_2h"], g["max_2h"] = roll.mean(), roll.std(), roll.min(), roll.max()
    g["mean_6h"] = c.rolling(6 * per_h, min_periods=8).mean()
    hour = g["t"].dt.hour + g["t"].dt.minute / 60
    g["tod_sin"], g["tod_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    g["hour"] = hour

    # logged events (dynamic stream, beyond the sensor)
    idx = np.arange(len(g))
    last_meal = pd.Series(np.where(g["meal"] > 0, idx, np.nan)).ffill()
    g["min_since_meal"] = ((idx - last_meal) * STEP_MIN).clip(upper=480).fillna(480)
    last_meal_g = pd.Series(np.where(g["meal"] > 0, g["meal_g"], np.nan)).ffill().fillna(0)
    g["last_meal_g"] = last_meal_g.values
    g["meal_g_2h"] = _rolling_sum(g["meal_g"], 2 * per_h)
    g["ins_sc_4h"] = _rolling_sum(g["ins_sc"], 4 * per_h)
    g["ins_bolus_2h"] = _rolling_sum(g["ins_bolus"], 2 * per_h)
    g["oral_4h"] = _rolling_sum(g["oral"], 4 * per_h).clip(upper=1)

    # twin memory: what the twin has learned about this person so far (strictly causal)
    g["twin_mean"] = c.expanding(min_periods=8).mean()
    g["twin_tar"] = (c >= HYPER).astype(float).where(c.notna()).expanding(min_periods=8).mean()
    g["twin_cv"] = c.expanding(min_periods=8).std() / g["twin_mean"]
    # personal post-meal rise, learned only from meals whose 2 h window has fully passed
    rise = np.full(len(g), np.nan)
    meal_idx = np.flatnonzero(g["meal"].values > 0)
    w = HORIZON_MIN // STEP_MIN
    learned, sums, n = np.full(len(g), np.nan), 0.0, 0
    events = []
    for m in meal_idx:
        if m + w < len(g) and not np.isnan(c.iloc[m]):
            peak = np.nanmax(c.iloc[m + 1 : m + w + 1].values) if c.iloc[m + 1 : m + w + 1].notna().any() else np.nan
            if not np.isnan(peak):
                events.append((m + w, peak - c.iloc[m]))
    ei = 0
    for i in range(len(g)):
        while ei < len(events) and events[ei][0] <= i:
            sums += events[ei][1]
            n += 1
            ei += 1
        if n:
            learned[i] = sums / n
    g["twin_meal_rise"] = learned
    # habit: share of previous days with a meal logged in the next 2 h of clock time
    day = (g["t"] - g["t"].iloc[0].normalize()).dt.days
    slot = (g["t"].dt.hour * 60 + g["t"].dt.minute) // STEP_MIN
    meal_tab = np.zeros((day.max() + 1, 96))
    for di, si, mv in zip(day, slot, g["meal"]):
        if mv:
            meal_tab[di, si] = 1
    habit = np.full(len(g), np.nan)
    for i, (di, si) in enumerate(zip(day, slot)):
        if di == 0:
            continue
        cols = [(si + k) % 96 for k in range(1, w + 1)]
        habit[i] = meal_tab[:di][:, cols].max(axis=1).mean()
    g["twin_meal_habit"] = habit

    # labels
    fut = pd.concat([c.shift(-k) for k in range(1, w + 1)], axis=1)
    fut_raw = pd.concat([g["cgm_raw"].shift(-k) for k in range(1, w + 1)], axis=1)
    enough = fut_raw.notna().sum(axis=1) >= w - 2
    g["fut_max"] = fut.max(axis=1)
    g["fut_min"] = fut.min(axis=1)
    g["y_hyper"] = ((g["fut_max"] >= HYPER) & (c < HYPER)).astype(float).where(enough & c.notna() & (c < HYPER))
    g["y_hypo"] = ((g["fut_min"] < HYPO) & (c >= HYPO)).astype(float).where(enough & c.notna() & (c >= HYPO))
    for k in (2, 4, 6, 8):
        g[f"g_fut{k * STEP_MIN}"] = c.shift(-k).where(g["cgm_raw"].shift(-k).notna())
    return g


CGM_FEATURES = ["g_now", "g_lag15", "g_lag30", "g_lag45", "g_lag60", "g_lag90", "g_lag120",
                "d15", "d30", "d60", "accel", "mean_2h", "sd_2h", "min_2h", "max_2h", "mean_6h",
                "tod_sin", "tod_cos"]
EVENT_FEATURES = ["min_since_meal", "last_meal_g", "meal_g_2h", "ins_sc_4h", "ins_bolus_2h",
                  "basal_rate", "oral_4h"]
TWIN_FEATURES = ["twin_mean", "twin_tar", "twin_cv", "twin_meal_rise", "twin_meal_habit"]
EHR_FEATURES = ["female", "age", "bmi", "smoking_py", "drinker", "dm_years", "n_macro", "n_micro",
                "n_comorb", "hypo_history", *AGENTS.keys(), *LAB_COLS.values(), "homa_ir"]


def build_dataset(cache: str | None = os.path.join(ROOT, "results", "dataset.parquet")) -> pd.DataFrame:
    if cache and os.path.exists(cache):
        return pd.read_parquet(cache)
    static = load_static()
    frames = [build_features(load_dynamic(r)) for r in static["record"]]
    dyn = pd.concat(frames, ignore_index=True)
    df = dyn.merge(static, on="record", how="left")
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        df.to_parquet(cache)
    return df


if __name__ == "__main__":
    df = build_dataset(cache=None)
    print(df.shape, df["record"].nunique(), "records", df["patient"].nunique(), "patients")
    print("hyper onset windows:", int(df["y_hyper"].sum()), "/", int(df["y_hyper"].notna().sum()))
    print("hypo onset windows:", int(df["y_hypo"].sum()), "/", int(df["y_hypo"].notna().sum()))
