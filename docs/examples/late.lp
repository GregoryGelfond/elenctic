% Two jobs on one machine: job 1 takes 3 hours and runs before job 2.
% Job 2 is late if it starts at 7 or later; we expect it never to be late.
&dom { 0..9 } = s1. &dom { 0..9 } = s2.
&sum { s1 ; 3 } <= s2.
late :- &sum { s2 } >= 7.
#show late/0.
% @elenctic solver clingcon
% @expect sat
% @query no { late }
