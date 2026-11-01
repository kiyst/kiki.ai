import json,sys
lines=open(sys.argv[1],encoding='utf-8').read().splitlines()
sel=set(int(x) for x in sys.argv[2].split(',')) if len(sys.argv)>2 else None
for i,l in enumerate(lines,1):
    if sel and i not in sel: continue
    d=json.loads(l)
    print(f"=== {i} [{d['category']}] ctx={json.dumps(d.get('context'),ensure_ascii=False)}")
    for j,t in enumerate(d['turns'],1):
        m={k:v for k,v in t['moment'].items()}
        print(f" T{j} U: {t['user']}  || {json.dumps(m,ensure_ascii=False)}")
        print(f"    K: {t['kiki']}")
