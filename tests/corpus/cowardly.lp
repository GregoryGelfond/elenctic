%% cowardly.lp -- Chpter 5, Section 5.1.2
%% Last Modified: 1/29/14
%% Cowardly Students -- Strong and weak exceptions to defaults:
%%   Normally, students are afraid of math.
%%   Mary is not.
%%   Students in the math department are not.
%%   Those in CS may or may not be afraid.

student(john).  
student(mary).  
student(bob).  
student(pat).

dept(english).  
dept(cs).  
dept(math).

in(john,english).
in(mary,cs).
in(bob,cs).
in(pat,math).

-in(S,D1)  :- dept(D1),
              in(S,D2),
              D1 != D2.
              
afraid(S,math) :- student(S),
                  not ab(d(S)),
                  not -afraid(S,math).

-afraid(mary,math).
ab(d(mary)).

-afraid(S,math) :- in(S,math).
ab(d(S)) :- student(S),
            not -in(S,math).
            
ab(d(S)) :- student(S),
            not -in(S,cs).
            

%% --- elenctic @-contract (Gelfond-Kahl Sec 5.1.2; the program above is verbatim) ---
%% john (english) is afraid by default; mary and pat (math dept) are STRONG exceptions (each refutes
%% the default -> no); bob (CS) is the WEAK exception, "may or may not be" -- the three-valued
%% UNKNOWN the relation vocabulary cannot express.
#show afraid/2.
#show -afraid/2.
% @expect sat
% @query yes { afraid(john,math) }
% @query no { afraid(mary,math) }
% @query no { afraid(pat,math) }
% @query unknown { afraid(bob,math) }
% @note Strong and weak exceptions; bob is the entertained-but-unsettled case.
