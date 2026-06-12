"""End-to-end wall-clock evaluation of the REAL java_tax_calculator javac path.

Drives the skill's own ``try_java_path`` (repair -> javac -> example self-check ->
hidden runs) with the REAL DashScope 35B model, and instruments every phase:

  * each repair round: model latency, compile result, example self-check result
  * javac compile time, per-case ``java`` run time
  * total end-to-end wall clock

It does NOT modify the skill source. It imports run.py as a module and wraps
(monkey-patches) its timing-relevant functions with logging shims that call
through to the originals. The skill's logic is unchanged.

Usage:
  export JAVA_HOME=/d/environment/Java/jdk-21; export PATH="$JAVA_HOME/bin:$PATH"
  set -a; . ./.env.dashscope; set +a
  PYTHONIOENCODING=utf-8 python <this> [rounds]

Stdlib only, Python 3.9, ASCII-only prints.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# research/javac_eval -> research -> task -> tasks -> .trellis -> repo
REPO = HERE.parents[4]
RUN_PY = REPO / "source" / "solution" / "skills" / "java_tax_calculator" / "scripts" / "run.py"

# Public ground truth (decoded from the base64 constants in JavaSource_7_1.java).
PUBLIC_DED = 5000.0
PUBLIC_BRACKETS = [
    [0.0, 3000.0, 0.03, 0.0],
    [3001.0, 12000.0, 0.10, 410.0],
    [12001.0, 25000.0, 0.20, 2660.0],
    [25001.0, 35000.0, 0.25, 4410.0],
    [35001.0, 55000.0, 0.30, 7160.0],
    [55001.0, 80000.0, 0.35, 15160.0],
    [80001.0, 999999999.0, 0.45, 15310.0],
]
STD_SALARIES = [5000, 12000, 25000, 35000, 55000, 60000, 80000, 90000, 150000, 500000]
PUBLIC_EXAMPLES = [(3000, "0.00"), (8000, "90.00"), (15000, "590.00"),
                   (30000, "2340.00"), (100000, "27440.00")]
PUBLIC_REFERENCE = ["0.00", "290.00", "1340.00", "3090.00", "7840.00",
                    "9340.00", "11090.00", "22940.00", "49940.00", "207440.00"]


def load_skill():
    spec = importlib.util.spec_from_file_location("jtr", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Instrument:
    """Wraps run.py timing functions; records phase timings into self.log."""

    def __init__(self, m):
        self.m = m
        self.log = []
        self.round = 0
        self._orig_repair = m.llm_repair_source
        self._orig_compile = m.compile_java
        self._orig_run = m.run_java_case

    def install(self):
        m = self.m

        def repair_shim(config, source, feedback, timeout):
            self.round += 1
            t0 = time.monotonic()
            out = self._orig_repair(config, source, feedback, timeout)
            dt = time.monotonic() - t0
            self.log.append(("repair", self.round, dt, out is not None,
                             len(feedback or "")))
            print("  [round %d] model repair: %.2fs (usable=%s, timeout=%ds, feedback_len=%d)"
                  % (self.round, dt, out is not None, timeout, len(feedback or "")))
            return out

        def compile_shim(source, work_dir):
            t0 = time.monotonic()
            cls, err = self._orig_compile(source, work_dir)
            dt = time.monotonic() - t0
            self.log.append(("compile", self.round, dt, cls is not None, err[:200]))
            status = "OK class=%s" % cls if cls else ("FAIL: " + err[:160].replace("\n", " | "))
            print("  [round %d] javac: %.2fs -> %s" % (self.round, dt, status))
            return cls, err

        def run_shim(class_name, work_dir, salary):
            t0 = time.monotonic()
            out = self._orig_run(class_name, work_dir, salary)
            dt = time.monotonic() - t0
            self.log.append(("run", self.round, dt, out is not None, str(salary)))
            return out

        m.llm_repair_source = repair_shim
        m.compile_java = compile_shim
        m.run_java_case = run_shim

    def restore(self):
        self.m.llm_repair_source = self._orig_repair
        self.m.compile_java = self._orig_compile
        self.m.run_java_case = self._orig_run

    def summary(self):
        repair_t = sum(e[2] for e in self.log if e[0] == "repair")
        compile_t = sum(e[2] for e in self.log if e[0] == "compile")
        run_t = sum(e[2] for e in self.log if e[0] == "run")
        n_repair = sum(1 for e in self.log if e[0] == "repair")
        n_compile = sum(1 for e in self.log if e[0] == "compile")
        n_run = sum(1 for e in self.log if e[0] == "run")
        return dict(repair_t=repair_t, compile_t=compile_t, run_t=run_t,
                    n_repair=n_repair, n_compile=n_compile, n_run=n_run)


def evaluate(m, label, source, examples, salaries, reference, ded, brackets,
             max_rounds, repair_timeout):
    print("=" * 78)
    print("CASE:", label)
    print("  max_rounds=%d  repair_timeout=%ds" % (max_rounds, repair_timeout))
    inst = Instrument(m)
    inst.install()
    warnings = []
    config = m._model_config()
    t0 = time.monotonic()
    # No deadline cap here: we want the raw worst-case timing, then compare to 480.
    outputs = m.try_java_path(config, source, examples, salaries,
                              repair_timeout, max_rounds, warnings, deadline=None)
    total = time.monotonic() - t0
    inst.restore()

    s = inst.summary()
    print("  --- timings ---")
    print("  model repair total : %.2fs over %d call(s)" % (s["repair_t"], s["n_repair"]))
    print("  javac compile total: %.2fs over %d call(s)" % (s["compile_t"], s["n_compile"]))
    print("  java run total     : %.2fs over %d run(s)" % (s["run_t"], s["n_run"]))
    print("  END-TO-END         : %.2fs" % total)
    print("  warnings:", warnings)

    if outputs is None:
        print("  RESULT: java path returned None (no validated build within rounds)")
        correct = 0
        match_ref = False
    else:
        correct = sum(1 for a, b in zip(outputs, reference) if a == b)
        match_ref = outputs == reference
        print("  java-path outputs:", outputs)
        print("  reference        :", reference)
        print("  hidden taxes correct: %d/%d  exact-match=%s"
              % (correct, len(reference), match_ref))
        # 11-seg incl version
        ver_ok = "21.0.11" in m.java_version_line()
        print("  full 11-seg correct: %d/11 (version=%s)"
              % ((1 if ver_ok else 0) + correct, ver_ok))

    return dict(label=label, outputs=outputs, total=total, summary=s,
                correct=correct, match_ref=match_ref, warnings=list(warnings))


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    repair_timeout = int(os.getenv("EVAL_REPAIR_TIMEOUT", "60"))
    m = load_skill()
    print("run.py:", RUN_PY)
    print("model:", (m._model_config() or {}).get("model"))
    print("java_toolchain_available:", m.java_toolchain_available())
    print("java_version_line():", repr(m.java_version_line()))
    print()

    public_src = (REPO / "publish" / "publish_V1" / "JavaSource_7_1.java").read_text(encoding="utf-8")

    results = []
    results.append(evaluate(
        m, "PUBLIC JavaSource_7_1 (decoded ground truth)",
        public_src, PUBLIC_EXAMPLES, STD_SALARIES, PUBLIC_REFERENCE,
        PUBLIC_DED, PUBLIC_BRACKETS, rounds, repair_timeout))

    print("=" * 78)
    print("DONE. public exact-match=%s in %.2fs (rounds budget=%d, repair_timeout=%ds)"
          % (results[0]["match_ref"], results[0]["total"], rounds, repair_timeout))


if __name__ == "__main__":
    main()
