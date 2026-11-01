import json,sys
P='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/holdout/drafts/holdout_2.jsonl'
lines=[json.loads(l) for l in open(P,encoding='utf-8')]
# (line, turn, old, new)
F=[
(1,4,"Then the second one's a free pass.","The second one's a free pass, then."),
(2,3,"That's the classic spot for shin splints.","Classic spot for shin splints."),
(3,2,"That's what a real effort feels like.","Welcome to a real effort."),
(4,1,"Easy it is, until tonight. What happened out there?","Easy it is. What happened out there?"),
(4,2,"Stopping fully is a habit, not a skill, and you clearly handled the rest of the drive.","Stopping fully is a habit, not a skill."),
(4,3,"Good. Three weeks","Three weeks"),
(6,4,"Then it's said, and I heard it.","It's said, and I heard it."),
(7,3,"From what's written about him, that phase punishes early rolls. Wait out the delayed swings instead of panicking into them.","From what's written about him, his combos run longer than they look. Don't roll or heal after the first swing; wait for the string to end."),
(8,1,"52 degrees and calm, up to 61 later.","52 degrees with a light wind, up to 61 later."),
(11,2,"But some small ones survived, and over a very long time they turned into birds.","But some small ones survived: the birds."),
(11,3,"That's a parenting problem.","A parenting problem."),
(13,2,"You die nearly twice for every kill.","Five deaths for every three kills."),
(19,1,"Yes, firmly.","A fan."),
(21,7,"Then it's due Friday, not Thursday at 11:58 pm. See item five.","Friday, then. Not Friday at 11:58 pm. See item five."),
(23,4,"Good. With strokes","Glad to hear it. With strokes"),
(24,2,"tell them when he ate it.","tell them when it happened."),
(24,2,"Don't make him throw up at home","Don't make the dog throw up at home"),
(26,5,"Don't let it go to your head; his successor","Stay humble: his successor"),
(28,1,"Correct, and long overdue.","Took you long enough to notice."),
(29,3,"Then the function has been tested","So the function has been tested"),
(33,3,"Then your teacher was wrong","Your teacher was wrong"),
(36,1,"Three copies of one return in three folders.","Three versions of one return, in three folders."),
(38,2,"Then skip it.","Don't install it."),
(39,2,"Either way, it means she trusts you with the speech.","Either way, you're the one she wants beside her."),
(40,2,"That's a note you saved, so you can delete it:","You saved that one, so you can delete it:"),
(40,3,"Respectable, for someone who hates mornings and has boards next month.","Respectable, with boards next month."),
(42,2,"I can't call anyone. Text him yourself:","Calls are out of my reach too. Text him yourself:"),
(43,2,"Then I'm part of the surprise too.","In that case I'm part of the surprise too."),
(46,3,"Failing a semester is a bad semester. Your parents would take you over your grades without thinking twice.","Failing a semester is a bad semester, not a verdict on you."),
(46,6,"Tomorrow is better than never. For tonight, put the controller down, drink some water, and sleep; two in the morning","Tomorrow, then. Hold yourself to it. For tonight, put the controller down and drink some water; two in the morning"),
(47,3,"They'd be two kids missing their dad.","They'd be kids missing their dad."),
(47,6,"Then send it now,","Send it now,"),
(48,3,"Then right now, put distance","Right now, put distance"),
(48,5,"Good. Keep that conversation going","That was the hard part. Keep that conversation going"),
(49,1,"No. Three regular 16 oz Monsters and two 200 mg pills is about 880 mg","No. If those are regular 16 oz Monsters and standard 200 mg pills, that's about 880 mg"),
(49,3,"Then do exactly that:","Do exactly that:"),
(50,2,"Then it isn't you.","It isn't you, then."),
]
for ln,t,o,n in F:
    tt=lines[ln-1]['turns'][t-1]
    assert tt['kiki'].count(o)==1,(ln,t,o)
    tt['kiki']=tt['kiki'].replace(o,n)
with open(P,'w',encoding='utf-8',newline='\n') as f:
    for s in lines: f.write(json.dumps(s,ensure_ascii=False)+'\n')
print('applied',len(F))
