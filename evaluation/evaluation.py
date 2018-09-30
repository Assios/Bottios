import chess
from pprint import pprint
from .piece_square_tables import pst

def create_fields():
	return [(col + row) for col in "ABCDEFGH" for row in "12345678"]

fields = create_fields()

def field_to_coords(field):
    x, y = field[0], field[1]

    col = "ABCDEFGH".find(x)
    row = 8 - int(y)

    return(row,col)

def get_piece_value(piece):
    piece_score = {
        "p": 100,
        "n": 288,
        "b": 345,
        "r": 480,
        "q": 1077,
        "k": 1000000
    }

    value = piece_score.get(piece.lower())

    if (piece.islower()):
        return -value

    return value

def evaluate(node):
    score = 0

    for field in fields:
        piece = node.piece_at(getattr(chess, field))

        if piece:
            p = str(piece)

            score += get_piece_value(p)
            field_coords = field_to_coords(field)
            piece_value = pst[p.lower()]

            if p.islower():
                piece_value = pst[p][::-1]

            if p.islower():
                score -= piece_value[field_coords[0]][field_coords[1]]
            else:
                score += piece_value[field_coords[0]][field_coords[1]]

    return score
