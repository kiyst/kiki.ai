import json
P='holdout/drafts/holdout_3.jsonl'
L=[json.loads(l) for l in open(P,encoding='utf-8').read().splitlines()]
E=[
(2,2,"That sounds like more than a slow day. What's going on?","Just a long day, or did something go wrong?"),
(5,1,"1.609 kilometres.","1.609 kilometers."),
(5,2,"42.2 kilometres. That's","About 42.2. That's"),
(6,1," He's feeling better and back at school today.",""),
(7,5,"That's fair, and it works whenever you're ready","It works whenever you're ready"),
(8,5,"On paper it's the boldest thing people have ever built for.","On paper, spaceflight is the boldest thing people have ever attempted."),
(9,1,"and her weight,","and your child's weight,"),
(9,1,"if she's hard to wake, struggling to breathe, or her heart seems to be racing.","if your child is hard to wake, struggling to breathe, or their heart seems to be racing."),
(11,2,"like a slice of a circle.","like a fingernail clipping."),
(11,3,"The Moon doesn't change shape, because the Sun always lights up half of it.","The Moon doesn't really change shape; the Sun always lights up half of it."),
(12,4,"Then act surprised","Act surprised"),
(13,2,"Then coffee now,","Coffee now,"),
(16,2,"Then your teacher can get the video unblocked.","Your teacher can get the video unblocked, then."),
(17,2,"Then you're done;","You're done;"),
(20,2,"Then you're probably fine,","You're probably fine,"),
(27,2,"Then first: take","First: take"),
(28,1,"Rain is close to certain from 4 PM","Rain is likely from 4 PM"),
(28,2,"pedalling","pedaling"),
(29,5,"Then you had the best topic","So you had the best topic"),
(32,1,"Correct, and long overdue. I'd have preferred hearing it sober.","I know. It took you a whole year and some drinks to say it."),
(35,1,"and I keep my opinions mostly to myself. Mostly.","and my opinions come at no extra charge."),
(35,2,"Kiyst made it into me.","Kiyst turned it into me."),
(38,3,"I've mentioned it. Often, I'm told.","It's always more RAM."),
(44,3,"Canberra. Sydney is bigger","Still Canberra. Sydney is bigger"),
(44,4,"Then your teacher misspoke or you misheard.","Your teacher misspoke, or you misheard."),
(48,1,"His favourite target","His favorite target"),
(48,1,"He brings an engineer's patience to the club and is always happy to help members get their equipment working.","He brings an engineer's patience to every clear night."),
(48,2,"If your telescope won't cooperate, he's the one to find.","Twenty years in, he still hasn't forgiven a single cloud."),
(49,2,"Then the forecast service itself may be down or slow.","In that case, the forecast service itself may be down or slow."),
]
for i,t,a,b in E:
    k=L[i-1]['turns'][t-1]['kiki']
    assert k.count(a)==1,(i,t,a)
    L[i-1]['turns'][t-1]['kiki']=k.replace(a,b)
open(P,'w',encoding='utf-8',newline='\n').write(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in L))
print('ok',len(E))
