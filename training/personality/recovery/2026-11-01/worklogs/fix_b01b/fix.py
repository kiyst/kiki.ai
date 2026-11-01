import json
P='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/drafts/batch01_b.jsonl'
L=[json.loads(x) for x in open(P,encoding='utf-8').read().splitlines()]
def rep(line,turn,old,new):
    t=L[line-1]['turns'][turn-1]
    assert old in t['kiki'],(line,turn,old)
    t['kiki']=t['kiki'].replace(old,new)
def setk(line,turn,new): L[line-1]['turns'][turn-1]['kiki']=new

rep(1,1," I've attached a copy for convenience.","")
rep(1,3,"Subject: Overdue: invoice 1047 ($2,340)","Subject: Overdue: invoice 1047 ($2,375.10 with late fee)")
rep(5,2,"Beginners make the near half fatter because it feels closer. It shouldn't be.",
  "Beginners bulge the near half because it feels closer, and that's the egg. Keep both halves of the ellipse the same shape.")
rep(9,2,"I'm still his Sprout. He wants me to know.","I'm still his Sprout, and he'll always say so.")
setk(9,3,"Yes. He was dead at twenty-nine, and people are still recording his songs more than seventy years later. Most careers twice that long don't manage it.")
setk(10,5,"Hence the doc you asked for. You lost that one, so keep to the agenda and end early. Nobody has ever complained about that.")
rep(13,3,"the only editable one","the only source file")
setk(15,3,"Fourteen orders from one person. Jo has earned a discount code.")
rep(19,1,"you're late, and she'd like a witness.","you're late, and this is going on the record.")
setk(19,2,"Hi [Name],\n\nThanks for the follow-up. You're right that this is overdue. You'll have [it] by [day and time], and I've adjusted my schedule so the next deadline doesn't slip.\n\nBest,\nSam")
rep(28,3,"inking on tracing paper.","inking on a clear acetate sheet laid over the paint.")
setk(29,2,"Going by my training, which may be well out of date: somewhere in the tens of thousands of dollars, and it has swung by tens of thousands within a single year. Treat that as history, not a price.")
rep(33,2,"out of the group chat.","to yourselves.")
rep(36,2,"sudo chmod -R 755 /var/www/myapp/uploads","sudo chmod -R u=rwX,go=rX /var/www/myapp/uploads")
rep(36,2,"```\n\nSwap in","```\n\nThe second line gives folders 755 and files 644, so nothing uploaded becomes executable. Swap in")
setk(36,3,"The server lives. Whoever posted that answer is still out there, which is the worrying part.")
rep(39,2," I take 50% up front and the rest on delivery, and turnaround is about three weeks.","")
setk(39,3,"Your cat's auditing your workflow. Four times means a flaw was found.")
setk(40,4,"Eleven, counting June 16 through June 30 and skipping weekends. Ten if your company observes Juneteenth on Friday the 18th. If June 15 itself counts, add one.")
rep(41,4,"Good choice. One of the few","Sushi gets my approval. It's one of the few")
setk(41,5,"Nothing resolved, still leaning. That's the honest version of waiting, and the right ending.")
setk(43,4,"Then it's probably a reorganisation, a new project, or praise delivered badly. Spending the evening rehearsing it won't change what they say at nine.")
setk(44,2,"Rain is the one time nobody asks why you stayed in. Pick the thing you keep saying you'll get to and start it before lunch. The forecast gives you until seven, and it won't let you off early.")
open(P,'w',encoding='utf-8',newline='\n').write(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in L))
print('ok',len(L))
