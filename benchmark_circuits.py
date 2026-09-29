"""Synthetic analog-like block graphs. These are not foundry circuit netlists."""
import random

from analog_layout import validate

FAMILIES = ("mirror_bank", "differential_chain", "folded_branches", "bias_fanout")


def make_circuit(family, seed):
    if family not in FAMILIES:
        raise ValueError("Unknown circuit family")
    rng = random.Random(seed)
    pairs = rng.randint(2, 5)
    width, height = rng.choice([48, 56, 64]), 12 * (pairs + 1)
    devices, symmetry = [], []
    for i in range(pairs):
        w, h = rng.randint(3, 6), rng.randint(3, 5)
        x, y = rng.randint(3, 10), 5 + 12 * i
        left, right = f"L{i}", f"R{i}"
        devices.extend([dict(name=left, width=w, height=h, x=x, y=y),
                        dict(name=right, width=w, height=h, x=width-x-w, y=y)])
        symmetry.append([left, right])
    devices.append(dict(name="BIAS", width=6, height=4, x=(width-6)//2, y=5+12*pairs))
    nets = []
    def add(names, weight=1):
        nets.append(dict(name=f"net_{len(nets)}", devices=names, weight=weight))
    if family == "mirror_bank":
        add([d["name"] for d in devices], 2)
        for i in range(pairs):
            add([f"L{i}", f"R{i}"], 1)
    elif family == "differential_chain":
        for i in range(pairs-1):
            for side in "LR":
                add([f"{side}{i}", f"{side}{i+1}"], rng.randint(1, 3))
        add(["L0", "R0", "BIAS"], 2)
        add([f"L{pairs-1}", f"R{pairs-1}"], 1)
    elif family == "folded_branches":
        for i in range(pairs-1):
            add([f"L{i}", f"R{i+1}"], 2)
            add([f"R{i}", f"L{i+1}"], 2)
        add(["L0", "R0", "BIAS"], 1)
    else:
        for i in range(pairs):
            add([f"L{i}", f"R{i}", "BIAS"], rng.randint(1, 3))
    spec = dict(name=f"{family}_{seed}", family=family, synthetic=True,
                boundary=[width, height], spacing=1, devices=devices,
                symmetry_pairs=symmetry, centered=["BIAS"], nets=nets)
    validate(spec)
    return spec
