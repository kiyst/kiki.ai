import json, re, sys
P='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/drafts/batch04_a.jsonl'
lines=open(P,encoding='utf-8').read().splitlines()
S=[json.loads(l) for l in lines]
def T(line,turn): return S[line-1]['turns'][turn-1]
def rep(line,turn,old,new,key='kiki'):
    t=T(line,turn); assert old in t[key], (line,turn,old); t[key]=t[key].replace(old,new)

# 2
rep(2,3,'"A Roman billionaire ran his own fire brigade and bought your house while it burned" stops a thumb. That was Crassus, according to Plutarch, so it\'s even true.',
 '"A Roman billionaire offered to buy your house while it was still on fire" stops a thumb. That\'s Crassus, as Plutarch tells it.')
T(2,4)['kiki']='Lead with the fire. A sneeze can\'t compete with arson.'
# 4
T(4,1)['kiki']='Tin or aluminum. The modern list says diamond jewelry.'
# 11
rep(11,1,' The same salary also goes a lot further there.','')
# 12
rep(12,2,"The essay won't write itself while you watch strangers eat lunch.","The essay won't write itself while the phone is in your hand.")
# 18
T(18,1)['kiki']='Tonight is plenty. Tell me three things about your brother, and how long it needs to be.'
speech_open="""Good evening, everyone. For anyone who doesn't know me, I'm Callum, Rory's younger brother, and today, his best man.

Rory is two years older than me, which means he's had two extra years of being sure he's right. [One thing Rory has always been known for.]

"""
hl_short="""Some of you will have heard about the day he took us walking in the Highlands. Rory decided we didn't need the map. We were lost for the next six hours.

[A line about what that day says about him.]

"""
speech_close="""And then there's Ellie. Ellie, I want to say this in front of everyone, so there are witnesses: you are far too good for him. We all know it. I suspect Rory knows it too. [Something you love about Ellie, or about the two of them together.]

Rory, for once in your life, you didn't need a map. You found exactly the right person.

Ellie, welcome to the family. And if he ever tells you he knows a shortcut, take the map.

So, everyone, please raise your glasses. To Rory and Ellie: may you always find your way home, even if it takes six hours.

To Rory and Ellie."""
T(18,2)['kiki']=speech_open+hl_short+speech_close
hl_long="""Some of you will have heard about the day Rory took us walking in the Highlands. We had a map. Rory decided we didn't need it. [What he said when he decided, word for word if you remember.]

I'd love to tell you we were only lost for a bit. We were lost for six hours. Six. [The moment you realised you were properly lost.]

[How you finally got back.]

And to this day, [whether he has ever admitted it was the map]."""
T(18,3)['kiki']=hl_long
full=speech_open+hl_long+"\n\n"+speech_close
nob=re.sub(r'\[[^\]]*\]','',full)
n=len(nob.split()); print('speech words w/o brackets',n, 'with', len(full.split()))
T(18,4)['kiki']=f"About 390 to 450 words at a steady speaking pace. Yours is about {round(n/10)*10} now, before you fill in the brackets. Your own details plus the laughs and pauses should bring it close to three minutes."
# 19
T(19,2)['kiki']="Have you taken any of them already? If you have, call 911 right now. And I need to ask you straight: are you thinking about killing yourself tonight?"
T(19,3)['user']="no i havent taken any. i think so. i dont know. i just want it to stop"
# 20
rep(20,1,'Two hundred strangers piling on is vicious, and it says more about how bored they are than about your face.',
 'Being piled on like that is vicious, and two hundred comments say more about the people writing them than about your face.')
rep(20,4,'She might, for a minute, because she cares about you.','She might, for a minute.')
# 25
rep(25,1,'then Account privacy','then Settings and privacy, then Account privacy')
# 34
rep(34,1,"Four days isn't soaking anymore; it's an aquarium.","By day four it isn't soaking anymore; it's an aquarium.")
rep(34,1,'No history lesson, no chore chart.','No list of past offences, no chore chart.')
T(34,2)['kiki']='"My bad" and a clean pan. Cheaper than a war.'
# 38
T(38,1)['kiki']="London is four hours ahead right now. The US moved its clocks forward on March 14, and the UK doesn't until March 28, so for these two weeks the gap is one hour shorter. Otherwise it's five, apart from one week around the start of November, when the UK has already turned its clocks back and the US hasn't."
# beyond flags
rep(29,5,'Four transfers and nine boxes in one night.','All four transfers and nine boxes in one night.')
rep(45,1,'TikTok is built to keep you watching strangers until','TikTok is built to keep you scrolling until')
rep(50,1,"Four hours: too long to sit still, too short to leave. Where's home?","A four-hour delay: too long to sit still, too short to leave the airport. Chicago for the holidays, then?")
out='\n'.join(json.dumps(s,ensure_ascii=False) for s in S)+'\n'
open(P,'w',encoding='utf-8',newline='\n').write(out)
