"""Narration for the demo video, one entry per frame. Numbers are read from results/metrics.json."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = json.load(open(os.path.join(ROOT, "results", "metrics.json")))
H, O, F, D = M["hyper"], M["hypo"], M["forecast"], M["dataset"]
FULL = "Full twin (+ EHR)"
OP = json.load(open(os.path.join(ROOT, "results", "operating.json")))
OPH, OPO = OP["hyper"], OP["hypo"]
PT, CE = "Personal twin (CGM + events + memory)", "Personal twin + core EHR (9 fields)"
TH = {r["threshold"]: r for r in OPH[PT]["tradeoff"]}
TO = {r["threshold"]: r for r in OPO[PT]["tradeoff"]}


def ci(r, k):
    lo, hi = r["ci_vs_cgm"][k]
    return f"from {lo:+.3f} to {hi:+.3f}"


def d1(r, k):
    v = r[k]["auroc_day1"]
    return "not defined" if v is None else f"{v:.3f}"


def p(x):
    return f"{100 * x:.0f} percent"


def a(x):
    return f"{x:.2f}"


def lead(e):
    return "no" if e["median_lead_min"] is None else f"{e['median_lead_min']:.0f} minutes of"


FRAMES = [
    ("slide01", f"""Hello. We are team Snack Overflow from R V College of Engineering, Bengaluru: Yash Saraogi, who leads the team, Tallam Sri Sai Subramanyam, and Yash Gautam.
This is our submission to the Happiest Health Digital Twin Challenge. Our project is called GlycoTwin. It is a digital twin of a person with type 2 diabetes. It fuses two streams of data, the health record and a continuous glucose sensor, and it warns a clinician up to two hours before the patient's glucose leaves the safe range, in either direction.
In the next fifteen minutes or so we will cover the problem, the use case, the data we chose and why, the architecture, what exactly makes this a twin, how we evaluated it, the results on patients the model never saw, the doctor's dashboard, and finally what this proof of concept does not show yet.
Every number you will see comes out of the code in our public repository, and one command reproduces all of them."""),

    ("slide02", """Let us start with the problem.
According to the ICMR INDIAB study published in the Lancet Diabetes and Endocrinology in 2023, about one hundred and one million Indians live with diabetes, and another one hundred and thirty six million have prediabetes. Most of them have type 2 diabetes.
The main number a doctor uses to manage them is HbA1c. HbA1c is a three month average. It is a good long term marker, but it cannot tell you when glucose went high after lunch, or how low it fell at three in the morning.
A continuous glucose monitor that samples every fifteen minutes records ninety six readings a day. Over one quarter, that is eight thousand six hundred and forty readings for a single patient. No clinician can read that raw, especially across a panel of patients.
And the risks are real in both directions. Hypoglycaemia in people on insulin or sulfonylureas is the acute danger: falls, arrhythmia, hospital admission. Repeated high spikes after meals are the slow danger that drives complications.
So what is missing is a model of this one patient that reads the record and the live stream together, learns how this person responds to meals, says two hours early which way glucose is about to leave the range, and shows the doctor why. That is how we scoped our digital twin. One condition, type 2 diabetes, one clinically meaningful adverse event, and an explanation for every alert."""),

    ("slide03", """Here is the healthcare use case, concretely.
The user is a diabetes team: an endocrinologist, a diabetes educator, or a ward nurse. They are looking after a panel of patients who wear a continuous glucose monitor, either in an inpatient ward or in remote monitoring after discharge.
The input is what such a team already has: the record taken at admission, the live sensor stream, and the meal and dose logs.
The twin produces two alerts. A hyperglycaemia alert means the patient is likely to rise above one hundred and eighty milligrams per decilitre within the next two hours. The team can then check the meal, consider a correction dose, or suggest a walk. A hypoglycaemia alert means the patient is likely to fall below seventy within two hours. The team can offer a snack or hold the next sulfonylurea or insulin dose.
The twin view also shows what it has learned about this person: their usual post meal rise, and when they usually eat. That helps tailor dose and diet advice.
Every alert comes with its top five reasons, so a doctor can overrule an alert whose reason does not make clinical sense.
To be clear, the twin does not dose and does not prescribe. It is decision support. It ranks who needs attention in the next two hours and explains why."""),

    ("slide04", f"""Now the data, and the sandbox rules.
The challenge requires anonymised, open source, or synthetic data. We chose real, anonymised data rather than only synthetic data. The dataset is Shanghai T2DM, published by Zhao and colleagues in Scientific Data in 2023, under a Creative Commons attribution licence.
It contains {D['patients']} people with type 2 diabetes. Some were monitored in more than one period, so there are {D['records']} monitoring periods in total, with {D['cgm_points']:,} continuous glucose readings at fifteen minute intervals. That is about {D['patient_days']:.0f} patient days.
The static stream is the electronic health record. For each period there are thirty three fields: age, sex, BMI, smoking and alcohol history, years since diagnosis, acute, macrovascular and microvascular complications, comorbidities, the glucose lowering drugs and other drugs. There are sixteen lab tests, including fasting and two hour glucose, C peptide, insulin, HbA1c, glycated albumin, lipids, eGFR and uric acid. We also derive HOMA IR, an index of insulin resistance, from fasting glucose and fasting insulin.
The dynamic stream is the sensor plus the logs: meals written in free text with grams, subcutaneous insulin doses, insulin pump bolus and basal rates, and oral agents.
Why not just generate synthetic data? Because a model trained on our own simulator would mostly learn our simulator. Real glucose data keeps us honest. And it satisfies the sandbox rules: the data is public, de identified and openly licensed. No identifiable patient data is used anywhere, which keeps us within the spirit of the D P D P Act and HIPAA."""),

    ("slide05", """This is the architecture.
On the left are the two input streams. The static stream is the health record, one row per monitoring period. The dynamic stream is the glucose sensor every fifteen minutes, plus meal and dose logs. Below them, drawn with a light border, are adapters we have designed but not built in this proof of concept: reading records through FHIR and India's A B D M, and reading heart rate, steps and sleep from Apple Health or Google Fit. We list them so it is clear what is and is not in the prototype.
The ingest and align stage puts each patient on a regular fifteen minute grid. It fills sensor gaps only up to thirty minutes, and leaves longer gaps missing rather than inventing data. It parses grams of food from the meal text and units of insulin from the dose text, and turns the record fields into numbers. Most importantly, it is causal. Nothing that happens after time t is allowed into the state at time t.
The twin state at time t has four parts: glucose features such as level, lags, trends and two and six hour windows; event features such as time since the last meal, food in the last two hours, and insulin on board; the twin memory, which we will explain next; and the thirty three field record profile.
From this state, three gradient boosted tree models, built with LightGBM, produce three outputs: the probability of a rise above one eighty within two hours, the probability of a fall below seventy within two hours, and the glucose trajectory at thirty, sixty, ninety and one hundred and twenty minutes.
All of this feeds the clinician dashboard."""),

    ("slide06", """So what makes this a twin, and not just a glucose forecaster? Our answer is memory. The twin keeps a model of this particular patient and updates it as data arrives.
There are four learned items. The personal mean glucose is the running mean of every reading so far. The personal time above range is the share of readings at or above one eighty so far. The personal post meal rise is the average peak rise in the two hours after each of this patient's past meals. And the usual meal in the next two hours is the share of past days on which this patient logged a meal in the same clock window, for example between one and three in the afternoon.
On top of that sits the record profile: HbA1c, C peptide, HOMA IR, drugs and complications.
One detail matters a lot for honesty. Every memory item is computed only from data before time t. A meal counts toward the post meal rise only after its full two hour window has passed. Otherwise the future glucose, which is our label, would leak into the feature, and the results would look better than they really are.
Because the memory is causal, the twin can be replayed. In the dashboard you can drag a cursor through time and watch the memory grow exactly as it would have at the bedside."""),

    ("slide07", f"""Now the evaluation protocol. Our rule was that every number in this presentation must be on patients the model never saw during training.
The two targets are defined like this. Hyper: glucose is below one eighty now, and any reading in the next two hours is at or above one eighty. Hypo: glucose is at or above seventy now, and any reading in the next two hours is below seventy. So we predict the onset of an excursion, not its continuation, which is the clinically useful and harder question.
For splitting, we use five fold group k fold by patient. All periods from one patient go to the same fold, so the model never trains on a patient it is tested on.
The alert threshold is fixed at a probability of zero point five before looking at any test fold. We did not tune it on test data.
For uncertainty, we bootstrap over patients, five hundred resamples, not over individual windows, because windows from the same patient are strongly correlated and would give falsely narrow intervals.
We compare against a simple trend rule, which is current glucose plus twice the last thirty minute change, roughly what a nurse would eyeball. And we run ablations: record only, sensor only, sensor plus events, plus twin memory, and the full twin with the record.
There are {H['n_windows']:,} hyper windows, of which {p(H['prevalence'])} are positive, and {O['n_windows']:,} hypo windows, of which {100 * O['prevalence']:.1f} percent are positive. So hypoglycaemia is the rarer and harder event."""),

    ("slide08", f"""Here are the main results, all on held out patients.
Start at the top. The trend rule, with no machine learning, reaches an area under the ROC curve of {H['Trend rule (no ML)']['auroc']:.3f} for highs and {O['Trend rule (no ML)']['auroc']:.3f} for lows. The record alone reaches {H['EHR only']['auroc']:.3f} for highs and only {O['EHR only']['auroc']:.3f} for lows. The sensor alone reaches {H['CGM only']['auroc']:.3f} and {O['CGM only']['auroc']:.3f}.
The personal twin, which is the sensor plus meal and dose events plus the twin's memory of the patient, is the best model overall: {OPH[PT]['auroc']:.3f} for highs and {OPO[PT]['auroc']:.3f} for lows.
The last two rows add the record on top: first nine core clinical fields chosen in advance, then all thirty three. They score {OPH[CE]['auroc']:.3f} and {H[FULL]['auroc']:.3f} for highs, and {OPO[CE]['auroc']:.3f} and {O[FULL]['auroc']:.3f} for lows. So they are close, but not better. We come back to this in two slides, because it is our most important finding.
The precision recall numbers tell the same story. For a rare event like a low, chance level is just the prevalence, {O['prevalence']:.3f}, and the personal twin reaches {OPO[PT]['auprc']:.3f}.
Against the trend rule, the gain is clear. The ninety five percent confidence interval over patients for the full twin minus the trend rule is {H['full_minus_rule_auroc_ci95'][0]:+.3f} to {H['full_minus_rule_auroc_ci95'][1]:+.3f} for highs, and {O['full_minus_rule_auroc_ci95'][0]:+.3f} to {O['full_minus_rule_auroc_ci95'][1]:+.3f} for lows. Both exclude zero."""),

    ("slide09", """This chart shows the ablation visually. Grey bars are the baselines and partial models. The left panel is highs and the right panel is lows.
Three things stand out. First, the record alone cannot time an event. It knows who is at risk in general, for example someone on insulin with a history of hypoglycaemia, but not when. For lows it is close to chance. Second, the live sensor carries most of the timing. Third, the twin memory, what the model has learned about this patient from their own data, adds on top of the sensor. For highs that gain is clear. For lows it is within noise, and we say so on the next slide. The memory is the part that makes this a twin rather than a generic forecaster."""),

    ("slide10", f"""Now the honest finding about fusion with the record.
This table shows the gain in AUROC over the sensor only model, with ninety five percent confidence intervals from a patient bootstrap. The personal twin gains {ci(OPH, PT)} for highs, and {ci(OPO, PT)} for lows. Adding the nine core record fields gives {ci(OPH, CE)} for highs and {ci(OPO, CE)} for lows. Adding all thirty three gives {ci(OPH, FULL)} and {ci(OPO, FULL)}.
So for highs, the twin's memory gives a gain whose interval excludes zero. For lows, every interval includes zero, so we cannot claim a gain there. And in this cohort, once the twin has a few hours of a patient's glucose, the static record adds no measurable accuracy. We expected the record to help most on the first day, before the memory fills. So we checked day one separately. On day one the sensor only model scores {d1(OPH, 'CGM only')} for highs, and with the core record {d1(OPH, CE)}. The record did not rescue day one either.
Why? We think the twin's learned mean glucose and time above range are a current, personal version of what HbA1c summarises over three months. And with only one hundred patients, thirty three static fields mostly let the trees memorise who is who, which does not transfer to a new patient.
We decided to report this rather than hide it. The record still matters. On its own it carries population risk, and a clinician needs it beside every alert to decide what to do. In our design it is context for the doctor, not the source of the timing. Testing whether it adds accuracy in a larger and more varied cohort is on our roadmap."""),

    ("slide11", f"""A ranking metric is not what a ward sees, so we also measured events.
An excursion is a crossing from in range to out of range. It counts as caught if an alert fired at any fifteen minute step in the two hours before the crossing. A false alert episode is a run of consecutive alerts with no crossing in the two hours after it starts.
The chart plots, for each model, the share of excursions caught against false alert episodes per patient day, as the threshold moves. Up and to the left is better.
At the threshold of zero point five, which we fixed in advance, the personal twin catches {p(TH[0.5]['recall'])} of the {TH[0.5]['events']:,} high excursions, with a median lead time of {TH[0.5]['median_lead_min']:.0f} minutes, and {TH[0.5]['false_per_day']:.2f} false alert episodes per patient day.
Lows are different. They are rare, only about three percent of windows, so the model's probabilities rarely reach zero point five. At that threshold the twin catches only {p(TO[0.5]['recall'])} of lows. If a ward lowers the threshold to zero point two, it catches {p(TO[0.2]['recall'])}, at {TO[0.2]['false_per_day']:.2f} false episodes per patient day. At zero point one it catches {p(TO[0.1]['recall'])}, at {TO[0.1]['false_per_day']:.2f}.
We did not tune these on the test data. We read them off the curve to show the cost, so that a clinical team can choose its own trade off between missed lows and alert fatigue."""),

    ("slide12", f"""The twin also forecasts the trajectory, not just the risk.
On the left is the mean absolute error of the forecast at thirty, sixty, ninety and one hundred and twenty minutes, against a no change baseline that assumes glucose stays where it is. At sixty minutes the twin's error is {F['60']['mae']:.1f} milligrams per decilitre, against {F['60']['persistence_mae']:.1f} for no change. At two hours it is {F['120']['mae']:.1f} against {F['120']['persistence_mae']:.1f}.
On the right is calibration. We grouped predictions into bins and plotted the predicted risk against the rate that actually happened in held out patients. For highs the points sit on the diagonal: when the twin says thirty percent, it happens about thirty percent of the time. For lows the model is under confident in the middle range. When it says fifteen percent, lows happened about a quarter of the time. That is one more reason a ward should use a lower threshold for lows.
Patient by patient, the median AUROC for highs is {H['per_patient_auroc']['median']:.2f}, with an interquartile range from {H['per_patient_auroc']['q25']:.2f} to {H['per_patient_auroc']['q75']:.2f}, across {H['per_patient_auroc']['n']} patients who had events. It works for most patients, but not equally well for all."""),

    ("slide13", """Now the doctor's view. This is the clinician dashboard. It is a static web page hosted on GitHub Pages, and the link is in our repository. Every number it shows is an out of fold prediction for a held out patient, from the full twin with the record. So this is what the twin would have said in real time, for a patient it had never seen.
The left column is the static stream: the record card, and below it the twin memory. The centre shows the last seventy two hours of the sensor, with the target band shaded, meals as yellow dots and insulin as purple marks. The green dashed line is the twin's forecast for the next two hours from the cursor. Below it is the two hour risk timeline, orange for highs and blue for lows, with the alert threshold as a dashed line. On the right are the current reading, the two risks, the alert, and the reasons.
Let us walk through three moments."""),

    ("dash1", """This patient is on a sulfonylurea, one of the drug classes that cause hypoglycaemia. It is one fifteen in the morning. Glucose is seventy two, still inside the target band, so a nurse glancing at the number would see nothing wrong.
But the twin's blue risk line has been rising since midnight, and now says seventy one percent chance of falling below seventy in the next two hours. Fifteen minutes later, glucose did fall below seventy, and it stayed there for about half an hour.
On the right, under why the twin thinks so, are the top drivers in log odds, computed with tree SHAP on the same held out prediction. Current glucose and the two hour minimum push the risk up most. Next come things the twin has learned about this patient: they spend almost no time above range, and their personal mean glucose is only about one hundred. Time of day, the middle of the night, also adds risk. On the left, the drug list shows the sulfonylurea, so the doctor can see the likely cause next to the alert without opening another system."""),

    ("dash2", """Now we drag the cursor to eight in the morning, in the same patient. Breakfast, cereal and milk, was logged at seven thirty. Glucose is one hundred and twenty four and climbing, and the orange line says fifty five percent chance of rising above one eighty within two hours. The green forecast predicts a peak near one seventy eight, and the real trace peaked at about one fifty. So the risk was real, but the patient stayed just under the line. This is what a borderline alert looks like, and the doctor can see both the risk and the forecast before deciding.
Notice the twin memory panel on the left. The personal post meal rise and the usual meal times are filled in from this patient's own past days. On the first day these show 'learning', because the twin has not seen enough of the patient yet. That is deliberate. The twin should not pretend to know someone it has just met."""),

    ("dash3", """Here is a different patient, on insulin and metformin, with an HbA1c of eight point one percent. Over the past days the twin has learned that this person spends about half of the time above one eighty, and that their glucose rises by about seventy milligrams after a typical meal.
At six in the evening glucose is one thirty one, and the twin gives a fifty percent chance of rising above one eighty. The top drivers are different from the first patient: time of day, which here stands for the hospital dinner schedule, time since the last meal, and the twin's learned mean glucose and time above range. The same model gives different reasons for different people, because the twin state is different. That is what we mean by a personalised twin.
For a diabetes educator, the learned post meal rise is useful by itself. If one person rises seventy milligrams after a typical meal and another rises twenty, the diet conversation should be different."""),

    ("slide14", """This slide summarises what drives the twin across all held out predictions. The numbers are mean absolute SHAP contributions in log odds.
For highs, time of day ranks first. That is because this is a hospital cohort with fixed meal times, so the clock is a strong proxy for the next meal. In outpatients we would expect logged meals to take over that role, and that is something we would test. Then come current glucose, the twin's learned mean glucose, the recent trends, time since the last meal, and the learned post meal rise.
For lows, current glucose comes first, followed by the twin's learned mean glucose and variability, the two hour minimum, and the trends.
We show this table because a black box is not acceptable in a clinic. If a driver ever looks clinically wrong, the doctor can see it and overrule the alert."""),

    ("slide15", """Now the most important slide for a fair evaluation: what this proof of concept does not show yet.
First, it uses one cohort. These are Chinese adults, mostly monitored in hospital. Indian diets, outpatient life, and Indian sensor users need their own validation before anyone should trust these numbers in India.
Second, the memory is short. Each monitoring period is three to fourteen days, so the twin learns habits from at most two weeks.
Third, this dataset has no heart rate, steps or sleep. We designed adapters for those signals, but they are untested, so we make no claims about them.
Fourth, meal size is grams of logged food, not carbohydrate counts.
Fifth, this is retrospective only. There is no prospective or silent mode trial yet, and this is not a medical device.
And sixth, the model learns associations, not causes. The twin warns and explains, but it does not simulate what would happen if you changed a dose. We think it is better to say this clearly than to show a what if slider that looks causal but is not."""),

    ("slide16", """Here is how we would take this to an Indian deployment.
First, wearables. Add heart rate, heart rate variability, steps and sleep from Apple Health or Google Fit as more dynamic features, and measure how much they add, the same way we measured the record.
Second, records. Read the record through FHIR R4 and India's Ayushman Bharat Digital Mission instead of a spreadsheet. The twin does not change; only the input does.
Third, an Indian cohort. Retrain and recalibrate on Indian sensor data, collected with consent under the D P D P Act, and check calibration site by site. A larger cohort is also where we would test again whether the record adds accuracy.
Fourth, a silent trial. Run the twin beside a ward for four weeks without showing alerts, then compare its alerts with what actually happened. That gives the real alert burden and lead time.
And fifth, a mechanistic core. Pair the learned twin with a physiological glucose insulin model, so that what if questions about dose changes become true simulations rather than correlations."""),

    ("slide17", f"""To summarise.
We built a digital twin for type 2 diabetes on real data: {D['patients']} patients, with their health records and fifteen minute glucose sensor data brought together in one twin state that updates every fifteen minutes.
On patients the model never saw, the twin reaches an AUROC of {OPH[PT]['auroc']:.3f} for high excursions and {OPO[PT]['auroc']:.3f} for low excursions two hours ahead, clearly above a trend rule.
We measured what each stream contributes instead of assuming it. The twin's memory of the patient adds accuracy for high excursions. The static record, in this cohort, does not, and we told you why.
We built a clinician dashboard that replays the twin and explains every alert.
And everything is open source under the MIT licence. One command reproduces every number in this video.
The repository and the live dashboard are at github dot com slash c h x m q slash Snack Overflow underscore R V C E.
Thank you for watching. We would be glad to take questions in the jury round."""),
]
