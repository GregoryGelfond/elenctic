% Roads between depots; the road b-c is closed, so c and d should be cut off from a.
edge(a,b). edge(b,c). edge(c,d).
closed(b,c).
maintenance(b).
open(X,Y) :- edge(X,Y), not closed(X,Y).
open(X,Y) :- edge(X,Y), maintenance(X).
reach(a).
reach(Y) :- reach(X), open(X,Y).
#show reach/1.
% @expect sat
% @query no { reach(c), reach(d) }
