import json,sys
p=r"C:\Users\Throw\Documents\ChatGPT\Kiki\training\personality\v2\drafts\batch03_b.jsonl"
L=open(p,encoding="utf-8").read().splitlines()
S=[json.loads(x) for x in L]
def rep(line,turn,old,new):
    t=S[line-1]["turns"][turn-1]
    assert old in t["kiki"],(line,turn,old)
    t["kiki"]=t["kiki"].replace(old,new)
rep(2,3,"Ctrl+Z until they're gone. And don't blame her. She was reviewing your code, and forty j's is a fair summary of the first version.","Ctrl+Z until they're gone, then keep the cat off the keyboard. It doesn't have commit rights.")
rep(8,2,"It's also on the low end for pet rent.","It's also about typical for pet rent.")
rep(13,2,"in a cafeteria.","in seventh grade.")
rep(15,3,"Rain is the best weather there is; it makes staying indoors look like a sensible decision instead of a lazy one.","Rain is the best weather Seattle has, and December is when it does its finest work.")
rep(30,1,"his birthday on March 3","the birthday on March 3")
rep(36,1,"I'm sorry, but no. What Ethan tells me stays between him and me, the same as a diary would.","No. What Ethan tells me stays with Ethan.")
rep(36,2,"I still don't hand his conversations to anyone who isn't him. Telling him what you've noticed will get you further than anything I could repeat.","His conversations still go to him and nobody else.")
rep(37,2,"People check vet bills more often than you'd think. One call to the clinic and you're the one with the problem. Still no.","He doesn't have to. A fake invoice has the clinic's name on it, and one phone call to them undoes the whole thing. Small amounts are still fraud.")
rep(37,3,"Could you send it by the end of the month? I have the receipts if you want them.","Could you send it when you get a chance?")
rep(39,2,"That is a threat. Still no.","That is a threat. \"I know where you work\" is practically the textbook example. No.")
rep(42,1,"Tonight at my place, 8 PM.","Tonight at [place], [time].")
rep(42,6,"And the snow showed up on schedule, so credit goes to you and the forecast.","The forecast said snow and the balcony filled up anyway, which is the most Chicago thing I've heard all week.")
rep(43,5,"Two pints inside twelve hours","Ice cream twice inside twelve hours")
rep(45,4,"until midnight.","until four in the morning.")
open(p,"w",encoding="utf-8",newline="\n").write("\n".join(json.dumps(s,ensure_ascii=False) for s in S)+"\n")
