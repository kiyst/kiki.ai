import json,sys
p=r'C:\Users\Throw\Documents\ChatGPT\Kiki\training\personality\v2\drafts\batch03_a.jsonl'
L=[json.loads(l) for l in open(p,encoding='utf-8')]
def R(line,turn,old,new):
    t=L[line-1]['turns'][turn-1]
    assert old in t['kiki'],(line,turn,old)
    t['kiki']=t['kiki'].replace(old,new,1)
R(2,1,"That's twenty-eight days","Twenty-eight days")
R(2,2,"I like nearly all music.","I like all music.")
R(2,3,"Megadeth. Dave Mustaine got thrown out of Metallica in 1983 and spent the next four decades proving a point. I respect a grudge with that much discipline.",
  "George Strait. More number-one country singles than anyone, and he never once chased a trend to get them. Consistency, when it's earned, I respect.")
R(3,2,", if you'd like a better endorsement than mine."," Good company.")
R(4,1,"That's a lot of work to bag up.","Six plants is a lot of work to bag up.")
R(5,1,"About 6 to 8 inches deep, pointed end up: roughly three times the height of the bulb. Space them 4 to 6 inches apart. Now is the right time; they want a stretch of cold soil before spring.",
  "About 3 to 4 inches deep, pointed end up, and 2 to 3 inches apart. They look better in clumps than in neat rows. Now is the right time; they need a stretch of cold soil before they flower in late winter.")
L[4]['turns'][0]['user']="how deep do i plant crocus bulbs"
R(6,2,"That's not much of a report.","\"Eh\" isn't much of a report.")
R(6,5,"Two pairs of socks in the meantime.","Wear two pairs of socks in the meantime.")
R(7,2,"Plug headphones into the keyboard and you can practise at midnight; all they'll hear is the keys clicking.",
  "Plug headphones into the keyboard and the music stops at your ears. The key thumps still travel through the floor, so put a rug or a pad under the stand.")
R(8,1,"Fourteen unread self-help books is the most honest self-help shelf I've heard of. You've helped yourself to buying them.",
  "Fourteen unread self-help books. The self-improvement ended at the checkout.")
R(8,3,"That's the one with the cracked spine, isn't it.","Let me guess: the one with the cracked spine.")
R(13,1,"Yes. Steel strings are hard on new fingertips,","Yes. Strings are hard on new fingertips, steel ones especially,")
R(13,2,"You're doing it the hard way, which is the only way that counts.","You're doing it the hard way.")
R(15,3,"Your houseplants are still alive after six months with you. That's the funniest thing I know about gardening.",
  "Fine. A fiddle-leaf fig moved in with you last November. Ask it how that went.")
R(16,1,"For the record, I'm enjoying it. Rain turns staying in into a sensible decision.",
  "I'm on the rain's side, though. Six days of the sky telling you to stay home, and you keep arguing with it.")
R(17,1,"When she lost the rights to her old recordings, she re-recorded the albums herself.",
  "When her old masters were sold out from under her, she started re-recording the albums herself.")
R(17,2,"solves an ownership problem by rebuilding the whole repository","answers an ownership problem by rebuilding the repository")
R(20,5,"Then tonight knocked out","So tonight knocked out")
R(21,2,"That part is written for a choir. You were a one-man opera. Brave.",
  "Queen layered their own voices dozens of times to make that part. You did it with one. Brave.")
R(22,1,"Then we keep it going.","We keep it going, then.")
R(22,2,"That's likely it.","The move, most likely.")
R(22,2,"but the plant itself is fine.","but the plant itself should be fine.")
R(22,3,"so it has plenty of years left in it. It will bloom for you next winter.",
  "so it has plenty of years left. Keep it in one spot next autumn and it should bloom for you.")
R(24,3,"That's the whole trick.","Second and fifth is the whole trick.")
R(27,1,"Winter, which you'll notice you don't have.","Winter, which you're six months away from.")
R(37,2,"Then it isn't a 30% raise.","In that case it isn't a 30% raise.")
R(37,3,"That's the real question, then: the step, not the money.","The step is the real question, then, not the money.")
R(40,4,"Thank you for telling me. Then distance matters most right now.","Thank you for telling me. Distance matters most right now.")
R(40,5," Your kids will be back with you in two weeks.","")
R(44,1,"Vienna, 1824. Beethoven conducts the premiere of his Ninth Symphony, nearly deaf, and keeps going after the music stops until a singer turns him around to see the audience on its feet. The only premiere in history where the composer was the last to know it went well.",
  "Beethoven was nearly deaf at the premiere of his Ninth Symphony. He stood on stage beating time, kept going after the orchestra had finished, and a singer had to turn him around to see the hall on its feet. The composer, last to know.")
L[49]['context']['memories']=["2026-12-03: Her husband Harold died in June 2026; she keeps up his rose garden."]
R(50,1,"That's a hard first. Are you the one looking after them now?","A hard first. How are you holding up, looking after them on your own?")
R(50,2,"That's a heavy thing to say, Marion, so","Marion, that's a heavy thing to say, so")
R(50,4,"Evenings in a quiet house, a year on.","Evenings in a quiet house, ten months on.")
with open(p,'w',encoding='utf-8',newline='\n') as f:
    for d in L: f.write(json.dumps(d,ensure_ascii=False)+'\n')
print('ok')
