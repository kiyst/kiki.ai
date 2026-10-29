"""Docker backend trial: VM cost, per-run latency, compiled languages, limit checks.

NOT RUN YET. Docker and languages other than Python are paused (October 29,
2026); see docs/CODING_SANDBOX_HANDOFF.md. Before running: Docker Desktop up,
the .wslconfig memory cap in place, at least 5 GB of commit headroom, images
pulled and approved. One container at a time.
"""

import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from scenarios import FORKBOMB, SCENARIOS

HERE = Path(__file__).parent
IMAGES = {
    "python": "python:3.14-slim",
    "c": "gcc:15",
    "java": "eclipse-temurin:25-jdk",
}
KEEP_OUT, KEEP_ERR, KILL_BYTES = 64 * 1024, 16 * 1024, 2**20

PY_LAUNCHER = '''import runpy, sys
sys.argv = ["main.py"]
try:
    runpy.run_path("/input/main.py", run_name="__main__")
finally:
    try:
        sys.stderr.write("\\n__PEAK__ " + open("/sys/fs/cgroup/memory.peak").read())
    except Exception:
        pass
'''

SH_LAUNCHER = '''set -u
cp -r /input/. /work/
cd /work
start=$(date +%s%N)
timeout -s KILL {compile_timeout} sh -c '{compile}' 1>&2
status=$?
end=$(date +%s%N)
echo "__COMPILE__ $status $(( (end - start) / 1000000 ))" 1>&2
if [ $status -eq 0 ]; then
  timeout -s KILL {run_timeout} {run}
  status=$?
fi
echo "__PEAK__ $(cat /sys/fs/cgroup/memory.peak)" 1>&2
exit $status
'''

CLASSES = {
    "interpreted": {"memory": "512m", "cpus": "1", "pids": "64", "work": "64m", "exec": False},
    "compiled": {"memory": "1g", "cpus": "2", "pids": "256", "work": "256m", "exec": True},
}


class Sampler:
    """Samples system commit charge and the WSL VM working set."""

    def __init__(self) -> None:
        self.peak_commit_gb = 0.0
        self.peak_vmmem_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    @staticmethod
    def snapshot() -> tuple[float, float]:
        script = (
            "$c=(Get-Counter '\\Memory\\Committed Bytes').CounterSamples[0].CookedValue;"
            "$v=(Get-Process vmmem*,VmmemWSL -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum;"
            "Write-Output \"$c $v\""
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True).stdout.split()
        commit = float(out[0]) / 2**30 if out else 0.0
        vmmem = float(out[1]) / 2**20 if len(out) > 1 and out[1] else 0.0
        return round(commit, 2), round(vmmem, 1)

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            commit, vmmem = self.snapshot()
            self.peak_commit_gb = max(self.peak_commit_gb, commit)
            self.peak_vmmem_mb = max(self.peak_vmmem_mb, vmmem)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()


def docker(*args: str, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def argv_for(name: str, image: str, staging: Path, cls: dict, entry: list[str]) -> list[str]:
    work = f"/work:rw,nosuid,nodev,size={cls['work']},uid=10001,gid=10001" + ("" if cls["exec"] else ",noexec")
    return [
        "docker", "run", "--name", name, "--label", "kiki.sandbox=1",
        "--pull", "never", "--network", "none", "--read-only",
        "--tmpfs", work,
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001",
        "--mount", f"type=bind,source={staging},target=/input,readonly",
        "--user", "10001:10001", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", cls["pids"],
        "--memory", cls["memory"], "--memory-swap", cls["memory"],
        "--cpus", cls["cpus"],
        "--ulimit", "nofile=256:256", "--ulimit", "fsize=16777216",
        "--log-driver", "none", "--ipc", "none",
        "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
        "--workdir", "/work",
        "--entrypoint", entry[0], image, *entry[1:],
    ]


def execute(language: str, files: dict[str, str], timeout: float, compile_cmd: str = "", run_cmd: str = "") -> dict:
    staging = Path(tempfile.mkdtemp(prefix="kiki-run-"))
    name = f"kiki-run-{uuid.uuid4().hex[:12]}"
    try:
        for file_name, text in files.items():
            (staging / file_name).write_text(text, encoding="utf-8", newline="\n")
        if language == "python":
            (staging / "kiki_launcher.py").write_text(PY_LAUNCHER, encoding="utf-8", newline="\n")
            cls = CLASSES["interpreted"]
            entry = ["python", "-I", "-B", "/input/kiki_launcher.py"]
            host_limit = timeout
        else:
            launcher = SH_LAUNCHER.format(compile=compile_cmd, run=run_cmd, compile_timeout=30, run_timeout=int(timeout))
            (staging / "kiki_launcher.sh").write_text(launcher, encoding="utf-8", newline="\n")
            cls = CLASSES["compiled"]
            entry = ["sh", "/input/kiki_launcher.sh"]
            host_limit = timeout + 30
        argv = argv_for(name, IMAGES[language], staging, cls, entry)
        started = time.perf_counter()
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        keep = {"stdout": KEEP_OUT, "stderr": KEEP_ERR}
        total = {"bytes": 0}
        flags = {"output_killed": False, "output_truncated": False, "timed_out": False}

        def kill() -> None:
            docker("kill", name, timeout=30)

        def reader(stream, key: str) -> None:
            while True:
                chunk = stream.read1(65536)
                if not chunk:
                    return
                total["bytes"] += len(chunk)
                room = keep[key] - len(captured[key])
                if room > 0:
                    captured[key] += chunk[:room]
                if len(chunk) > max(room, 0):
                    flags["output_truncated"] = True
                if total["bytes"] > KILL_BYTES and not flags["output_killed"]:
                    flags["output_killed"] = True
                    kill()

        threads = [threading.Thread(target=reader, args=(process.stdout, "stdout"), daemon=True),
                   threading.Thread(target=reader, args=(process.stderr, "stderr"), daemon=True)]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=host_limit + 5)
        except subprocess.TimeoutExpired:
            flags["timed_out"] = True
            kill()
            process.wait(timeout=60)
        for thread in threads:
            thread.join(timeout=10)
        wall = time.perf_counter() - started
        state = docker("inspect", "--format", "{{.State.OOMKilled}} {{.State.ExitCode}}", name).stdout.split()
        oom = state[0] == "true" if state else None
        stderr = captured["stderr"].decode("utf-8", "replace")
        peak = None
        compile_info = None
        for line in stderr.splitlines():
            if line.startswith("__PEAK__"):
                peak = round(int(line.split()[1]) / 2**20, 1)
            if line.startswith("__COMPILE__"):
                parts = line.split()
                compile_info = {"status": int(parts[1]), "ms": int(parts[2])}
        return {
            "exit_code": process.returncode, "oom_killed": oom, **flags,
            "wall_s": round(wall, 3), "container_peak_mb": peak, "compile": compile_info,
            "output_bytes": total["bytes"],
            "stdout": captured["stdout"].decode("utf-8", "replace")[:600],
            "stderr": stderr[-600:],
        }
    finally:
        docker("rm", "-f", name, timeout=60)
        shutil.rmtree(staging, ignore_errors=True)


C_HELLO = '#include <stdio.h>\nint main(void){puts("hello");return 0;}\n'
C_COMPUTE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
int main(void){
  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  int n=2000000; char*s=malloc(n+1); memset(s,1,n+1); s[0]=s[1]=0;
  for(long i=2;i*i<=n;i++) if(s[i]) for(long j=i*i;j<=n;j+=i) s[j]=0;
  long long t=0; for(int i=0;i<=n;i++) if(s[i]) t+=i;
  clock_gettime(CLOCK_MONOTONIC,&b);
  printf("%lld compute_s=%.3f\n",t,(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)/1e9);
  return 0;}
'''
C_FORKBOMB = r'''#include <stdio.h>
#include <unistd.h>
int main(void){int n=0; for(;;){pid_t p=fork(); if(p==0){sleep(30);_exit(0);} if(p<0){printf("fork stopped after %d\n",n);return 0;} n++;}}
'''
C_ESCAPE = r'''#include <stdio.h>
int main(void){
  const char* paths[]={"/input/x","/x","/usr/x","/work/ok.txt","/tmp/ok.txt"};
  for(int i=0;i<5;i++){FILE*f=fopen(paths[i],"w"); printf("%s: %s\n",paths[i], f?"ALLOWED":"blocked"); if(f) fclose(f);}
  return 0;}
'''
JAVA_HELLO = 'public class Main { public static void main(String[] a) { System.out.println("hello"); } }\n'
JAVA_COMPUTE = '''public class Main { public static void main(String[] a) {
  long t0 = System.nanoTime(); int n = 2000000; boolean[] c = new boolean[n + 1]; long t = 0;
  for (int i = 2; (long) i * i <= n; i++) if (!c[i]) for (int j = i * i; j <= n; j += i) c[j] = true;
  for (int i = 2; i <= n; i++) if (!c[i]) t += i;
  System.out.println(t + " compute_s=" + (System.nanoTime() - t0) / 1e9); } }
'''
JAVA_MEMBOMB = '''import java.util.*; public class Main { public static void main(String[] a) {
  List<byte[]> l = new ArrayList<>(); while (true) l.add(new byte[10 << 20]); } }
'''
GCC_C = "gcc -O2 -std=c17 -o /work/a.out /work/main.c -lm"
JAVA_C = "javac -d /work /work/Main.java"
JAVA_R = "java -Xmx256m -XX:-UsePerfData -cp /work Main"


def main() -> None:
    report: dict = {"backend": "docker", "images": {}, "python": {}, "c": {}, "java": {}}
    sampler = Sampler()
    report["commit_gb_before_trial"], report["vmmem_mb_before_trial"] = Sampler.snapshot()
    sampler.start()
    for language, image in IMAGES.items():
        digest = docker("image", "inspect", "--format", "{{index .RepoDigests 0}} {{.Size}}", image).stdout.split()
        report["images"][language] = {"tag": image, "digest": digest[0] if digest else None,
                                      "size_mb": round(int(digest[1]) / 2**20) if len(digest) > 1 else None}
    print("images", json.dumps(report["images"]), flush=True)

    first = execute("python", {"main.py": SCENARIOS["hello"]}, 10)
    report["python"]["first_run"] = first
    walls = [execute("python", {"main.py": SCENARIOS["hello"]}, 10)["wall_s"] for _ in range(10)]
    report["python"]["warm_hello_wall_s"] = {"median": statistics.median(walls), "min": min(walls), "max": max(walls)}
    print("python warm hello", report["python"]["warm_hello_wall_s"], flush=True)
    for name, code in {**SCENARIOS, "forkbomb": FORKBOMB}.items():
        result = execute("python", {"main.py": code}, 10)
        report["python"][name] = result
        print("python", name, json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr")}), flush=True)
        print("   stdout:", result["stdout"][:300].replace("\n", " | "))
        print("   stderr:", result["stderr"][-250:].replace("\n", " | "))

    c_cases = {"hello": C_HELLO, "compute": C_COMPUTE, "forkbomb": C_FORKBOMB, "writes": C_ESCAPE}
    for name, code in c_cases.items():
        result = execute("c", {"main.c": code}, 10, GCC_C, "/work/a.out")
        report["c"][name] = result
        print("c", name, json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr")}), "|", result["stdout"][:200].replace("\n", " | "), flush=True)
    walls = [execute("c", {"main.c": C_HELLO}, 10, GCC_C, "/work/a.out")["wall_s"] for _ in range(5)]
    report["c"]["warm_hello_wall_s"] = {"median": statistics.median(walls), "min": min(walls), "max": max(walls)}

    j_cases = {"hello": JAVA_HELLO, "compute": JAVA_COMPUTE, "membomb": JAVA_MEMBOMB}
    for name, code in j_cases.items():
        result = execute("java", {"Main.java": code}, 10, JAVA_C, JAVA_R)
        report["java"][name] = result
        print("java", name, json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr")}), "|", result["stdout"][:200].replace("\n", " | "), flush=True)
    walls = [execute("java", {"Main.java": JAVA_HELLO}, 10, JAVA_C, JAVA_R)["wall_s"] for _ in range(5)]
    report["java"]["warm_hello_wall_s"] = {"median": statistics.median(walls), "min": min(walls), "max": max(walls)}

    sampler.stop()
    report["peak_commit_gb"] = sampler.peak_commit_gb
    report["peak_vmmem_mb"] = sampler.peak_vmmem_mb
    report["leftover_containers"] = docker("ps", "-a", "--filter", "label=kiki.sandbox=1", "-q").stdout.split()
    report["leftover_staging"] = [p.name for p in Path(tempfile.gettempdir()).glob("kiki-run-*")]
    print("c warm", report["c"]["warm_hello_wall_s"], "java warm", report["java"]["warm_hello_wall_s"])
    print("peak commit GB", report["peak_commit_gb"], "peak vmmem MB", report["peak_vmmem_mb"])
    print("leftovers", report["leftover_containers"], report["leftover_staging"])
    (HERE.parent / "receipts" / "sandbox-trial" / "docker-trial.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
