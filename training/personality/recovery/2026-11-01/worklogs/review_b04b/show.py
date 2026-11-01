import json,sys
a,b=int(sys.argv[1]),int(sys.argv[2])
for i,l in enumerate(open('batch04_b.jsonl',encoding='utf8'),1):
    if i<a or i>b: continue
    s=json.loads(l)
    print(f"=== {i} [{s['category']}]", json.dumps(s.get('context'),ensure_ascii=False))
    for t in s['turns']:
        m=dict(t['moment']);
        print(" U:",t['user']); print("   M:",json.dumps(m,ensure_ascii=False)); print(" K:",t['kiki'])
