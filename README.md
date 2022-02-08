# Bottios 

<img width="794" alt="screen shot 2018-10-03 at 22 42 17" src="https://user-images.githubusercontent.com/1413265/46438868-4f3cb800-c75f-11e8-9e4c-21f70bc1b1f5.png">

Bottios is a simple chess engine [playing on Lichess](https://lichess.org/@/Bottios). It relies on `python-chess` for move generation and features a negamax search with alpha-beta pruning. It currently plays Standard chess, Atomic chess, Antichess and Three-check.

### Opening book

Bottios can play with an opening book, but doesn't support transposition, i.e. it won't recognize an opening if the position is reached from other lines than what's stored in the book. On Lichess, Bottios usually plays with an opening book based on all 32K Lichess games played by [GM Andrew Tang](https://lichess.org/@/penguingm1).

### Variants

Bottios can currently play Standard chess, Atomic chess, Antichess and Three-check, but I'm planning to add support for all chess variants available on Lichess.
