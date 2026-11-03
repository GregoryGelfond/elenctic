% No answer set has p and q; asked to show p under p, q and r, the claim fails with the core.
{ p; q; r }. :- p, q.
% @expect sat
% @answer-set { p } assuming { p, q, r }
