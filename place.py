"""Local SDMA placement for Config.ipynb and the command line."""
import argparse
import csv
from datetime import datetime
from fractions import Fraction
import json
import os
from pathlib import Path
import sys

import networkx as nx
from qiskit import qpy

from sdma.calibration import Calibration
from sdma.compiler import DEFAULT_TRANSPILATION, joint_circuit, placement_options, read_circuit
from sdma.geometry import templates_for
from sdma.outputs import draw_layouts, write_notebook
from sdma.packing import Planner


ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "Example"
INPUT_CIRCUITS = ROOT / "circuits"
CALIBRATION = EXAMPLE / "ibm_kingston_calibrations_2026-11-13T14_57_10Z.csv"
TOPOLOGY = ROOT / "sdma" / "heron_r2.json"


def read_policy(path):
    policy = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip()[:1].isdigit():
                continue
            span, h, v = row[:3]
            ends = [int(n) for n in span.replace("\u2013", "-").replace("--", "-").split("-")]
            policy.update((k, (int(h), int(v))) for k in range(ends[0], ends[-1] + 1))
    if not policy:
        raise ValueError("Policy CSV needs data rows such as 2-3,3,3.")
    return policy


def path_prompt(label, default):
    value = input(f"{label} [{default}]: ").strip().strip('"')
    return Path(value) if value else default


def allocate(*, calibration=CALIBRATION, policy=EXAMPLE / "policy.csv",
             workload=EXAMPLE / "workload.csv", circuits=INPUT_CIRCUITS,
             output=EXAMPLE / "output", topology=TOPOLOGY, s=0.5, seed=42,
             optimization_level=DEFAULT_TRANSPILATION["optimization_level"],
             routing_method=DEFAULT_TRANSPILATION["routing_method"],
             seed_transpiler=DEFAULT_TRANSPILATION["seed_transpiler"],
             init_qubits=None, rep_delay_seconds=None, max_execution_time_seconds=None, circuit=None):
    """Compile and pack the requested instances; return the generated run directory."""
    transpilation = dict(optimization_level=optimization_level, routing_method=routing_method,
                         seed_transpiler=seed_transpiler)
    csv_path, folder = Path(calibration), Path(circuits)
    s = Fraction(str(s))
    if circuit is None:
        with Path(workload).open(encoding="utf-8-sig", newline="") as f:
            specs = [(r["path"], int(r["times"])) for r in csv.DictReader(f)]
    else:
        specs = [(name, int(n)) for name, n in circuit]
    if not specs or not 0 <= s <= 1 or any(n < 1 for _, n in specs):
        raise ValueError("Supply at least one circuit, a positive copy count and s between 0 and 1.")
    policy = read_policy(Path(policy))
    topo = json.loads(Path(topology).read_text(encoding="utf-8"))
    pos = {int(q): tuple(xy) for q, xy in topo["positions"].items()}
    graph = nx.Graph()
    graph.add_nodes_from(pos)
    graph.add_edges_from(topo["edges"])
    cal = Calibration(csv_path)
    usable = set(pos) & cal.usable
    shape_cache, native, candidates, requests = {}, {}, {}, []
    for name, times in specs:
        if name not in candidates:
            program = read_circuit(folder / name)
            width = program.num_qubits
            if width not in shape_cache:
                shape_cache[width] = templates_for(width, graph, pos)
            native[name], candidates[name] = placement_options(
                program, shape_cache[width], graph, pos, cal, usable, transpilation)
            if not candidates[name]:
                raise ValueError(f"{name}: no calibrated mapping on the supplied topology.")
        width = native[name][0].num_qubits
        for _ in range(times):
            requests.append(dict(name=f"w{len(requests)+1:04}", algorithm=name, width=width))
    pages = Planner(candidates, policy, s, seed, len(usable)).pack(requests)
    dest = Path(output).resolve()
    label = dest.parent.name if dest.name == "output" else dest.name
    compiled = ROOT / "compiled_circuits" / (label or "run")
    if any(p.is_dir() and any(p.iterdir()) for p in (dest, compiled)):
        run = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        dest, compiled = dest / run, compiled / run
    dest.mkdir(parents=True, exist_ok=True)
    compiled.mkdir(parents=True, exist_ok=True)
    try:
        circuit_dir = Path(os.path.relpath(compiled, dest))
    except ValueError:  # Windows output on a different drive.
        circuit_dir = compiled
    options = {"dynamical_decoupling": {"enable": False},
               "twirling": {"enable_gates": False, "enable_measure": False}}
    execution = {k: v for k, v in (("init_qubits", init_qubits), ("rep_delay", rep_delay_seconds)) if v is not None}
    if execution:
        options["execution"] = execution
    if max_execution_time_seconds is not None:
        options["max_execution_time"] = max_execution_time_seconds
    manifest = dict(device=topo.get("name", "IBM QPU"), calibration=csv_path.name,
                    policy={str(k): list(v) for k, v in policy.items()}, s=str(float(s)),
                    seed=seed, **transpilation, fixed_sampler_options=options, pages=[])
    for number, page in enumerate(pages, 1):
        file = f"page_{number:03}.qpy"
        with (compiled / file).open("wb") as f:
            qpy.dump(joint_circuit(page, native, max(pos) + 1, number), f)
        manifest["pages"].append(dict(number=number, circuit=(circuit_dir / file).as_posix(), workloads=[
            dict(register=w["name"], circuit=Path(w["algorithm"]).name, qubits=w["qubits"],
                 active_qubits=w["active_qubits"], isa_depth=w["depth"],
                 classical_bits=native[w["algorithm"]][w["variant"]].num_clbits) for w in page]))
    (dest / "layout.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    draw_layouts(manifest, graph, pos, dest / "layout.pdf")
    write_notebook(dest / "Execute.ipynb")
    (dest / "fetched_results").mkdir(exist_ok=True)
    print(f"{len(requests)} circuit instances on {len(pages)} page{'s' if len(pages) != 1 else ''}")
    print(dest / "layout.pdf")
    print(dest / "Execute.ipynb")
    return dest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibration", type=Path, default=CALIBRATION)
    p.add_argument("--policy", type=Path, default=EXAMPLE / "policy.csv")
    p.add_argument("--s", "--separate-value", default="0.5", help="Depth rounding threshold")
    p.add_argument("--circuits", type=Path, default=INPUT_CIRCUITS, help="Folder containing the input circuits")
    work = p.add_mutually_exclusive_group()
    work.add_argument("--workload", type=Path, default=EXAMPLE / "workload.csv", help="CSV with path,times columns")
    work.add_argument("--circuit", nargs=2, action="append", metavar=("PATH", "TIMES"))
    p.add_argument("--topology", type=Path, default=TOPOLOGY)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--optimization-level", type=int, choices=range(4), default=DEFAULT_TRANSPILATION["optimization_level"],
                   help="Qiskit transpiler optimization level before SDMA placement (default: 2)")
    p.add_argument("--routing-method", choices=("sabre", "basic", "lookahead"), default=DEFAULT_TRANSPILATION["routing_method"],
                   help="Route inside each candidate template (default: sabre)")
    p.add_argument("--seed-transpiler", type=int, default=DEFAULT_TRANSPILATION["seed_transpiler"],
                   help="Qiskit transpiler seed, separate from the packing seed (default: 20260928)")
    p.add_argument("--output", type=Path, default=EXAMPLE / "output", help="Run directory (default: Example/output)")
    args = p.parse_args()
    if len(sys.argv) == 1:
        value = input(f"Transpiler optimization level, 0-3 [{args.optimization_level}]: ").strip()
        if value:
            if value not in ("0", "1", "2", "3"):
                p.error("Optimization level must be 0, 1, 2, or 3.")
            args.optimization_level = int(value)
        args.calibration = path_prompt("IBM calibration CSV", args.calibration)
        args.policy = path_prompt("Separation policy CSV", args.policy)
        args.s = input("Rounding threshold s [0.5]: ").strip() or args.s
        args.circuits = path_prompt("Circuit folder", args.circuits)
        args.workload = path_prompt("Workload CSV", args.workload)
    allocate(**vars(args))
