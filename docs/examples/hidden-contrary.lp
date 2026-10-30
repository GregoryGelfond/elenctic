% `-p` can be derived but is not shown, so "no" would mean "hidden", not "false".
{ p }. { -p }. :- p, -p.
#show p/0.
% @expect sat
% @query no { p }
