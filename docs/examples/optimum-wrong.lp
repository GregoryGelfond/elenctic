% The same knapsack, with two claims that are wrong.
{ a; b; c }.
:- a, b.
#maximize { 3,a : a; 2,b : b; 2,c : c }.
#show a/0. #show b/0. #show c/0.
% @expect sat
% @model optimal { b }
% @cost { 5 }
