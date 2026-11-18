"""Compile on local templates, then move native instructions to physical wires."""
from pathlib import Path

from qiskit import ClassicalRegister, QuantumCircuit, qasm2, qpy, transpile
from qiskit.transpiler import CouplingMap

from .circuits import bit_conditions, isa_depth, leaves
from .geometry import bounds, embeddings


DEFAULT_TRANSPILATION = dict(optimization_level=2, routing_method="sabre", seed_transpiler=20260928)


def read_circuit(path):
    if path.suffix.lower() == ".qpy":
        with path.open("rb") as f:
            circuit, = qpy.load(f)
    elif path.suffix.lower() == ".qasm":
        circuit = qasm2.load(path, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS,
                             include_path=(path.parent, Path.cwd()))
    else:
        raise ValueError(f"Use an OpenQASM 2 .qasm or a single-circuit .qpy file: {path}")
    if not any(op.name == "measure" for op, _ in leaves(circuit)):
        circuit.measure_all()
    return bit_conditions(circuit) if circuit.has_control_flow_op() else circuit


def compile_shape(circuit, template, graph, transpilation):
    local = {q: i for i, q in enumerate(template)}
    coupling = CouplingMap()
    for i in range(len(template)):
        coupling.add_physical_qubit(i)
    for a, b in graph.subgraph(template).edges:
        coupling.add_edge(local[a], local[b])
        coupling.add_edge(local[b], local[a])
    isa = transpile(circuit, basis_gates=["cz", "rz", "sx", "x"], coupling_map=coupling,
                    initial_layout=list(range(len(template))), layout_method="trivial",
                    **transpilation)
    return bit_conditions(isa) if isa.has_control_flow_op() else isa


def placement_options(circuit, templates, graph, pos, calibration, usable, transpilation):
    best, circuits = {}, []
    for variant, template in enumerate(templates):
        isa = compile_shape(circuit, template, graph, transpilation)
        circuits.append(isa)
        instructions = [(op.name, qs) for op, qs in leaves(isa)]
        indices = {key: i for i, key in enumerate(dict.fromkeys(instructions))}
        active = sorted({q for op, qs in indices if op not in ("barrier", "delay") for q in qs})
        mappings = [m for m in embeddings(template, graph, pos) if usable.issuperset(m)
                    and all(calibration.admitted(op, tuple(m[q] for q in qs)) for op, qs in indices)]
        if not mappings:
            continue
        depth = isa_depth(isa)
        costs = calibration.costs(list(indices), [indices[key] for key in instructions], mappings)
        for m, cost in zip(mappings, costs):
            box = bounds(m, pos)
            key = (depth, tuple(box))
            if key not in best or (cost, m) < (best[key]["hardware_cost"], best[key]["qubits"]):
                best[key] = dict(variant=variant, depth=depth, bounds=box, qubits=m,
                                 active_qubits=[m[q] for q in active], hardware_cost=float(cost))
    return circuits, sorted(best.values(), key=lambda r: (r["hardware_cost"], r["depth"], r["qubits"]))


def joint_circuit(page, native, device_width, page_number):
    joint = QuantumCircuit(device_width, name=f"sdma_page_{page_number:03}")
    for w in page:
        isa = native[w["algorithm"]][w["variant"]]
        result = ClassicalRegister(isa.num_clbits, w["name"])
        joint.add_register(result)
        joint.compose(isa, qubits=w["qubits"], clbits=list(result), inplace=True)
    return joint
