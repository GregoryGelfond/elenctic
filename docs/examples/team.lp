% Pick a team of two or three; bob and cy refuse to work together.
% A team is balanced when it has at least two seniors; we expect every team to be balanced.
cand(ann;bob;cy;dee). senior(ann;dee).
2 { team(P) : cand(P) } 3.
:- team(bob), team(cy).
seniors(N) :- N = #count { P : team(P), senior(P) }.
balanced :- seniors(N), N >= 2.
#show team/1. #show balanced/0.
% @expect sat
% @cautious { balanced }
