"""Write the vector layout and Execute.ipynb."""
from bisect import bisect_right
from itertools import accumulate
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import LineCollection
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextToPath
import nbformat as nb


PALETTE = ("#0072B2", "#D55E00", "#00866A", "#8845A0", "#9A6710", "#C23C70",
           "#357D95", "#626C27", "#414CA2", "#923831", "#347C44", "#70596D")

# Coordinates and type sizes are in PDF points (72 per inch), measured from the top left.
LETTER = (792, 612)  # US Letter, landscape
LEGEND_X, LEGEND_RIGHT, COLUMN_GAP, ID_WIDTH = 449, 768, 12, 39
COLUMN_STEP = (LEGEND_RIGHT - LEGEND_X + COLUMN_GAP) / 2
LEGEND_TOP, LEGEND_BOTTOM = 104, 566
NAME_SIZE, DETAIL_SIZE = 9, 8


def _legend_sheets(workloads):
    metrics = TextToPath()

    def fit(text, width, size):
        font = FontProperties(family="DejaVu Sans", size=size)
        def measure(s):
            return metrics.get_text_width_height_descent(s, font, False)[0]
        lines = []
        while measure(text) > width:
            n = max(1, bisect_right(range(1, len(text) + 1), width, key=lambda i: measure(text[:i])))
            cut = max((i for i in range(max(1, n // 2), n + 1)
                       if text[i-1] in "_-/ " or text[i:i+1] == "."), default=n)
            lines.append(text[:cut])
            text = text[cut:]
        return lines + [text]

    def entries(column_width):
        width = column_width - ID_WIDTH - 2
        for i, w in enumerate(workloads):
            name = fit(w["circuit"], width, NAME_SIZE)
            detail = fit(f"{len(w['qubits'])} qubits  |  ISA depth {w['isa_depth']}", width, DETAIL_SIZE)
            yield i, name, detail, max(32, 12 * len(name) + 10 * len(detail) + 8)

    height = LEGEND_BOTTOM - LEGEND_TOP
    wide = list(entries(LEGEND_RIGHT - LEGEND_X))
    if sum(r[-1] for r in wide) <= height:
        return [[wide]]

    columns, column, used = [], [], 0
    for row in entries(COLUMN_STEP - COLUMN_GAP):
        if column and used + row[-1] > height:
            columns.append(column)
            column, used = [], 0
        column.append(row)
        used += row[-1]
    columns.append(column)

    # Balance each pair without changing the register order or shrinking the type.
    sheets = []
    for start in range(0, len(columns), 2):
        pair = columns[start:start + 2]
        if len(pair) == 2:
            rows = pair[0] + pair[1]
            ends = list(accumulate(r[-1] for r in rows))
            split = min(range(1, len(rows)), key=lambda n: (abs(2 * ends[n-1] - ends[-1]), -n))
            pair = [rows[:split], rows[split:]]
        sheets.append(pair)
    return sheets


def draw_layouts(layout, graph, pos, path):
    width, height = LETTER
    xs, ys = zip(*pos.values())
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    style = {"pdf.fonttype": 42, "font.family": "DejaVu Sans", "savefig.bbox": None}
    with plt.rc_context(style), PdfPages(path) as pdf:
        for page in layout["pages"]:
            ws = page["workloads"]
            fig = plt.figure(figsize=(width / 72, height / 72), layout="none", facecolor="white")
            def at(x, y, text, **kw):
                return fig.text(x / width, 1 - y / height, text, va="top", **kw)
            at(25, 18, f"Page {page['number']} of {len(layout['pages'])}",
               fontsize=19, weight="bold", color="#17242B")
            used = {q for w in ws for q in w["active_qubits"]}
            noun = "instance" if len(ws) == 1 else "instances"
            at(25, 48, f"{layout['device']}     /     {len(ws)} {noun}     /     "
               f"{len(used)} of {len(pos)} active qubits     /     s = {layout['s']}", fontsize=10)
            ax = fig.add_axes([20 / width, 48 / height, 422 / width, 486 / height])
            segments = [(pos[a], pos[b]) for a, b in graph.edges]
            ax.add_collection(LineCollection(segments, colors="#B6C0C4", linewidths=1, zorder=0))
            owners = {q: i for i, w in enumerate(ws) for q in w["qubits"]}
            for i, w in enumerate(ws):
                color = PALETTE[i % len(PALETTE)]
                internal = [(pos[a], pos[b]) for a, b in graph.subgraph(w["active_qubits"]).edges]
                ax.add_collection(LineCollection(internal, colors=color, linewidths=2.5, zorder=1))
                anchor = min(w["qubits"], key=lambda q: (pos[q][1], pos[q][0]))
                ax.annotate(w["register"], pos[anchor], xytext=(0, 8.1), textcoords="offset points",
                            ha="center", va="bottom", color=color, fontsize=6.2, weight="bold",
                            bbox=dict(facecolor="white", alpha=.9, edgecolor="none", pad=.45), zorder=5)
            for q, (x, y) in pos.items():
                i = owners.get(q)
                color = PALETTE[i % len(PALETTE)] if i is not None else "#A8B2B6"
                ax.scatter(x, y, s=158, facecolor=color if q in used else "white",
                           edgecolor=color, linewidth=.8, zorder=2)
                ax.text(x, y, str(q), ha="center", va="center", fontsize=6.6, zorder=3,
                        color="white" if q in used else "#546169")
            ax.set(xlim=(xmin-.65, xmax+.65), ylim=(ymax+.55, ymin-.85), aspect="equal")
            ax.set_axis_off()
            at(25, 584, f"Calibration: {layout['calibration']}", fontsize=8, color="#45525B")
            at(LEGEND_X, 584, "Filled: active   |   Colored outline: reserved", fontsize=8, color="#45525B")
            sheets = _legend_sheets(ws)
            for n, columns in enumerate(sheets, 1):
                title = "Circuit instances"
                if len(sheets) > 1:
                    title += f"  |  Legend sheet {n} of {len(sheets)}"
                legend = [at(LEGEND_X, 79, title, fontsize=11, weight="bold")]
                for col, rows in enumerate(columns):
                    x, y = LEGEND_X + col * COLUMN_STEP, LEGEND_TOP
                    for i, name, detail, row_height in rows:
                        color = PALETTE[i % len(PALETTE)]
                        legend.append(at(x, y, ws[i]["register"], color=color, fontsize=NAME_SIZE, weight="bold"))
                        for j, line in enumerate(name):
                            legend.append(at(x + ID_WIDTH, y + 12*j, line, fontsize=NAME_SIZE, parse_math=False))
                        for j, line in enumerate(detail):
                            legend.append(at(x + ID_WIDTH, y + 12*len(name) + 10*j, line,
                                             fontsize=DETAIL_SIZE, color="#4D5961"))
                        y += row_height
                pdf.savefig(fig)
                for label in legend:
                    label.remove()
            plt.close(fig)


def write_notebook(path):
    template = Path(__file__).with_name("notebook_cells.py").read_text(encoding="utf-8")
    cells = {}
    for section in template.split("# %% ")[1:]:
        title, code = section.split("\n", 1)
        cells[title] = code.strip()
    md, code = nb.v4.new_markdown_cell, nb.v4.new_code_cell
    doc = nb.v4.new_notebook(cells=[
        md("# Execute | SDMA on IBM Quantum\nEach selected layout page submits one joint job. All instances on a page "
           "share the same shots and have separate classical registers. See the [layout PDF](layout.pdf) for their physical qubits."),
        md("## 1. IBM account and shots\nEnter your IBM API key, instance CRN, backend name, and shot count in the next cell. "
           "Use the backend matching the placement calibration. Saving the notebook saves the key in plain text; "
           "clear it before sharing. This cell shows the layout without connecting to IBM. "
           "To change the compilation or placement settings, rerun the SDMA cell in `Config.ipynb`."),
        code(cells["configuration"]),
        md("## 2. Submit selected pages\nSet the page list below and run once. Re-running it submits new jobs. "
           "Each returned ID is appended to jobs.csv. The default empty list makes Run All safe to use for inspection."),
        code(cells["submit"]),
        md("## 3. Fetch results\nAfter a kernel restart, run **IBM account and shots**, then this cell. "
           "Fetch reads the job IDs in `jobs.csv`. Each completed job is saved in `fetched_results/page_NNN_JOBID.json` "
           "using IBM's `RuntimeEncoder`, including every register's shot samples and the returned metadata. "
           "Rerun Fetch after a pending job finishes. Use `json.load(file, cls=RuntimeDecoder)` with "
           "`RuntimeDecoder` from `qiskit_ibm_runtime` to restore a result."),
        code(cells["fetch"]),
    ], metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})
    nb.write(doc, path)
