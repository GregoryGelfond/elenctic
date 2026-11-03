% A knapsack: take items a, b, c, never a with b, and maximize the value taken.
{ a; b; c }.
:- a, b.
#maximize { 3,a : a; 2,b : b; 2,c : c }.
#show a/0. #show b/0. #show c/0.
% @expect sat
% @count optimal 1
% @answer-set optimal { a, c }
% @cautious optimal { a, c }
% @brave optimal { a, c }
% @cost { -5 }
