% Two numbers x and y that sum to 3; if `rush` holds, x is at least 2.
% Clingcon is asked for with the annotation below; every answer is a shown set with its assignment.
&dom { 0..3 } = x. &dom { 0..3 } = y. &sum { x ; y } = 3.
{ rush }.
&sum { x } >= 2 :- rush.
#show rush/0.
% @elenctic solver clingcon
% @expect sat
% @count 6
% @assign { x=1, y=2 }
% @answer-set { rush } where { x=2, y=1 }
