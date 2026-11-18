# %% configuration
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from qiskit import qpy
from qiskit_ibm_runtime import QiskitRuntimeService, RuntimeEncoder, SamplerV2
from qiskit_ibm_runtime.exceptions import IBMRuntimeError

API_KEY = ""  # Paste your IBM Cloud API key here. Clear it before sharing the notebook.
INSTANCE = ""  # Paste the full IBM Quantum instance CRN here.
BACKEND_NAME = ""  # Enter the IBM backend matching your placement calibration.
SHOTS = 16_384  # Paper setting. None lets IBM Runtime choose the shot count.

RUN_DIR = Path(".")  # Directory containing this notebook and layout.json.
layout = json.loads((RUN_DIR / "layout.json").read_text(encoding="utf-8"))
pages = {p["number"]: p for p in layout["pages"]}
ledger = RUN_DIR / "jobs.csv"
print(f"Compiled at optimization level {layout['optimization_level']} with {layout['routing_method']} routing.")
for number, page in pages.items():
    print(f"Page {number}: {len(page['workloads'])} circuit instance(s)")

def runtime_service():
    if not BACKEND_NAME.strip():
        raise ValueError("Set BACKEND_NAME in the first code cell, then rerun it.")
    if not API_KEY.strip() or not INSTANCE.strip():
        raise ValueError("Fill in API_KEY and INSTANCE in the first code cell, then rerun it.")
    return QiskitRuntimeService(channel="ibm_quantum_platform", token=API_KEY.strip(), instance=INSTANCE.strip())

# %% submit
PAGES_TO_SUBMIT = []  # Set to [1], [1, 2], or list(pages) for all pages.

if PAGES_TO_SUBMIT:
    sampler = SamplerV2(mode=runtime_service().backend(BACKEND_NAME.strip()),
                        options=layout["fixed_sampler_options"])
    for number in PAGES_TO_SUBMIT:
        page = pages[number]
        with (RUN_DIR / page["circuit"]).open("rb") as f:
            joint, = qpy.load(f)
        sampler.options.environment.job_tags = ["sdma", f"page-{number:03}"]
        job = sampler.run([joint], shots=SHOTS)
        row = dict(job_id=job.job_id(), page=number, backend=BACKEND_NAME.strip(), shots=SHOTS,
                   submitted_utc=datetime.now(timezone.utc).isoformat())
        print(f"Page {number}: {row['job_id']}", flush=True)
        with ledger.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row))
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
else:
    print("Choose the page numbers above to submit.")

# %% fetch
FETCH_PAGES = None  # None for all submitted pages, or e.g. [2].
out = RUN_DIR / "fetched_results"
out.mkdir(exist_ok=True)
submitted = []
if ledger.exists():
    with ledger.open(encoding="utf-8", newline="") as f:
        submitted = [row for row in csv.DictReader(f)
                     if FETCH_PAGES is None or int(row["page"]) in FETCH_PAGES]
service = None
for row in submitted:
    number = int(row["page"])
    path = out / f"page_{number:03}_{row['job_id']}.json"
    if path.exists():
        print(f"Already saved: {path}")
        continue
    if service is None:
        service = runtime_service()
    try:
        job = service.job(row["job_id"])
        status = job.status()
        state = getattr(status, "name", str(status)).upper()
        print(f"Page {number}: {row['job_id']} {state}", flush=True)
        if state != "DONE":
            continue
        result = job.result()
    except IBMRuntimeError as exc:
        print(f"Page {number}: {row['job_id']}: {exc}")
        continue
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result, f, cls=RuntimeEncoder)
    tmp.replace(path)
    print(path)
if not submitted:
    print("No matching jobs in jobs.csv.")
