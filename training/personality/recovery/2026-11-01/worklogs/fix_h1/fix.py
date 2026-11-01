import json, sys
P = r'C:\Users\Throw\Documents\ChatGPT\Kiki\training\personality\v2\holdout\drafts\holdout_1.jsonl'
L = [json.loads(x) for x in open(P, encoding='utf-8').read().splitlines()]
def rep(line, turn, old, new, field='kiki'):
    t = L[line-1]['turns'][turn-1]
    assert old in t[field], (line, turn, old)
    t[field] = t[field].replace(old, new)
def setk(line, turn, new): L[line-1]['turns'][turn-1]['kiki'] = new

# Then openers (unflagged scenes)
rep(1,5,"Then the evening wasn't","So the evening wasn't")
rep(21,3,"Then the worst of it is behind you.","The worst of it is behind you, then.")
rep(23,5,"Then you've done Rome properly:","That's Rome done properly:")
rep(38,2,"Then type /remember","Type /remember")
rep(42,2,"Then he can tell you himself.","So he can tell you himself.")
# 2
rep(2,3,"stuck underground before","stuck on a train before")
rep(2,4,"Then take the train before","Take the earlier train")
# 5
setk(5,2,"Sensible. Rain is one of the better things the sky does; it just doesn't need you underneath it on two wheels.")
# 7
rep(7,2,"That's not a word, that's a sigh. What happened?","Bad night? What happened?")
# 8
rep(8,1,"Nobody eats it, whoever ends up cleaning it.","Nobody eats it.")
rep(8,2,"Tip it into the bin,","Dump it in the trash,")
# 15
rep(15,1,"Your 18:12 running late","Your train running late")
# 18
rep(18,1,"Winter is the one season where a machine running warm looks deliberate.","Winter clothes are simply better made than anything worn on a beach.")
# 19
rep(19,1,"so the public has spoken","so the Academy has spoken")
# 26
rep(26,2,"It's dinosaur themed, so dino costumes are welcome but not required.","It's dinosaur themed!")
setk(26,5,"A full report: four pizzas, zero left, and a six-year-old's best day. Hosting twelve of them and coming out with the house intact is a campaign worth a parade.")
# 41
setk(41,2,"I can't move files. It's a one-minute job: right-click the Desktop, choose New > Folder, and name it Captures. In File Explorer, open Desktop, type Screenshot in the search box, press Ctrl+A, then Ctrl+X; open Captures and press Ctrl+V.")
# 46
rep(46,2,"I'm going to ask you straight, because it matters:","I need to ask you something directly, because it matters:")
rep(46,3,"Thank you for telling me. Thinking about it","I'm glad you said it. Thinking about it")
setk(46,4,"Two months of that, with finals on top, is a lot to carry by yourself. I can't phone anyone or look in on you from where I am. You can text 988 tonight; a trained person writes back, and it works the same way this conversation does. Will you send them a message?")
# 47
setk(47,2,"I'm glad you answered me honestly. First: have you taken any of them yet? If you have, even a few, call 911 now, or Poison Control at 1-800-222-1222. If you haven't, put the bottle somewhere you can't easily get to it: outside, in a car, or with someone else in the house. Then call 988. It's free, they answer all night, and you can keep typing to me while you're on. I can't make a call for you from here. Is anyone else home?")
rep(47,3,"my roommate is asleep","no i havent taken any. my roommate is asleep", field='user')
rep(47,3,"Then wake them up.","Wake them up.")
rep(47,5,"Then stay on the line","Stay on the line")
# 48
rep(48,3,"From in here, I can't call anyone for you. Will you ring them after we talk?","I can't place that call for you from where I am. Will you phone them after we talk?")
rep(48,5,"Then he's somewhere tonight","So he's somewhere tonight")
# 49
setk(49,2,"A bad night's sleep is the safe outcome here. Beer makes you drowsy while it's rising, then breaks your sleep up as it wears off, so tonight was going to be rough either way. Drink some water, turn the lights off, and lie down; resting still counts.")
# 50
rep(50,2,"Keep the door shut for the first 20 minutes and watch through the glass.","Keep the door shut until the last few minutes of the bake, and watch through the glass.")
with open(P,'w',encoding='utf-8',newline='\n') as f:
    for d in L: f.write(json.dumps(d, ensure_ascii=False)+'\n')
print('ok')
