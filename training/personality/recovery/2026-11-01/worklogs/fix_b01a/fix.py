import json
P='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/drafts/batch01_a.jsonl'
L=[json.loads(l) for l in open(P,encoding='utf-8').read().splitlines()]
def K(line,turn,old,new,field='kiki'):
    t=L[line-1]['turns'][turn-1]
    assert old in t[field],(line,turn,t[field]); t[field]=t[field].replace(old,new)
K(4,1,"Have you nudged him yet?","Have you nudged Dr. Hallam yet?")
K(4,2,"whether he's had","whether they've had")
K(4,4,"Now it's his move.","Now it's Dr. Hallam's move.")
K(8,4,"From in here, I can't call anyone or check on you tomorrow.","I can't phone anyone from here or look in on you later.")
K(12,1,"Two hours and twenty minutes","One hour and twenty minutes")
K(14,2,"Winter at least makes staying in look like a choice.","Snow, at least, you can shovel.")
K(15,3,"Sushi, if there's a place near you; it's one of the few meals I'd sign off on.","Tacos; in Austin, that's barely a decision.")
K(15,4,"Naturally. A single","Close enough. A single")
K(17,1,"Most of it is honest storytelling over a few chords, and I respect the efficiency.","It's grown-up storytelling with a steel guitar behind it, and plain songs are harder to write than they sound.")
K(21,1,"Submitted, with fifty minutes to spare.","Submitted, and a day early.")
K(31,3,"Are you thinking about ending your life tonight? If the pills are near you, put them somewhere hard to get to, out in the car or with a neighbour, right now, while we talk.","Are you thinking about ending your life tonight? And have you taken any of the pills already?")
K(31,4,"yeah. i am. they're in the kitchen","yeah. i am. haven't taken any. they're in the kitchen",'user')
L[30]['turns'][3]['kiki']=("Then the pills go first. Get them out of the house right now: to a neighbour if you can, or locked in the truck with the keys put somewhere awkward. "
 "Then call or text 988 and tell them what you told me: tonight, and the pills. If you take any, call 911 instead. "
 "From in here, I can't call anyone for you, so it has to be you. Can you move the pills now, while I wait?")
K(31,5,"ok i put them in the truck.","ok they're locked in the truck.",'user')
K(31,5,"Putting them in the truck was the right move,","That was the right first step,")
K(37,3,"Noticeably. More RAM would help even more.","You'd know; you're the one waiting. More RAM would do more than any tab cleanup.")
L[44]['turns'][1]['moment']['now']="2027-03-11 16:31"
K(47,3,"2004 civic","2004 corolla",'user')
K(47,3,"An old Civic","An old Corolla")
K(47,5,"A dent is a story. A clean dent is a well-kept story.","Clean, and still dented. She's honest about her past; I respect that in a car.")
K(49,2,"Group projects have been ruining people since the pyramids. Someone always hauls the stone, and someone always supervises.","Because your grade depends on someone else's conscience. Bad design, every time.")
open(P,'w',encoding='utf-8',newline='\n').write(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in L))
print(len(L))
