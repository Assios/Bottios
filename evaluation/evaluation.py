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

def get_piece_value(piece, variant="standard"):
    piece_score = {
        "p": 100,
        "n": 350,
        "b": 370,
        "r": 525,
        "q": 1000,
        "k": 1000000
    }

    atomic_piece_score = {
        "p": 100,
        "n": 150,
        "b": 150,
        "r": 300,
        "q": 600,
        "k": 1000000
    }

    if variant == "atomic":
        value = atomic_piece_score.get(piece.lower())
    else:
        value = piece_score.get(piece.lower())        

    if (piece.islower()):
        return -value

    return value

def evaluate(node, variant="standard"):
    score = 0

    for field in fields:
        piece = node.piece_at(getattr(chess, field))

        if piece:
            p = str(piece)

            score += get_piece_value(p, variant)
            field_coords = field_to_coords(field)
            piece_value = pst[p.lower()]

            if p.islower():
                piece_value = pst[p][::-1]

            if p.islower():
                score -= piece_value[field_coords[0]][field_coords[1]]
            else:
                score += piece_value[field_coords[0]][field_coords[1]]

    return score
