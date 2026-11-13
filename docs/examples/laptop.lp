% Configure a laptop; first avoid a heavy build, then minimize the price.
% We expect the cheapest configuration to have 32 GB of memory.
1 { ram(16;32) } 1.
1 { disk(512;1024) } 1.
heavy :- ram(32), disk(1024).
#minimize { 1@2 : heavy }.
#minimize { 150@1,ram : ram(16); 300@1,ram : ram(32);
            80@1,disk : disk(512); 120@1,disk : disk(1024) }.
#show ram/1. #show disk/1.
% @expect sat
% @cautious optimal { ram(32) }
