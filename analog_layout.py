"""Toy block placement with hard geometry constraints and a learned move policy.

Coordinates are abstract grid units; net terminals are device centers.
This is a research baseline, not transistor geometry or a DRC/LVS tool.
"""
import argparse
import copy
import json
import math
import random
from pathlib import Path
from xml.sax.saxutils import escape


def validate(spec):
    width, height = spec["boundary"]
    if not all(isinstance(v, int) and v > 0 for v in (width, height)):
        raise ValueError("Boundary must contain two positive integers")
    if not isinstance(spec["spacing"], int) or spec["spacing"] < 0:
        raise ValueError("Spacing must be a nonnegative integer")
    devices = spec["devices"]
    names = [d["name"] for d in devices]
    if not names or len(names) != len(set(names)):
        raise ValueError("Device names must be nonempty and unique")
    for d in devices:
        if not isinstance(d["name"], str) or not d["name"]:
            raise ValueError("Device names must be nonempty strings")
        if any(not isinstance(d[k], int) for k in ("x", "y", "width", "height")):
            raise ValueError("Device geometry must use integer grid units")
        if d["width"] <= 0 or d["height"] <= 0:
            raise ValueError("Device dimensions must be positive")
    assigned = set()
    by_name = {d["name"]: d for d in devices}
    for pair in spec.get("symmetry_pairs", []):
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError("Each symmetry pair must contain two distinct devices")
        for name in pair:
            if name not in by_name or name in assigned:
                raise ValueError("Symmetry groups must reference unique existing devices")
            assigned.add(name)
        a, b = (by_name[n] for n in pair)
        if (a["width"], a["height"]) != (b["width"], b["height"]):
            raise ValueError("Mirrored devices must have identical dimensions")
    for name in spec.get("centered", []):
        if name not in by_name or name in assigned:
            raise ValueError("Centered devices must be unique and outside symmetry pairs")
        assigned.add(name)
    for net in spec["nets"]:
        if not net["devices"] or any(n not in by_name for n in net["devices"]):
            raise ValueError("Nets must reference existing devices")
        weight = net.get("weight", 1)
        if not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError("Net weights must be finite and positive")
    problems = violations(spec, devices)
    if problems:
        raise ValueError("Initial placement is invalid: " + "; ".join(problems))


def violations(spec, devices):
    problems = []
    width, height = spec["boundary"]
    spacing = spec["spacing"]
    by_name = {d["name"]: d for d in devices}
    for i, a in enumerate(devices):
        if a["x"] < 0 or a["y"] < 0 or a["x"] + a["width"] > width or a["y"] + a["height"] > height:
            problems.append("outside boundary: " + a["name"])
        for b in devices[i + 1:]:
            separated = (a["x"] + a["width"] + spacing <= b["x"] or
                         b["x"] + b["width"] + spacing <= a["x"] or
                         a["y"] + a["height"] + spacing <= b["y"] or
                         b["y"] + b["height"] + spacing <= a["y"])
            if not separated:
                problems.append("overlap/spacing: " + a["name"] + "/" + b["name"])
    for left, right in spec.get("symmetry_pairs", []):
        a, b = by_name[left], by_name[right]
        if a["y"] != b["y"] or a["x"] + a["width"] + b["x"] != width:
            problems.append("broken symmetry: " + left + "/" + right)
    for name in spec.get("centered", []):
        d = by_name[name]
        if 2 * d["x"] + d["width"] != width:
            problems.append("not centered: " + name)
    return problems


def wire_cost(spec, devices):
    centers = {d["name"]: (d["x"] + d["width"] / 2, d["y"] + d["height"] / 2) for d in devices}
    cost = 0.0
    for net in spec["nets"]:
        points = [centers[n] for n in net["devices"]]
        cost += net.get("weight", 1) * sum(max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1))
    return cost


def optimize(spec, steps=10000, seed=0, policy="adaptive", learned_policy=None, observations=None):
    """Annealing with epsilon-greedy learning of useful move step sizes."""
    validate(spec)
    if steps <= 0 or policy not in ("adaptive", "uniform", "learned"):
        raise ValueError("Positive steps and adaptive/uniform/learned policy required")
    if policy == "learned" and learned_policy is None:
        raise ValueError("The learned policy requires a trained model")
    rng = random.Random(seed)
    current = copy.deepcopy(spec["devices"])
    best = copy.deepcopy(current)
    initial = current_cost = best_cost = wire_cost(spec, current)
    index = {d["name"]: i for i, d in enumerate(current)}
    groups = [list(pair) for pair in spec.get("symmetry_pairs", [])]
    used = {n for g in groups for n in g}
    groups += [[n] for n in index if n not in used]
    centered = set(spec.get("centered", []))
    sizes = [1, 2, 4, 8]
    values, counts = [0.0] * 4, [0] * 4
    accepted = legal = 0
    history = [{"step": 0, "best_cost": best_cost}]
    for step in range(steps):
        if policy == "learned":
            if step % 64 == 0:
                predicted = learned_policy.predict(spec, current_cost, step / steps)
            if rng.random() < 0.2:
                action = rng.randrange(len(sizes))
            else:
                maximum = max(predicted)
                action = rng.choice([i for i, v in enumerate(predicted) if v == maximum])
        elif policy == "uniform" or rng.random() < 0.2:
            action = rng.randrange(len(sizes))
        else:
            maximum = max(values)
            action = rng.choice([i for i, v in enumerate(values) if v == maximum])
        candidate = copy.deepcopy(current)
        group = rng.choice(groups)
        dx, dy = rng.choice([(sizes[action], 0), (-sizes[action], 0), (0, sizes[action]), (0, -sizes[action])])
        if len(group) == 1 and group[0] in centered:
            dx, dy = 0, rng.choice([-sizes[action], sizes[action]])
        a = candidate[index[group[0]]]
        a["x"] += dx
        a["y"] += dy
        if len(group) == 2:
            b = candidate[index[group[1]]]
            b["x"] = spec["boundary"][0] - a["x"] - a["width"]
            b["y"] = a["y"]
        reward = 0.0
        before_cost = current_cost
        if not violations(spec, candidate):
            legal += 1
            cost = wire_cost(spec, candidate)
            reward = max(0.0, current_cost - cost)
            temperature = max(0.01, max(initial * 0.05, 1) * (1 - step / steps) ** 2)
            if cost <= current_cost or rng.random() < math.exp((current_cost - cost) / temperature):
                current, current_cost = candidate, cost
                accepted += 1
                if cost < best_cost:
                    best, best_cost = copy.deepcopy(candidate), cost
        counts[action] += 1
        values[action] += 0.1 * (reward - values[action])
        if observations is not None:
            observations.append((before_cost, step / steps, action, reward))
        if (step + 1) % max(1, steps // 100) == 0:
            history.append({"step": step + 1, "best_cost": best_cost})
    return {"devices": best, "initial_cost": initial, "best_cost": best_cost,
            "improvement_percent": 100 * (initial - best_cost) / initial if initial else 0,
            "violations": violations(spec, best), "seed": seed, "steps": steps,
            "policy": policy, "legal_proposals": legal, "accepted_moves": accepted,
            "move_sizes": sizes, "action_counts": counts, "learned_rewards": values,
            "history": history}


def write_svg(spec, devices, path):
    width, height = spec["boundary"]
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 {width+4} {height+4}">',
            '<rect x="-2" y="-2" width="100%" height="100%" fill="white"/>',
            f'<rect width="{width}" height="{height}" fill="none" stroke="#555" stroke-width="0.15"/>',
            f'<path d="M {width/2} 0 V {height}" stroke="#999" stroke-width="0.1" stroke-dasharray="0.5 0.5"/>']
    for d in devices:
        body += [f'<rect x="{d["x"]}" y="{height-d["y"]-d["height"]}" width="{d["width"]}" height="{d["height"]}" fill="#c9e3ff" stroke="#245" stroke-width="0.15"/>',
                 f'<text x="{d["x"]+d["width"]/2}" y="{height-d["y"]-d["height"]/2}" text-anchor="middle" dominant-baseline="middle" font-size="1">{escape(d["name"])}</text>']
    path.write_text("\n".join(body + ["</svg>"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("examples/differential_pair.json"))
    parser.add_argument("--output", type=Path, default=Path("results/demo"))
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", choices=["adaptive", "uniform", "learned"], default="adaptive")
    parser.add_argument("--model", type=Path, help="Frozen move_policy.json for learned policy")
    args = parser.parse_args()
    spec = json.loads(args.input.read_text())
    model = None
    if args.policy == "learned":
        if args.model is None:
            parser.error("--policy learned requires --model")
        from placement_learning import MovePolicy
        model = MovePolicy.load(args.model)
    result = optimize(spec, args.steps, args.seed, args.policy, learned_policy=model)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    placement = copy.deepcopy(spec)
    placement["devices"] = result["devices"]
    (args.output / "placement.json").write_text(json.dumps(placement, indent=2) + "\n")
    write_svg(spec, spec["devices"], args.output / "initial.svg")
    write_svg(spec, result["devices"], args.output / "optimized.svg")
    print(json.dumps({k: result[k] for k in ("initial_cost", "best_cost", "improvement_percent", "violations", "policy", "seed")}, indent=2), flush=True)
    print(f"Artifacts: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
