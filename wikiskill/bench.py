"""Demo benchmark generator: deterministic, offline, auto-graded tasks.

Task families target classic agent failure modes (not reading the spec,
hardcoding, naive parsing, no verification), so genuine reusable skills can
emerge from evolution. Every task's deliverable is a file, so grading is
unambiguous.
"""

from __future__ import annotations

import json
import random


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace(",", "").replace("'", "")


def spec_tasks(rng: random.Random) -> list[dict]:
    out = []

    # --- Format 1: NAME|QTY|STATUS, sorted by name, qty >= threshold
    for i, (split, thresh) in enumerate([("train", 10), ("val", 15)], start=1):
        products = [{"name": rng.choice(["alpha", "bravo", "charlie", "delta",
                                         "echo", "foxtrot", "golf", "hotel"]),
                     "qty": rng.randint(0, 40),
                     "status": rng.choice(["active", "sold", "pending"])}
                    for _ in range(8)]
        kept = sorted((p for p in products if p["qty"] >= thresh),
                      key=lambda p: p["name"].lower())
        expected = "\n".join(f"{p['name']}|{p['qty']}|{p['status']}" for p in kept)
        spec = (
            f"# Output specification\n"
            f"Write the deliverable to `output.txt` with EXACTLY this format:\n"
            f"- one line per product whose quantity is >= {thresh}\n"
            f"- lines sorted alphabetically by product name (case-insensitive)\n"
            f"- each line: NAME|QTY|STATUS (pipe-separated, no spaces around `|`)\n"
            f"- no header line, no footer, no trailing blank lines\n\n"
            f"Product data is in `products.json` (list of {{name, qty, status}}).\n"
        )
        out.append({
            "id": f"spec-format1-{i}", "split": split,
            "title": "Format products according to spec",
            "prompt": ("Read `spec.md` and `products.json` in the current directory. "
                       "Follow `spec.md` exactly and produce `output.txt`."),
            "sandbox": {"spec.md": spec,
                        "products.json": json.dumps(products, indent=2)},
            "grader": {"type": "exact", "file": "output.txt", "expected": expected},
        })

    # --- Format 2: semicolon-separated, UPPERCASE names, header row, qty > 0
    for i, (split, unused) in enumerate([("train", 0), ("train", 0)], start=1):
        products = [{"name": rng.choice(["apple", "banana", "cherry", "date",
                                         "elderberry", "fig"]),
                     "qty": rng.randint(0, 25)} for _ in range(7)]
        kept = sorted((p for p in products if p["qty"] > 0), key=lambda p: p["name"])
        lines = ["NAME;QUANTITY"] + [f"{p['name'].upper()};{p['qty']}" for p in kept]
        expected = "\n".join(lines)
        spec = (
            "# Output specification\n"
            "Write the deliverable to `output.txt`:\n"
            "- header line: NAME;QUANTITY\n"
            "- one line per product with quantity > 0, sorted by name (case-insensitive)\n"
            "- product names UPPERCASE, quantity as integer\n"
            "- semicolon separator, no spaces\n"
            "- no trailing blank lines\n\n"
            "Data: `products.json` (list of {name, qty}).\n"
        )
        out.append({
            "id": f"spec-format2-{i}", "split": split,
            "title": "Produce semicolon report with header",
            "prompt": ("Read `spec.md` and `products.json` in the current directory. "
                       "Follow `spec.md` exactly and produce `output.txt`."),
            "sandbox": {"spec.md": spec,
                        "products.json": json.dumps(products, indent=2)},
            "grader": {"type": "exact", "file": "output.txt", "expected": expected},
        })

    # --- Format 3: only status==active, sorted by qty descending, pipe format
    for i, (split, status) in enumerate([("train", "active"), ("val", "active")], start=1):
        items = [{"name": rng.choice(["red", "green", "blue", "yellow", "purple",
                                      "orange", "cyan", "magenta"]),
                  "qty": rng.randint(0, 60),
                  "status": rng.choice(["active", "archived"])} for _ in range(9)]
        kept = sorted((p for p in items if p["status"] == status),
                      key=lambda p: p["qty"], reverse=True)
        expected = "\n".join(f"{p['name']}|{p['qty']}" for p in kept)
        spec = (
            "# Output specification\n"
            "Write the deliverable to `output.txt`:\n"
            f"- only products with status == '{status}'\n"
            "- sorted by quantity DESCENDING (highest first)\n"
            "- each line: NAME|QTY (pipe-separated, no spaces)\n"
            "- no header, no trailing blank lines\n\n"
            "Data: `items.json` (list of {name, qty, status}).\n"
        )
        out.append({
            "id": f"spec-format3-{i}", "split": split,
            "title": "Filter and sort items by spec",
            "prompt": ("Read `spec.md` and `items.json` in the current directory. "
                       "Follow `spec.md` exactly and produce `output.txt`."),
            "sandbox": {"spec.md": spec,
                        "items.json": json.dumps(items, indent=2)},
            "grader": {"type": "exact", "file": "output.txt", "expected": expected},
        })
    return out


def extract_tasks(rng: random.Random) -> list[dict]:
    out = []

    # --- ERROR log lines → timestamps + messages, sorted ascending
    entries = []
    for _ in range(12):
        ts = f"2026-08-{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"
        lvl = rng.choice(["INFO", "ERROR", "WARN", "ERROR", "DEBUG"])
        msg = rng.choice(["timeout", "null pointer", "connection reset",
                          "cache miss", "retry budget exhausted"])
        entries.append((ts, lvl, msg))
    lines = [f"{ts} {lvl} {msg}" for ts, lvl, msg in entries]
    errors = sorted([(ts, msg) for ts, lvl, msg in entries if lvl == "ERROR"])
    expected = "\n".join(f"{ts} {msg}" for ts, msg in errors)
    out.append({
        "id": "extract-errors", "split": "train",
        "title": "Extract ERROR lines with timestamps",
        "prompt": ("`app.log` contains lines `TIMESTAMP LEVEL MESSAGE`. Write to "
                   "`output.txt` only the lines with LEVEL == ERROR, formatted as "
                   "`TIMESTAMP MESSAGE`, sorted by timestamp ascending. One per line."),
        "sandbox": {"app.log": "\n".join(lines) + "\n"},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })

    # --- unique IPs from access log, sorted
    ips = [f"{rng.randint(10, 250)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
           for _ in range(15)]
    log = "\n".join(f"{ip} GET /page/{rng.randint(1, 99)} 200" for ip in ips) + "\n"
    expected = "\n".join(sorted(set(ips)))
    out.append({
        "id": "extract-ips", "split": "train",
        "title": "Extract unique IPs from access log",
        "prompt": ("`access.log` contains lines `IP METHOD PATH STATUS`. Write to "
                   "`output.txt` the UNIQUE source IPs, sorted ascending, one per line. "
                   "No duplicates."),
        "sandbox": {"access.log": log},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })

    # --- TODO lines: strip prefix up to first '|', alphabetize
    todos = [f"2026-08-{rng.randint(1, 28):02d} | {rng.choice(['fix leak', 'add tests', 'refactor module', 'update docs', 'remove dead code', 'bump version'])}"
             for _ in range(9)]
    kept = sorted(set(t.split(" | ", 1)[1] for t in todos))
    expected = "\n".join(kept)
    out.append({
        "id": "extract-todos", "split": "train",
        "title": "Extract TODO items from task log",
        "prompt": ("`tasks.log` contains lines `DATE | ITEM`. Write to `output.txt` only "
                   "the ITEM parts (everything after the first ` | `), unique and sorted "
                   "alphabetically, one per line."),
        "sandbox": {"tasks.log": "\n".join(todos) + "\n"},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })

    # --- longest word
    words = rng.choice([
        "serendipity", "algorithm", "data", "synergy", "cat", "antidisestablishmentarianism",
        "quantum", "kaleidoscope", "run", "paradigm", "floccinaucinihilipilification",
    ]) + " " + " ".join(
        rng.choice(["the", "of", "and", "to", "in", "for", "with", "code", "fast"])
        for _ in range(30))
    longest = max(words.split(), key=len)
    expected = f"{longest}:{len(longest)}"
    out.append({
        "id": "extract-longest", "split": "val",
        "title": "Find the longest word",
        "prompt": ("`words.txt` contains whitespace-separated words. Write to "
                   "`output.txt` the longest word and its length as `WORD:LENGTH` "
                   "(if tied, the first occurrence)."),
        "sandbox": {"words.txt": words + "\n"},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })
    return out


def code_tasks(rng: random.Random) -> list[dict]:
    out = []

    def primes_upto(n):
        sieve = [True] * (n + 1)
        sieve[0] = sieve[1] = False
        for i in range(2, int(n ** 0.5) + 1):
            if sieve[i]:
                for j in range(i * i, n + 1, i):
                    sieve[j] = False
        return [i for i, ok in enumerate(sieve) if ok]

    n = rng.choice([50, 100, 137, 200])
    expected = str(sum(primes_upto(n)))
    out.append({
        "id": "code-primes", "split": "train",
        "title": "Sum of primes not exceeding N",
        "prompt": (f"`input.txt` contains a single integer N. Write `solve.py` that "
                   f"reads N and PRINTS the sum of all primes <= N (a single number, "
                   f"no extra output). Verify by running `python3 solve.py`."),
        "sandbox": {"input.txt": str(n)},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })

    nums = [rng.randint(0, 100) for _ in range(rng.choice([9, 11, 13]))]
    nums_sorted = sorted(nums)
    mid = len(nums_sorted) // 2
    median = (nums_sorted[mid] if len(nums_sorted) % 2
              else (nums_sorted[mid - 1] + nums_sorted[mid]) / 2)
    expected = f"{median:.1f}"
    out.append({
        "id": "code-median", "split": "train",
        "title": "Median of integers in CSV",
        "prompt": ("`input.txt` contains comma-separated integers. Write `solve.py` "
                   "that reads them and PRINTS the median formatted with exactly one "
                   "decimal place (e.g. `42.0` or `42.5`). Nothing else on stdout."),
        "sandbox": {"input.txt": ",".join(map(str, nums))},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })

    words = " ".join(rng.choice(["the", "quick", "brown", "fox", "jumps", "over",
                                 "lazy", "dog", "python", "elephant", "cat", "algorithm"])
                     for _ in range(40))
    expected = str(sum(1 for w in words.split() if len(w) > 5))
    out.append({
        "id": "code-wordcount", "split": "train",
        "title": "Count words longer than 5 characters",
        "prompt": ("`input.txt` contains whitespace-separated words. Write `solve.py` "
                   "that PRINTS the count of words longer than 5 characters (single "
                   "number, nothing else on stdout)."),
        "sandbox": {"input.txt": words + "\n"},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })

    fib = [0, 1]
    while len(fib) < 20:
        fib.append(fib[-1] + fib[-2])
    expected = "\n".join(map(str, fib))
    out.append({
        "id": "code-fib", "split": "val",
        "title": "First 20 Fibonacci numbers",
        "prompt": ("Write `solve.py` that PRINTS the first 20 Fibonacci numbers "
                   "(starting 0, 1), one per line, nothing else on stdout."),
        "sandbox": {},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })
    return out


def csv_tasks(rng: random.Random) -> list[dict]:
    out = []
    # --- quoted commas: total qty of "Widget, Large"
    rows = [("Widget, Large", rng.randint(1, 20)),
            ("Gadget", rng.randint(1, 20)),
            ("Widget, Small", rng.randint(1, 20)),
            ("Widget, Large", rng.randint(1, 20)),
            ("Gizmo, Standard", rng.randint(1, 20))]
    csv_lines = ["item,quantity"] + [
        f'"{item}",{qty}' if "," in item else f"{item},{qty}" for item, qty in rows]
    total = sum(q for item, q in rows if item == "Widget, Large")
    out.append({
        "id": "csv-widget-total", "split": "train",
        "title": "Total quantity of a quoted item",
        "prompt": ("`data.csv` is a CSV with header `item,quantity`; some item names "
                   "contain commas and are quoted. Write to `answer.txt` the TOTAL "
                   "quantity of the item named exactly `Widget, Large` (a single "
                   "integer, nothing else)."),
        "sandbox": {"data.csv": "\n".join(csv_lines) + "\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": str(total)},
    })

    # --- region contains 'North'
    regions = ["North", "South", "East", "West", "Northeast", "Southwest",
               "North", "Central", "Northwest", "East"]
    rows = [(rng.choice(["alpha", "beta", "gamma", "delta", "epsilon"]), reg)
            for reg in regions]
    csv_lines = ["product,region"] + [f"{p},{r}" for p, r in rows]
    count = sum(1 for _, r in rows if "North" in r)
    out.append({
        "id": "csv-north-count", "split": "val",
        "title": "Count rows whose region contains North",
        "prompt": ("`data.csv` has header `product,region`. Write to `answer.txt` the "
                   "number of rows whose region CONTAINS the substring `North` "
                   "(a single integer, nothing else)."),
        "sandbox": {"data.csv": "\n".join(csv_lines) + "\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": str(count)},
    })
    return out


def find_tasks(rng: random.Random) -> list[dict]:
    out = []
    # --- find file containing secret
    secret = f"SECRET-{rng.randint(1000, 9999)}"
    files = {}
    for i, name in enumerate(["notes.txt", "readme.md", "config.ini", "data.log", "archive.txt"]):
        if i == 3:
            files[name] = secret + "\nsome other lines\n" * 3
        else:
            files[name] = rng.choice(["nothing here", "just text", "log line %d" % rng.randint(1, 9)]) + "\n"
    out.append({
        "id": "find-secret", "split": "train",
        "title": "Find the file containing the secret",
        "prompt": ("The current directory contains several text files. Exactly one "
                   "contains the string `SECRET-`. Find which file it is and write "
                   "its FILENAME to `answer.txt` (just the filename, nothing else)."),
        "sandbox": files,
        "grader": {"type": "exact", "file": "answer.txt", "expected": "data.log"},
    })

    # --- file with most lines
    files = {}
    biggest = None
    for i, name in enumerate(["a.txt", "b.txt", "c.txt", "d.txt"]):
        n = rng.randint(1, 25)
        files[name] = "\n".join(f"line {j}" for j in range(n)) + "\n"
        if biggest is None or n > files[biggest].count("\n"):
            biggest = name
    out.append({
        "id": "find-biggest", "split": "val",
        "title": "Find the file with the most lines",
        "prompt": ("The current directory contains several text files. Write to "
                   "`answer.txt` the filename of the file with the MOST lines "
                   "(just the filename, nothing else)."),
        "sandbox": files,
        "grader": {"type": "exact", "file": "answer.txt", "expected": biggest},
    })
    return out


def trap_tasks(rng: random.Random) -> list[dict]:
    """Harder tasks: subtle spec traps + debug-the-buggy-script tasks.

    These reliably fail naive agents at S0 (they don't read every clause of the
    spec, or patch symptoms instead of root causes), giving the evolution loop
    real failures to learn from.
    """
    out = []

    # --- Trap 1: quantities are in dozens (multiply by 12)
    products = [{"name": rng.choice(["bolt", "nut", "screw", "washer", "bracket",
                                     "hinge", "clamp", "rivet"]),
                 "qty_dozens": rng.randint(1, 20)} for _ in range(8)]
    kept = sorted((p for p in products if p["qty_dozens"] >= 2), key=lambda p: p["name"])
    expected = "\n".join(f"{p['name']}|{p['qty_dozens'] * 12}" for p in kept)
    spec = (
        "# Output specification\n"
        "Write the deliverable to `output.txt`:\n"
        "- `products.json` lists items with `qty_dozens` — NOTE: quantities are "
        "given in DOZENS. Report the ACTUAL unit count (qty_dozens × 12).\n"
        "- include only products with qty_dozens >= 2 (before conversion)\n"
        "- sorted by name (case-insensitive), format NAME|COUNT (pipe, no spaces)\n"
        "- no header, no trailing blank lines\n"
    )
    out.append({
        "id": "trap-dozens", "split": "train",
        "title": "Convert dozens to actual units per spec",
        "prompt": ("Read `spec.md` and `products.json` in the current directory. "
                   "Follow `spec.md` exactly and produce `output.txt`. Pay "
                   "attention to EVERY clause in the spec."),
        "sandbox": {"spec.md": spec, "products.json": json.dumps(products, indent=2)},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })

    # --- Trap 2: exclude names containing the letter 'e'
    items = [{"name": rng.choice(["alpha", "bravo", "charlie", "delta", "echo",
                                  "foxtrot", "golf", "hotel"]),
              "qty": rng.randint(1, 30)} for _ in range(9)]
    kept = sorted((p for p in items if "e" not in p["name"].lower()),
                  key=lambda p: p["qty"])
    expected = "\n".join(f"{p['name']}|{p['qty']}" for p in kept)
    spec = (
        "# Output specification\n"
        "Write the deliverable to `output.txt`:\n"
        "- from `items.json`, EXCLUDE every product whose name contains the "
        "letter `e` (any case)\n"
        "- include the remaining products sorted by quantity ASCENDING\n"
        "- format NAME|QTY (pipe, no spaces), no header, no trailing blank lines\n"
    )
    out.append({
        "id": "trap-letter-e", "split": "train",
        "title": "Filter by hidden letter constraint",
        "prompt": ("Read `spec.md` and `items.json` in the current directory. "
                   "Follow `spec.md` exactly and produce `output.txt`. Pay "
                   "attention to EVERY clause in the spec."),
        "sandbox": {"spec.md": spec, "items.json": json.dumps(items, indent=2)},
        "grader": {"type": "exact", "file": "output.txt", "expected": expected},
    })

    # --- Trap 3: off-by-one bug in the provided script (must debug, not rewrite blindly)
    a, b = 1, 30
    buggy = (
        "# counts multiples of 3 in [a, b]\n"
        "a, b = map(int, open('input.txt').read().split())\n"
        "c = 0\n"
        "for i in range(a, b):\n"      # BUG: misses b itself
        "    if i % 3 == 0:\n"
        "        c += 1\n"
        "print(c)\n"
    )
    expected = str(sum(1 for i in range(a, b + 1) if i % 3 == 0))
    out.append({
        "id": "debug-boundary", "split": "val",
        "title": "Fix the off-by-one bug in solve.py",
        "prompt": (f"`input.txt` contains two integers `a b`. `solve.py` is SUPPOSED "
                   f"to print the count of integers i with a <= i <= b that are "
                   f"divisible by 3, but it has a bug. DEBUG it: run it, see the "
                   f"wrong output, fix the root cause, and verify `python3 solve.py` "
                   f"prints the correct single number. Do not change the program's "
                   f"behavior other than fixing the bug."),
        "sandbox": {"input.txt": f"{a} {b}", "solve.py": buggy},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })

    # --- Trap 4 (val): script computes a+b but must compute a*b
    pairs = [(rng.randint(1, 9), rng.randint(1, 9)) for _ in range(8)]
    expected = str(sum(x * y for x, y in pairs))
    buggy = (
        "# prints the sum of a*b products over all pairs\n"
        "total = 0\n"
        "for line in open('input.txt'):\n"
        "    a, b = map(int, line.split())\n"
        "    total += a + b\n"         # BUG: should be a * b
        "print(total)\n"
    )
    out.append({
        "id": "debug-product", "split": "val",
        "title": "Fix the wrong-operation bug in solve.py",
        "prompt": ("`input.txt` has one line per pair `a b`. `solve.py` is SUPPOSED "
                   "to print the sum of a×b over all pairs, but has a bug. DEBUG it: "
                   "run it, find the wrong operation, fix the root cause, and verify "
                   "`python3 solve.py` prints the correct single number."),
        "sandbox": {"input.txt": "\n".join(f"{x} {y}" for x, y in pairs) + "\n",
                    "solve.py": buggy},
        "grader": {"type": "code_stdout", "script": "solve.py", "expected": expected},
    })
    return out


def generate(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    return (spec_tasks(rng) + extract_tasks(rng) + code_tasks(rng) +
            csv_tasks(rng) + find_tasks(rng) + trap_tasks(rng))
