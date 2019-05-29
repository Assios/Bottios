import chess
from pprint import pprint
from .piece_square_tables import variant_pst

cols = "ABCDEFGH"
rows = "12345678"

def create_fields():
	return [(col + row) for col in cols for row in rows]

fields = create_fields()

def antichess_evaluate(node, color, variant="antichess"):
    pieces = ""

    for field in fields:
        piece = node.piece_at(getattr(chess, field))

        if piece:
            p = str(piece)
            pieces += p

    w_pieces = sum(1 for c in pieces if c.isupper())
    b_pieces = sum(1 for c in pieces if c.islower())

    score = b_pieces - w_pieces

    return score
