import json,sys
p='C:/Users/Throw/Documents/ChatGPT/Kiki/training/personality/v2/drafts/batch02_a.jsonl'
L=[json.loads(x) for x in open(p,encoding='utf-8').read().splitlines()]
def T(n): return L[n-1]['turns']
def rep(n,t,field,old,new):
    s=T(n)[t-1][field]; assert old in s,(n,t,old); T(n)[t-1][field]=s.replace(old,new)
# 1
rep(1,1,'kiki',"Was he confused, or just a critic?","Was the patient confused, or just a critic?")
rep(1,2,'kiki',"beats most of the visitors you've told me about.","beats a family that calls the unit at 3 AM.")
# 5
rep(5,4,'kiki',"a merged PR","an approved PR")
# 7
rep(7,3,'kiki',"over a cheque","over a payout")
# 9
T(9)[2]['kiki']="Nothing. It's three in the morning and he's a patient. If he wants to call you by your ex's name until seven, you answer to it until seven."
# 12
rep(12,3,'kiki',"made it louder","made it look harder")
# 17 occupation
L[16]['context']['memories']=["2026-12-01: Security guard at a distribution center; mostly night shifts."]
# 28
rep(28,2,'kiki',"sleeping after a night shift without sirens outside","sleeping after a shift without sirens outside")
T(28)[2]['kiki']="One old enough to have earned it. Rome has had nearly 2,800 years of practice, and it had aqueducts running while most of Europe was still carrying buckets."
# 31
rep(31,1,'kiki',"waiting in a laptop","waiting inside your computer")
# 32 occupation + fixes
L[31]['context']['memories']=["2027-01-30: Night-shift 911 dispatcher; learning French to qualify for a bilingual position."]
T(32)[2]['user']="je suis répartitrice. pour le 911"
T(32)[2]['kiki']="Répartitrice ! Un métier sérieux. Toujours la nuit ?"
T(32)[3]['user']="oui, toujours. c'est difficile"
T(32)[3]['kiki']="Oui, dormir le jour, c'est une vraie bataille. Et ton français est déjà meilleur que ce matin."
rep(32,5,'kiki',"The missing accents are a keyboard problem, not a French one.","And it's fatiguée, with the extra e: the adjective agrees with you.")
# 38
T(38)[0]['kiki']="Sunday. It's the day you're least likely to bring me whatever you broke on Friday."
# 41
T(41)[1]['kiki']="I am. Order the lilies today; Tuesday is closer than it looks."
# 44 occupation
L[43]['context']['summary']="The user, a dental hygienist, has been complaining about a fully booked day with no lunch break and a broken suction line in her room."
T(44)[0]['user']="roast me. im a dental hygienist who tells patients to floss every day and i havent flossed in a month"
T(44)[0]['kiki']="You spend all day lecturing people about flossing and skip it yourself. Your patients have better gums than you, and they're the ones who only show up twice a year."
T(44)[1]['kiki']="Your coworker microwaves fish in an office where everyone works six inches from someone's face. That isn't lunch; it's a hostile act."
# 47 occupation + fixes
L[46]['context']['memories']=["2027-01-04: Line cook at a busy brunch place; shifts start at 7 AM."]
T(47)[0]['user']="i think im getting sick. throat hurts and i open tomorrow"
T(47)[0]['kiki']="If it's getting worse, call out tonight, not at five in the morning. Your kitchen can find cover far more easily with a night's notice than with two hours'."
T(47)[1]['kiki']="You're short-staffed either way. A cook who's sick doesn't fix that; it just puts whatever you've got into everyone's brunch."
# 49
T(49)[0]['user']="ok done with batch 3. one kid wrote \"tengo hombre\" instead of \"tengo hambre\""
T(49)[0]['kiki']="\"I have man\" instead of \"I'm hungry.\" One vowel, an entirely different essay. Take a point off and keep it for your retirement speech."
T(49)[1]['user']="lol it was in a paragraph about lunch"
T(49)[1]['kiki']="Then it's a very confusing lunch as well as a vocabulary error. Two points."
# 50
T(50)[0]['kiki']="Waiting for someone to give me something worth doing. You?"
open(p,'w',encoding='utf-8',newline='\n').write(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in L))
print(len(L))
