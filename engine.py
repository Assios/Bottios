import chess
import time
from evaluation import *
from opening_book import Book
import pickle
import lichess
import random

inf = float('inf')
poscount = 0

DEPTH = 3
book = Book("penguin.book")

def search(node, color, variant, depth):
	moves = list(node.legal_moves)

	if not moves:
		print('Game over.')
		return

	move = negamax(node, -inf, inf, color, variant, depth)[1]

	if not move:
		return random.choice(moves)
	else:
		return move

def negamax(node, a, b, color, variant, depth=DEPTH):
	global poscount

	if node.is_checkmate():
		return (-inf, None)

	if (depth == 0):
		return (evaluate(node, variant) * color, None)

	moves = list(node.legal_moves)

	best_move = None
	best_value = -inf

	for move in moves:
		poscount+=1
		node.push(move)
		result = negamax(node, -b, -a, -color, variant, depth-1)

		value = -result[0]

		node.pop()
		if value > best_value:
			best_value = value
			best_move = move

		a = max(a, value)

		if a >= b:
			break

	return (best_value, best_move)


if __name__ == "__main__":
	board = chess.Board()
	moves = []
	book = None
	#pickle.dump(book, open("penguinbook.p", "wb"))

	c = 0
	while not board.is_game_over():
		if c%2==0:
			move = input("move: \n\n")
			move = chess.Move.from_uci(move)
			if not move in board.legal_moves:
				continue
		else:
			start_time = time.time()

			#book_move = book.get_moves(moves)
			book_move = None
			if book_move:
				move = random.choice(book_move)
				move = chess.Move.from_uci(move)
			else:
				(value, move) = negamax(board, -inf, inf, -1, "standard", DEPTH)
				print(move)
			elapsed = time.time() - start_time
			print("--- %s moves ---" % (len(board.legal_moves)))
			print("--- number of nodes: %s --" % poscount)
			print("--- %s seconds ---" % (elapsed))
			print("--- nodes per second: %s ---" % str(poscount / elapsed))

		print(move)
		moves.append(str(move))
		board.push(move)
		c+=1
