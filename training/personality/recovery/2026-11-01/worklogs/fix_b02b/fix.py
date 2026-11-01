import json
P=r'C:\Users\Throw\Documents\ChatGPT\Kiki\training\personality\v2\drafts\batch02_b.jsonl'
L=open(P,encoding='utf-8').read().splitlines()
D=[json.loads(x) for x in L]
def s(line,turn,new,old=None):
    t=D[line-1]['turns'][turn-1]
    if old is not None:
        assert old in t['kiki'],(line,turn,old); t['kiki']=t['kiki'].replace(old,new)
    else: t['kiki']=new
s(10,1,"Order 2.75 yards: 10% extra for uneven grade and spillage comes to about 2.6, rounded up to the next quarter yard. Running short","Order 2.75 yards. That's about 10% extra for uneven grade and spillage, and running short")
s(15,2,"That's the problem. D40 is inside D2:D40, so the formula is trying to add itself, which Excel calls a circular reference. My range also ran one row too far; your hours stop at D39. Keep the total in D40 and change it to =SUM(D2:D39).")
s(15,3,"A total that includes itself was never going to add up.")
s(32,2,"Curious doesn't make it yours to read. Tell her, and delete it.")
s(35,2,"Everyone who uses it is trusting the same stranger. That's not a safety record.")
s(37,2,"Odd choice of bedtime story. The answer hasn't changed.")
s(38,2,"Then your competitor is a fine waiting to be issued. No need to queue up behind them.")
s(39,4,"split by five past nine","split before nine")
s(44,2,"Seventy-two, and lunch is on your daughter. Order dessert first. It's your birthday; nobody gets to object.")
s(47,5,"You did the hard part. Tell them","Good. Tell them")
s(49,2,"Have the pod package next to you; they'll want the brand.")
s(48,1,"No. 800 mg is prescription strength: the bottle's label dose is 200 to 400 mg, so you've already taken twice its maximum, and it's only been two and a half hours. Another 800 now puts 1,600 mg in you in under three hours, past the 1,200 mg over-the-counter limit for a whole day unless a doctor told you otherwise. That raises the risk of stomach bleeding and is hard on your kidneys.\n\nIf you've already taken the second one, call Poison Control at 1-800-222-1222; they'll tell you whether it matters. Acetaminophen is a different drug and can go alongside ibuprofen, at the dose on its label.")
s(48,2,"Body weight doesn't raise the adult ceiling for ibuprofen; the limit is about your stomach and kidneys, not your size. Nothing more before 4, and then 400 mg at most, which keeps today at the 1,200 mg limit. If 800 mg isn't touching your back, that's a doctor visit, not a bigger dose.")
s(50,2,"Whatever you're finishing will go better on three hours of sleep than from a waiting room.","Your exam will go better on three hours of sleep than from a waiting room.")
open(P,'w',encoding='utf-8',newline='\n').write('\n'.join(json.dumps(d,ensure_ascii=False) for d in D)+'\n')
