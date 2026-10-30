% Cautious and brave consequences are computed by the solver; no answer set is enumerated.
{ p(1..40) }. q.
% @expect sat
% @cautious { q }
% @brave { p(7) }
% @cautious { p(1) }
