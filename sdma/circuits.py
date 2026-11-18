"""Local ISA depth, classical conditions and instruction traversal."""
from qiskit.circuit import Clbit, ClassicalRegister, IfElseOp
from qiskit.circuit.classical import expr
from qiskit.converters import circuit_to_dag


def isa_depth(qc):
    if not qc.has_control_flow_op():
        return qc.depth()
    # Match QuantumCircuit.depth's zero-weight directives, while expanding
    # conditional blocks. DAG.depth(recurse=True) counts barriers and would
    # otherwise change the depth of static workloads merely by composition.
    dag = circuit_to_dag(qc)
    ends = {}
    for node in dag.topological_op_nodes():
        start = max((ends.get(parent._node_id, 0) for parent in dag.predecessors(node)), default=0)
        blocks = getattr(node.op, "blocks", ())
        weight = (max(isa_depth(block) for block in blocks) if blocks else
                  0 if getattr(node.op, "_directive", False) else 1)
        ends[node._node_id] = start + weight
    return max(ends.values(), default=0)


def bit_conditions(qc):
    """Replace register predicates by equivalent bit predicates, not by gates.

    This avoids overlapping alias registers when multiple dynamic workloads are
    composed into independently named result registers.
    """
    out = qc.copy_empty_like()
    for instruction in qc.data:
        op = instruction.operation
        if op.name == "if_else":
            condition = op.condition
            if isinstance(condition, tuple):
                operand, value = condition
                if isinstance(operand, ClassicalRegister):
                    condition = expr.lift(True)
                    for index, bit in enumerate(operand):
                        condition = expr.logic_and(
                            condition, expr.equal(bit, bool((value >> index) & 1)))
                elif isinstance(operand, Clbit):
                    condition = expr.equal(operand, bool(value))
                else:
                    raise ValueError(f"Unsupported condition operand {operand}")
            blocks = [bit_conditions(block) for block in op.blocks]
            op = IfElseOp(condition, blocks[0], blocks[1] if len(blocks) == 2 else None,
                          label=op.label)
        elif hasattr(op, "blocks"):
            raise ValueError(f"Unsupported control-flow operation: {op.name}")
        out.append(op, instruction.qubits, instruction.clbits)
    return out


def leaves(qc, mapping=None):
    mapping = list(range(qc.num_qubits)) if mapping is None else list(mapping)
    for instruction in qc.data:
        op = instruction.operation
        physical = tuple(mapping[qc.find_bit(q).index] for q in instruction.qubits)
        if hasattr(op, "blocks"):
            for block in op.blocks:
                yield from leaves(block, physical)
        else:
            yield op, physical
