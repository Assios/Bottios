from collections import defaultdict
from functools import reduce
import operator
import json
from pprint import pprint
import chess
import chess.pgn
import re

def tree(): return defaultdict(tree)
def dicts(tree): return {k: dicts(tree[k]) for k in tree}


def reformat(pgn):
	"""
	If it is on the format 1. e4 c5 2. Nf3 d6 etc
	"""
	moves = re.sub(r'(\d)+\.', '', pgn).strip()
	return [move for move in moves.split(' ') if move]


def create_book_from_pgn(pgn, outfile):
	pgn = open('zergei_3check_white.pgn')
	game = chess.pgn.read_game(pgn)

	out = open(outfile, "a")

	c = 0

	while game:
		print(c)
		c+=1
		moves = game.mainline_moves()
		opening_line = ' '.join([str(move) for move in moves][:60])
		print(opening_line)
		out.write(opening_line + "\n")
		game = chess.pgn.read_game(pgn)


class Book():
	def __init__(self, _file):		
		with open('books/' + _file) as f:
			openings = f.readlines()
		openings = [reformat(opening) for opening in openings]

		self.book = tree()

		for line in openings:
			self.add_line(self.book, line)

		self.book_dict = dicts(self.book)

	def add_line(self, tree, path):
		if isinstance(path, str):
			path = path.split(' ')

		for node in path:
			tree = tree[node]

	def get_moves(self, game):
		book_copy = self.book_dict

		for move in game:
			book_copy = book_copy.get(move, None)
			if book_copy is None:
				return []

		try:
			return list(book_copy.keys())
		except:
			return []


if __name__ == '__main__':
	create_book_from_pgn("", "zergei_white_2check.book")

