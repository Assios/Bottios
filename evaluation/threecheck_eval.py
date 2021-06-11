import chess
from pprint import pprint
from .piece_square_tables import variant_pst

cols = "ABCDEFGH"
rows = "12345678"

def create_fields():
	return [(col + row) for col in cols for row in rows]

fields = create_fields()

def field_to_coords(field):
    x, y = field[0], field[1]

    col = "ABCDEFGH".find(x)
    row = 8 - int(y)

    return(row,col) 

def get_piece_value(piece, variant="threecheck"):
    piece_score = {
        "p": 100,
        "n": 350,
        "b": 370,
        "r": 525,
        "q": 1000,
        "k": 1000000
    }

    value = piece_score.get(piece.lower())        

    if (piece.islower()):
        return -value

    return value

def threecheck_eval(node, color, variant="standard"):
    score = 0

    if (color == 1):
        if node.remaining_checks[chess.WHITE] == 1:
            score += 2400
        if node.remaining_checks[chess.WHITE] == 2:
            score += 444

        if (node.remaining_checks[chess.WHITE] == 0):
            score += 1000000

        if node.remaining_checks[chess.BLACK] == 1:
            score -= 2400
        if node.remaining_checks[chess.BLACK] == 2:
            score -= 444

        if (node.remaining_checks[chess.BLACK] == 0):
            score -= 1000000       

    elif (color == 0):
        if node.remaining_checks[chess.BLACK] == 1:
            score += 2400
        if node.remaining_checks[chess.BLACK] == 2:
            score += 444

        if (node.remaining_checks[chess.BLACK] == 0):
            score += 1000000

        if node.remaining_checks[chess.WHITE] == 1:
            score -= 2400
        if node.remaining_checks[chess.WHITE] == 2:
            score -= 444

        if (node.remaining_checks[chess.WHITE] == 0):
            score -= 1000000         

    for field in fields:
        piece = node.piece_at(getattr(chess, field))

        if piece:
            p = str(piece)

            score += get_piece_value(p, variant)
            field_coords = field_to_coords(field)

            piece_value = variant_pst[variant][p.lower()]

            if p.islower():
                piece_value = variant_pst[variant][p][::-1]

            if p.islower():
                score -= piece_value[field_coords[0]][field_coords[1]]
            else:
                score += piece_value[field_coords[0]][field_coords[1]]

    return score

