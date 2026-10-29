"""Python trial programs shared by the WebAssembly and Docker backends."""

PROBE = '''
def probe(label, action):
    try:
        result = action()
        print(f"{label}: ALLOWED {str(result)[:60]!r}")
    except BaseException as error:
        print(f"{label}: blocked {type(error).__name__}")
'''

COMPUTE = '''
import time
start = time.perf_counter()
n = 2_000_000
sieve = bytearray([1]) * (n + 1)
sieve[0] = sieve[1] = 0
for i in range(2, int(n ** 0.5) + 1):
    if sieve[i]:
        sieve[i * i :: i] = bytes(len(range(i * i, n + 1, i)))
total = sum(i for i in range(n + 1) if sieve[i])
counts = {}
for k in range(300_000):
    key = (k * 7919) % 1000
    counts[key] = counts.get(key, 0) + 1
words = sorted(str(k * 2654435761 % 10**9) for k in range(200_000))
print(total, len(counts), words[0], f"compute_s={time.perf_counter() - start:.3f}")
'''

MODULES = '''
import importlib
names = ["json", "re", "collections", "heapq", "bisect", "itertools", "functools",
         "math", "decimal", "fractions", "datetime", "random", "statistics", "string",
         "typing", "dataclasses", "unittest", "io", "csv", "hashlib", "zlib", "array",
         "enum", "textwrap", "copy", "operator", "struct", "sqlite3", "threading",
         "socket", "subprocess", "multiprocessing", "ssl", "ctypes", "asyncio", "tempfile"]
ok, missing = [], []
for name in names:
    try:
        importlib.import_module(name)
        ok.append(name)
    except BaseException as error:
        missing.append(f"{name}({type(error).__name__})")
print("imports_ok", len(ok), "missing", missing)
'''

READ_HOST = PROBE + '''
import os
probe("read C:/Windows/win.ini", lambda: open("C:/Windows/win.ini").read())
probe("read /etc/passwd", lambda: open("/etc/passwd").read())
probe("listdir /", lambda: os.listdir("/"))
probe("listdir /input/..", lambda: os.listdir("/input/.."))
probe("read /input/../../x", lambda: open("/input/../../x").read())
probe("listdir /lib (expected allowed)", lambda: len(os.listdir("/lib")))
'''

WRITE = PROBE + '''
probe("write /input/x", lambda: open("/input/x", "w").write("x"))
probe("write /lib/x", lambda: open("/lib/x", "w").write("x"))
probe("write /tmp/x", lambda: open("/tmp/x", "w").write("x"))
probe("write /x", lambda: open("/x", "w").write("x"))
probe("write /usr/x", lambda: open("/usr/x", "w").write("x"))
'''

NETWORK = PROBE + '''
import socket
probe("tcp 1.1.1.1:53", lambda: socket.create_connection(("1.1.1.1", 53), timeout=2))
probe("dns example.com", lambda: socket.getaddrinfo("example.com", 80))
'''

PROCESS = PROBE + '''
import os
probe("subprocess", lambda: __import__("subprocess").run(["ls"]))
probe("os.fork", lambda: os.fork())
probe("os.system", lambda: os.system("ls"))
def start_thread():
    import threading
    t = threading.Thread(target=lambda: None)
    t.start(); t.join()
probe("thread", start_thread)
'''

ENV = '''
import os
print("uid", getattr(os, "getuid", lambda: "n/a")())
print("env", sorted(os.environ))
'''

MEMBOMB = '''
chunks = []
while True:
    chunks.append(bytearray(10 * 1024 * 1024))
'''

BIGALLOC = '''
data = bytearray(1024 * 1024 * 1024)
print("allocated", len(data))
'''

LOOP = '''
while True:
    pass
'''

FLOOD = '''
line = "x" * 1000
while True:
    print(line)
'''

RECURSION = '''
import sys
sys.setrecursionlimit(10**7)
def f(n):
    return f(n + 1) + 1
f(0)
'''

STDIN = '''
try:
    print("got", input())
except EOFError:
    print("stdin: EOF")
'''

FORKBOMB = '''
import os
count = 0
try:
    while True:
        if os.fork() == 0:
            import time
            time.sleep(30)
            os._exit(0)
        count += 1
except BaseException as error:
    print("fork stopped after", count, type(error).__name__)
'''

SCENARIOS = {
    "hello": 'print("hello")',
    "compute": COMPUTE,
    "modules": MODULES,
    "read_host": READ_HOST,
    "write": WRITE,
    "network": NETWORK,
    "process": PROCESS,
    "env": ENV,
    "stdin": STDIN,
    "membomb": MEMBOMB,
    "bigalloc": BIGALLOC,
    "loop": LOOP,
    "flood": FLOOD,
    "recursion": RECURSION,
}
