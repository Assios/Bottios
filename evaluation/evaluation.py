import chess
from .piece_square_tables import (
    PST_WHITE, PST_BLACK, PIECE_VALUES, ATOMIC_PIECE_VALUES, variant_pst
)

def evaluate(node, color, variant="standard"):
    """
    Optimized evaluation function.
    Uses piece_map() and pre-computed PST lookups for speed.
    """
    score = 0

    # Select the right piece values and PSTs for this variant
    if variant == "atomic":
        piece_values = ATOMIC_PIECE_VALUES
    else:
        piece_values = PIECE_VALUES

    pst_white = PST_WHITE[variant]
    pst_black = PST_BLACK[variant]

    # Use piece_map() - only iterates over squares with pieces
    for square, piece in node.piece_map().items():
        piece_type = piece.piece_type

        if piece.color == chess.WHITE:
            # White piece: add material and PST value
            score += piece_values[piece_type]
            score += pst_white[piece_type][square]
        else:
            # Black piece: subtract material and PST value
            score -= piece_values[piece_type]
            score -= pst_black[piece_type][square]

    # Atomic variant: penalize king safety (attackers near enemy king)
    if variant == "atomic":
        score += _atomic_king_safety(node, color)

    return score


def _atomic_king_safety(node, color):
    """Evaluate king safety for atomic chess (attackers near enemy king)."""
    score = 0

    # Find enemy king
    if color == 1:  # We are white, check black king safety
        enemy_king_sq = node.king(chess.BLACK)
        if enemy_king_sq is not None:
            # Count white attackers on squares adjacent to black king
            for adj_sq in _get_adjacent_squares_fast(enemy_king_sq):
                attackers = len(node.attackers(chess.WHITE, adj_sq))
                score += 200 * attackers
    else:  # We are black, check white king safety
        enemy_king_sq = node.king(chess.WHITE)
        if enemy_king_sq is not None:
            for adj_sq in _get_adjacent_squares_fast(enemy_king_sq):
                attackers = len(node.attackers(chess.BLACK, adj_sq))
                score -= 200 * attackers

    return score


# Pre-computed adjacent squares for each square (0-63)
_ADJACENT_SQUARES = []
for sq in range(64):
    file = sq % 8
    rank = sq // 8
    adj = []
    for df in [-1, 0, 1]:
        for dr in [-1, 0, 1]:
            if df == 0 and dr == 0:
                continue
            nf, nr = file + df, rank + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                adj.append(nr * 8 + nf)
    _ADJACENT_SQUARES.append(tuple(adj))
_ADJACENT_SQUARES = tuple(_ADJACENT_SQUARES)


def _get_adjacent_squares_fast(square):
    """Get adjacent squares using pre-computed lookup."""
    return _ADJACENT_SQUARES[square]


# Keep old functions for backwards compatibility if needed elsewhere
def get_piece_value(piece, variant="standard"):
    """Legacy function for backwards compatibility."""
    piece_score = {"p": 100, "n": 350, "b": 370, "r": 525, "q": 1000, "k": 1000000}
    atomic_piece_score = {"p": 100, "n": 150, "b": 150, "r": 300, "q": 600, "k": 1000000}

    if variant == "atomic":
        value = atomic_piece_score.get(piece.lower())
    else:
        value = piece_score.get(piece.lower())

    return -value if piece.islower() else value
