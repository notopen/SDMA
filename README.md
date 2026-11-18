# 2427	Depth-Aware Circuit Scheduling for Quantum Virtual Machines

SDMA takes IBM calibration data and a list of circuit instances and assigns them to QPU pages. A page is one physical circuit: its workloads run on disjoint qubits and each workload writes to its own result register.

## Start here

Tested with Python 3.13. From this directory, install the dependencies in a virtual environment:

```console
python -m pip install -r requirements.txt
```

Launch Jupyter from the artifact root:

```console
jupyter notebook Config.ipynb
```

1. Open [Config.ipynb](Config.ipynb). Select the calibration, policy and workload CSVs in the first code cell, or use the example paths. Set the rounding threshold and compiler options here.
2. Run **Run SDMA**. This local step produces a PDF, one compiled joint circuit per page, and an execution notebook. The cell links to the files it just generated. On a rerun, the new files go in a timestamped subfolder under the selected output folder; earlier notebooks, job IDs and results stay intact.
3. Open the generated **Execute.ipynb** when you want to submit. Supply your own IBM credentials, backend and shot count in its first code cell. Submit and Fetch are separate manual steps.

## Example

[circuits/](circuits/) contains the paper's 36 QASMBench benchmarks plus `cat_state_n22` and `ghz_state_n23`. 

The [example workload](Example/workload.csv) lists 19 circuits. Each was assigned one to four copies in a one-time random draw, for **52 circuit instances**. Config reads the saved counts without resampling. To run your own workload, list its filenames and copy counts in a `path,times` CSV and set `WORKLOAD_CSV` to that file.

Running [Config.ipynb](Config.ipynb) with the supplied Kingston calibration, `s=0.5` and optimization level `2` produced the [layout PDF](Example/output/layout.pdf) and [Execute notebook](Example/output/Execute.ipynb). The placement program printed:

```text
52 circuit instances on 5 pages
Instances per page: 5, 3, 11, 20, 13
```

## Inputs

| Input | Format |
| --- | --- |
| Calibration | IBM's per-qubit CSV export. The example uses the 2026-11-13 14:57:10 UTC Kingston snapshot. Gate errors are probabilities; gate and readout durations are in ns and coherence times are in us. Missing values are not filled from another snapshot. The calibration data can be download from https://quantum.cloud.ibm.com/computers |
| Separation policy | CSV, first three columns: depth bin, minimum horizontal gap and minimum vertical gap, in grid pitches. A bin can be an integer or a range such as `2-3`. An absent bin means the pair cannot share a page. See [policy.csv](Example/policy.csv). |
| Rounding threshold | `SEPARATE_VALUE` in [0, 1]. For routed depths with ratio `r = max(depths) / min(depths)`, the bin is `floor(r + 1 - s)`. At `s=0.5`, exactly 1.5 enters bin 2; exactly 6.5 falls outside the supplied table. |
| Circuits | A folder of OpenQASM 2 (`.qasm`) or single-circuit Qiskit (`.qpy`) files with bound parameters. The workload CSV lists `path,times`; paths are relative to `CIRCUIT_DIR` and times is a positive copy count. |
| Device | The supplied coordinate map is the 156-qubit Heron r2 layout. For another compatible CZ-based device, set `TOPOLOGY` to a JSON with its physical-qubit `positions` (integer x,y grid) and `edges`, and use its calibration CSV. Changing only the backend in Execute leaves the physical mapping unchanged. |

## Placement

Set `OPTIMIZATION_LEVEL` (0 through 3, default **2**), `ROUTING_METHOD` (default `sabre`) and `TRANSPILER_SEED` (default `20260928`) in Config. `PLACEMENT_SEED` (default `42`) controls the order in which the packer tries the supplied instances. Rerun the SDMA cell after a change: it recompiles the inputs before packing and generating the PDF and Execute notebook. Experiments with different settings can share the same workload CSV. If needed, set `INIT_QUBITS`, `REP_DELAY_SECONDS`, or `MAX_EXECUTION_TIME_SECONDS` in Config; `None` leaves the corresponding IBM Runtime default unset. Dynamical decoupling and twirling are fixed off.

For each width SDMA considers up to two compact connected templates, then enumerates translations, rotations and reflections that preserve their couplings. SDMA admits placements using the error limits: SX/X at most 0.01, CZ at most 0.05, and readout/reset at most 0.10; virtual RZ has zero error. It scores admitted placements using gate/readout errors and idle time relative to coherence.

## Submit and fetch

1. In **Execute.ipynb**, enter your IBM credentials in `API_KEY` and `INSTANCE` (the full CRN). Set the blank `BACKEND_NAME` to the QPU matching your placement calibration before Submit or Fetch. The shot count defaults to 16,384. Clear the key before sharing a saved notebook.
2. In **Submit**, set `PAGES_TO_SUBMIT` to the page numbers to run. The default empty list submits nothing; `list(pages)` submits all pages. Each selected page produces one joint job, including single-instance pages. Its ID is appended to `jobs.csv`. Submitting a page again creates another billable job.
3. Run **Fetch** when ready. If you restart the Juypter, run the account cell and then Fetch with the same account and instance. It lists pending jobs and writes each completed job's full `job.result()` to `fetched_results/page_NNN_JOBID.json` using IBM's `RuntimeEncoder`. This keeps the shot samples for all registers and the metadata returned by IBM. Fetch skips the download if a result file already exists for the same job ID. Submitting the same page again creates a new job ID, so both results are kept. For example, two completed runs of Page 1 with IDs `JOB_A` and `JOB_B` are saved as `page_001_JOB_A.json` and `page_001_JOB_B.json`. The layout manifest maps each register to its source circuit.

To reopen a file, use `json.load(file, cls=RuntimeDecoder)` with `RuntimeDecoder` from `qiskit_ibm_runtime`, as in [IBM's guide to saving and retrieving results](https://quantum.cloud.ibm.com/docs/en/ibm-quantum-compute/save-jobs). When moving the artifact, keep [Example/](Example/) and [compiled_circuits/](compiled_circuits/) under the same root.
