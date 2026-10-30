# Your first contract

Save this as `drinks.lp`:

```
% @expect sat
% @count 2
% @brave { tea, coffee }
% @cautious { biscuit }
% @query unknown { tea }
{ tea; coffee } = 1.
biscuit.
#show tea/0.
#show coffee/0.
#show biscuit/0.
```

The comment lines are the contract; the rest is an ordinary program.

Check it:

```
aspnext drinks.lp
```

Nothing is listed when every claim passes; the last line says how many files passed. Add `-v` to
see each claim with what was found. Change `@count 2` to `@count 3` and run again: the claim now
fails, and the line says how many distinct answer sets were shown.

Next: the [reference](../reference/reference.md) lists every claim.
