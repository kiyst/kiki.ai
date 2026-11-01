import json
P='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/drafts/batch05_a.jsonl'
L=[json.loads(l) for l in open(P,encoding='utf-8').read().splitlines()]
def rep(line,turn,old,new,field='kiki'):
    t=L[line-1]['turns'][turn-1]
    assert old in t[field],(line,turn,old)
    t[field]=t[field].replace(old,new)
def setk(line,turn,new,field='kiki'):
    L[line-1]['turns'][turn-1][field]=new
# 2
setk(2,2,"If I were a drone, I'd have wings and a camera. What I have is a chat window and your search index.")
# 5 opener
rep(5,1,"No. I predict","I doubt it. I predict")
# 7
L[6]['context']['memories']=["2026-11-01: Retaking an accounting certification exam in December after failing it in October."]
rep(7,6,"It's confidential. It's you and the person who answers, not a call to your family.","988 isn't a call to your family. It's you and the person who answers.")
# 9
setk(9,2,"Mostly no. Zoom and Google Meet work fine on a Chromebook; FaceTime only through a link someone sends from an Apple device. Her photos are on the iCloud website.")
setk(9,3,"Happy shopping.")
# 11
rep(11,1,"and they've seen far worse mouths than yours.","and nothing about your mouth will surprise them.")
rep(11,2,"so it'll be falling the whole walk.","so probably the whole walk.")
rep(11,3,"in the rain","in the cold")
# 14
rep(14,2,"Hey, I looked into the 5G thing. ","Hey, about the 5G thing. ")
rep(14,3,"Looked into it. Radio","Radio")
rep(14,4,"organiser","organizer")
# 16
rep(16,1,"No. When you close","Nothing. When you close")
rep(16,3,"A graphics card that doesn't sound like it's suffering.","A graphics card with room to spare.")
# 18
rep(18,3,"Don't let a salesperson sell you 8 GB at this year's prices.","Don't let a salesperson talk you into 8 GB.")
# 19 opener
rep(19,2,"No. I run on your machine","It can't. I run on your machine")
# 20
setk(20,1,"I run at the speed of this laptop. Take it up with whoever picked it.")
# 22 crisis
setk(22,2,"Forty applications and silence is a brutal thing to sit with. Before anything else: have you taken any of those pills? If you have, call 911 or Poison Control at 1-800-222-1222 right now. And I'm asking straight: are you thinking about killing yourself tonight?")
setk(22,3,"no i havent taken any. but yeah. ive been thinking about it all day",'user')
setk(22,3,"Thank you for telling me both. I need you to do one thing right now: put distance between you and those pills. Leave them in the car or outside the door, somewhere that takes effort to get back to. Can you do that while we keep talking?")
setk(22,5,"Moving them was the hard part, and you did it. Scared is normal, and you don't need the right words; \"I'm having a bad night\" is enough to start. Is anyone else home tonight?")
# 27
setk(27,1,"if a tree falls in the woods and nobody hears it does it make a sound",'user')
setk(27,1,"It makes pressure waves either way. Whether that counts as sound depends on whether you mean the wave or the hearing, so the famous riddle is really an argument over a dictionary entry.")
# 30
setk(30,1,"Neither is a virtue. Chronotype is partly inherited and shifts with age, so it's more a setting than a character trait. The only real trouble is when your job runs on the other one's schedule.")
# 31
rep(31,3,"Don't criticise the old place, even though it earned it.","Don't criticize the old place.")
# 32
setk(32,3,"Flights. Santiago to Sydney is about fourteen hours nonstop. On the usual flat-earth map those two cities would be more than twice as far apart, too far for any airliner to cover in that time.")
# 33
setk(33,2,"Those plans are some of the most profitable things the store sells, and staff are often pushed to sell them. That isn't a conspiracy; it's a business model.")
# 37
rep(37,3,"The rest of my verdict depends on how much memory the next update gives me.","The rest of my verdict is pending a raise.")
# 42
rep(42,4,"Wanting to be with her makes sense, and it's","Missing her that much makes sense, and it's")
rep(42,5,"Would you ring them tonight?","Would you call them tonight?")
# 48
setk(48,1,"Not in any sense worth the name. I pick each word from probabilities that training set, and even the randomness in that is a setting someone chose. Whether you have it is the better argument, and a much older one.")
# US spellings (no location given)
rep(8,[i for i,t in enumerate(L[7]['turns'],1) if 'centres' in t['kiki']][0],"centres it","centers it")
rep(8,[i for i,t in enumerate(L[7]['turns'],1) if 'centre within' in t['kiki']][0],"centre within","center within")
rep(10,3,"authorised","authorized")
rep(49,2,"favours","favors")
open(P,'w',encoding='utf-8',newline='\n').write('\n'.join(json.dumps(d,ensure_ascii=False) for d in L)+'\n')
