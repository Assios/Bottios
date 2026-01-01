import chess
import chess.polyglot
import time
from evaluation.evaluation import *
from evaluation.antichess_eval import antichess_evaluate
from evaluation.threecheck_eval import threecheck_eval
from opening_book import Book
import pickle
import random
import pprint
import chess.variant

inf = float('inf')
poscount = 0
qnodes = 0  # Quiescence nodes
tt_hits = 0

DEPTH = 2
MAX_QUIESCE_DEPTH = 10  # Limit quiescence search depth
MAX_KILLER_PLY = 64  # Maximum ply for killer moves

# Transposition table entry types
EXACT = 0      # Exact score
LOWERBOUND = 1 # Score is at least this (beta cutoff)
UPPERBOUND = 2 # Score is at most this (failed to raise alpha)

# Transposition table: zobrist_hash -> (depth, score, flag, best_move)
transposition_table = {}
TT_SIZE = 1000000  # Max entries

# Killer moves: store 2 killer moves per ply
# killer_moves[ply] = [move1, move2]
killer_moves = [[None, None] for _ in range(MAX_KILLER_PLY)]

# Piece values for MVV-LVA move ordering
PIECE_VALUES = {
	chess.PAWN: 100,
	chess.KNIGHT: 320,
	chess.BISHOP: 330,
	chess.ROOK: 500,
	chess.QUEEN: 900,
	chess.KING: 20000
}

def mvv_lva_score(board, move):
	"""Most Valuable Victim - Least Valuable Attacker scoring for move ordering."""
	score = 0

	# Captures: prioritize capturing high-value pieces with low-value pieces
	if board.is_capture(move):
		victim = board.piece_at(move.to_square)
		attacker = board.piece_at(move.from_square)
		if victim:
			score += 10 * PIECE_VALUES.get(victim.piece_type, 0)
		if attacker:
			score -= PIECE_VALUES.get(attacker.piece_type, 0)

	# Promotions are valuable
	if move.promotion:
		score += PIECE_VALUES.get(move.promotion, 0)

	return score

def store_killer(move, ply):
	"""Store a killer move at the given ply."""
	if ply >= MAX_KILLER_PLY:
		return
	# Don't store if it's already the first killer
	if killer_moves[ply][0] == move:
		return
	# Shift: move current first killer to second slot
	killer_moves[ply][1] = killer_moves[ply][0]
	killer_moves[ply][0] = move

def order_moves(board, moves, pv_move=None, tt_move=None, ply=0):
	"""Order moves for better alpha-beta pruning."""
	killers = killer_moves[ply] if ply < MAX_KILLER_PLY else [None, None]

	def move_score(move):
		# PV move from previous iteration gets highest priority
		if pv_move and move == pv_move:
			return 100000
		# TT move (from transposition table) gets second priority
		if tt_move and move == tt_move:
			return 90000
		# Captures scored by MVV-LVA (will be 100-9000 range typically)
		if board.is_capture(move):
			return 10000 + mvv_lva_score(board, move)
		# Killer moves get priority after captures
		if move == killers[0]:
			return 9000
		if move == killers[1]:
			return 8000
		# Promotions are good
		if move.promotion:
			return 7000 + PIECE_VALUES.get(move.promotion, 0)
		return 0

	return sorted(moves, key=move_score, reverse=True)

def get_static_eval(node, color, variant):
	"""Get static evaluation for the position."""
	if variant == "antichess":
		return antichess_evaluate(node, color, variant) * color
	if variant == "threeCheck":
		return threecheck_eval(node, color, variant) * color
	return evaluate(node, color, variant) * color

def quiesce(node, a, b, color, variant, qdepth=0):
	"""
	Quiescence search - continue searching captures until position is quiet.
	This avoids the horizon effect where we evaluate mid-capture.
	"""
	global qnodes, tt_hits, transposition_table

	# TT lookup for quiescence (use negative depth to distinguish from main search)
	pos_hash = chess.polyglot.zobrist_hash(node)
	q_depth_key = -qdepth - 1  # -1, -2, -3... for quiescence depths
	if pos_hash in transposition_table:
		tt_entry = transposition_table[pos_hash]
		tt_depth, tt_score, tt_flag, _ = tt_entry
		# Only use TT if it was from same or deeper quiescence search
		if tt_depth <= q_depth_key:
			tt_hits += 1
			if tt_flag == EXACT:
				return tt_score
			elif tt_flag == LOWERBOUND:
				a = max(a, tt_score)
			elif tt_flag == UPPERBOUND:
				b = min(b, tt_score)
			if a >= b:
				return tt_score

	# Check for game end
	if node.is_checkmate():
		return -inf
	if node.is_stalemate() or node.can_claim_draw():
		return 0
	if node.is_variant_end():
		return get_static_eval(node, color, variant)

	# Stand pat: evaluate current position
	# The side to move can choose to not capture
	stand_pat = get_static_eval(node, color, variant)

	if stand_pat >= b:
		return b  # Beta cutoff
	if stand_pat > a:
		a = stand_pat

	# Limit quiescence depth
	if qdepth >= MAX_QUIESCE_DEPTH:
		return stand_pat

	# Generate and search only captures (and promotions)
	captures = [m for m in node.legal_moves if node.is_capture(m) or m.promotion]

	if not captures:
		return stand_pat

	# Order captures by MVV-LVA
	captures = sorted(captures, key=lambda m: mvv_lva_score(node, m), reverse=True)

	alpha_orig = a
	best_score = stand_pat

	for move in captures:
		qnodes += 1
		node.push(move)
		score = -quiesce(node, -b, -a, -color, variant, qdepth + 1)
		node.pop()

		if score > best_score:
			best_score = score

		if score >= b:
			# Store in TT before returning
			transposition_table[pos_hash] = (q_depth_key, score, LOWERBOUND, None)
			return b  # Beta cutoff
		if score > a:
			a = score

	# Store result in TT
	if best_score <= alpha_orig:
		tt_flag = UPPERBOUND
	elif best_score >= b:
		tt_flag = LOWERBOUND
	else:
		tt_flag = EXACT
	transposition_table[pos_hash] = (q_depth_key, best_score, tt_flag, None)

	return a

def clear_killers():
	"""Clear killer moves table."""
	global killer_moves
	for i in range(MAX_KILLER_PLY):
		killer_moves[i] = [None, None]

def search(node, color, variant, depth):
	"""Iterative deepening search to fixed depth."""
	global poscount, qnodes, tt_hits, transposition_table
	poscount = 0
	qnodes = 0
	tt_hits = 0
	clear_killers()
	# Keep TT between depths for iterative deepening (don't clear it)

	moves = list(node.legal_moves)
	if not moves:
		print('Game over.')
		return

	best_move = None

	# Iterative deepening: search depth 1, then 2, ..., up to target depth
	for current_depth in range(1, depth + 1):
		nodes_before = poscount
		qnodes_before = qnodes
		hits_before = tt_hits
		result = negamax(node, -inf, inf, color, variant, current_depth, pv_move=best_move)
		best_move = result[1]
		nodes_this_depth = poscount - nodes_before
		qnodes_this_depth = qnodes - qnodes_before
		hits_this_depth = tt_hits - hits_before
		print(f"depth {current_depth}: {best_move} (score: {result[0]}, nodes: {nodes_this_depth}, qnodes: {qnodes_this_depth}, tt_hits: {hits_this_depth})")

	print(f"total nodes: {poscount}, qnodes: {qnodes}, tt_hits: {tt_hits}, tt_size: {len(transposition_table)}")
	if not best_move:
		return random.choice(moves)
	return best_move


def calculate_move_time(time_remaining_ms, increment_ms=0, moves_played=0):
	"""
	Calculate how much time to spend on this move.

	Args:
		time_remaining_ms: Time remaining on clock in milliseconds
		increment_ms: Increment per move in milliseconds
		moves_played: Number of moves played so far (for time distribution)

	Returns:
		Time to spend on this move in seconds
	"""
	# Network latency buffer - reserve time for API calls
	# Lichess API calls typically take 100-500ms
	NETWORK_BUFFER = 0.5  # seconds

	# Convert to seconds
	time_remaining = time_remaining_ms / 1000.0
	increment = increment_ms / 1000.0

	# Reserve time for network latency
	usable_time = max(0.1, time_remaining - NETWORK_BUFFER)

	# Estimate moves remaining in game (fewer pieces = fewer moves expected)
	# Use a simple model: expect ~40 moves total, adjust based on moves played
	if moves_played < 10:
		# Opening: save time, expect many moves ahead
		expected_moves_left = 35
	elif moves_played < 30:
		# Middlegame: use more time for complex positions
		expected_moves_left = 25
	else:
		# Endgame: fewer moves expected
		expected_moves_left = 15

	# Base time per move (use usable_time, not raw time_remaining)
	base_time = usable_time / expected_moves_left

	# Add a portion of increment (save some for safety)
	time_with_increment = base_time + (increment * 0.8)

	# Safety margins
	min_time = 0.1  # Never spend less than 100ms
	max_time = usable_time * 0.3  # Never spend more than 30% of usable time

	# In very low time, just move fast
	if time_remaining < 5:
		# Even faster moves in time trouble, leave buffer for network
		return max(0.05, (time_remaining - NETWORK_BUFFER) * 0.1)

	return max(min_time, min(max_time, time_with_increment))


def search_with_time(node, color, variant, time_limit, min_depth=1, max_depth=20):
	"""
	Iterative deepening search with time limit.
	Searches until time runs out, returns best move from last completed depth.

	Args:
		node: Board position
		color: Side to move (1=white, -1=black)
		variant: Chess variant
		time_limit: Maximum time to search in seconds
		min_depth: Minimum depth to search (default 1)
		max_depth: Maximum depth to search (default 20)

	Returns:
		Best move found
	"""
	global poscount, qnodes, tt_hits, transposition_table
	poscount = 0
	qnodes = 0
	tt_hits = 0
	clear_killers()

	start_time = time.time()

	moves = list(node.legal_moves)
	if not moves:
		print('Game over.')
		return None

	if len(moves) == 1:
		# Only one legal move, just play it
		print(f"Only one legal move: {moves[0]}")
		return moves[0]

	best_move = None
	best_score = -inf
	completed_depth = 0

	last_depth_time = 0

	for current_depth in range(1, max_depth + 1):
		elapsed = time.time() - start_time
		time_remaining = time_limit - elapsed

		# Estimate time for next depth based on last depth (branching factor ~6-8x)
		# Be conservative: assume next depth takes 8x longer
		estimated_next_time = last_depth_time * 8 if last_depth_time > 0 else 0

		# Don't start a new depth if:
		# 1. We've passed minimum depth AND
		# 2. We estimate we won't finish in time
		if current_depth > min_depth and estimated_next_time > time_remaining:
			print(f"Stopping: estimated {estimated_next_time:.1f}s for depth {current_depth}, only {time_remaining:.1f}s remaining")
			break

		nodes_before = poscount
		depth_start = time.time()

		result = negamax(node, -inf, inf, color, variant, current_depth, pv_move=best_move)

		depth_time = time.time() - depth_start
		last_depth_time = depth_time
		elapsed = time.time() - start_time

		# Only update best move if we completed this depth
		if result[1] is not None:
			best_move = result[1]
			best_score = result[0]
			completed_depth = current_depth

			nodes_this_depth = poscount - nodes_before
			print(f"depth {current_depth}: {best_move} (score: {best_score:.1f}, nodes: {nodes_this_depth}, time: {depth_time:.2f}s, total: {elapsed:.2f}s)")

		# Hard stop if we've exceeded time limit
		if elapsed >= time_limit:
			print(f"Time limit reached after depth {current_depth}")
			break

		# Check for forced mate - no need to search deeper
		if abs(best_score) > 100000:
			print(f"Mate found at depth {current_depth}")
			break

	total_time = time.time() - start_time
	print(f"Search complete: depth {completed_depth}, nodes: {poscount}, qnodes: {qnodes}, time: {total_time:.2f}s")

	if not best_move:
		return random.choice(moves)
	return best_move

def negamax(node, a, b, color, variant, depth=DEPTH, ply=0, pv_move=None, null_move_allowed=True):
	global poscount, tt_hits, transposition_table

	alpha_orig = a

	# Transposition table lookup
	pos_hash = chess.polyglot.zobrist_hash(node)
	tt_move = None
	if pos_hash in transposition_table:
		tt_entry = transposition_table[pos_hash]
		tt_depth, tt_score, tt_flag, tt_move = tt_entry

		if tt_depth >= depth:
			tt_hits += 1
			if tt_flag == EXACT:
				return (tt_score, tt_move)
			elif tt_flag == LOWERBOUND:
				a = max(a, tt_score)
			elif tt_flag == UPPERBOUND:
				b = min(b, tt_score)

			if a >= b:
				return (tt_score, tt_move)

	if node.is_checkmate():
		return (-inf, None)

	if node.is_stalemate():
		return (0, None)

	# Handle draws (threefold repetition, 50-move rule)
	# Use contempt: if we're ahead, a draw is bad; if we're behind, a draw is good
	if node.can_claim_draw():
		# Get static evaluation to determine if we're winning or losing
		static_eval = get_static_eval(node, color, variant)
		if static_eval > 100:
			# We're winning - a draw is bad, penalize it heavily
			return (-200, None)
		elif static_eval < -100:
			# We're losing - a draw is good
			return (200, None)
		else:
			# Roughly equal - draw is fine
			return (0, None)

	if (depth <= 1 and node.is_check()):
		depth += 1

	if node.is_variant_end():
		return (get_static_eval(node, color, variant), None)

	if depth == 0:
		# Use quiescence search instead of static eval
		return (quiesce(node, a, b, color, variant), None)

	# Null move pruning
	# Skip if: in check, low depth, or null move not allowed (to prevent consecutive nulls)
	# Also skip in antichess (zugzwang is common) and when we have few pieces
	# Skip at root (ply == 0) or when beta is inf (no bound to beat)
	in_check = node.is_check()
	if (null_move_allowed and not in_check and depth >= 3 and ply > 0 and
		variant != "antichess" and len(node.piece_map()) > 6 and b < inf):
		# Reduction: R = 2 + depth/4 (adaptive)
		R = 2 + depth // 4
		# Make null move
		node.push(chess.Move.null())
		# Search with reduced depth and null window
		null_score = -negamax(node, -b, -b + 1, -color, variant, depth - 1 - R, ply + 1,
							  null_move_allowed=False)[0]
		node.pop()

		# If null move fails high, we can prune
		if null_score >= b:
			return (b, None)

	moves = list(node.legal_moves)
	moves = order_moves(node, moves, pv_move, tt_move, ply)

	best_move = None
	best_value = -inf
	moves_searched = 0

	for move in moves:
		poscount += 1
		is_capture = node.is_capture(move)
		is_promotion = move.promotion is not None

		node.push(move)
		gives_check = node.is_check()

		# Late Move Reductions (LMR)
		# For later moves that aren't tactical, search at reduced depth first
		do_full_search = True
		if (moves_searched >= 4 and depth >= 3 and
			not is_capture and not is_promotion and not gives_check and not in_check):
			# Reduction amount: more reduction for later moves and higher depths
			reduction = 1 + (moves_searched // 8) + (depth // 4)
			reduction = min(reduction, depth - 1)  # Don't reduce below depth 1

			# Reduced depth search with null window
			result = negamax(node, -a - 1, -a, -color, variant, depth - 1 - reduction, ply + 1)
			value = -result[0]

			# If reduced search doesn't fail low, we need full re-search
			do_full_search = (value > a)

		if do_full_search:
			# Principal Variation Search (PVS): use null window after first move
			if moves_searched == 0:
				result = negamax(node, -b, -a, -color, variant, depth - 1, ply + 1)
				value = -result[0]
			else:
				# Null window search
				result = negamax(node, -a - 1, -a, -color, variant, depth - 1, ply + 1)
				value = -result[0]
				# Re-search with full window if it might improve alpha
				if value > a and value < b:
					result = negamax(node, -b, -a, -color, variant, depth - 1, ply + 1)
					value = -result[0]

		node.pop()
		moves_searched += 1

		if value > best_value:
			best_value = value
			best_move = move

		a = max(a, value)

		if a >= b:
			# Beta cutoff - store killer move if it's not a capture
			if not is_capture:
				store_killer(move, ply)
			break

	# Store in transposition table
	# Replacement strategy: always replace if deeper or same depth
	if best_value <= alpha_orig:
		tt_flag = UPPERBOUND
	elif best_value >= b:
		tt_flag = LOWERBOUND
	else:
		tt_flag = EXACT

	# Check if we should store
	should_store = True
	if pos_hash in transposition_table:
		existing_depth = transposition_table[pos_hash][0]
		# Only replace if our search is at least as deep
		should_store = depth >= existing_depth
	elif len(transposition_table) >= TT_SIZE:
		# Table full - find and replace shallowest entry (simple approach)
		# For better performance, could use a more sophisticated scheme
		should_store = True  # Always try to store, will evict oldest

	if should_store:
		# If table is full, remove a random entry to make room
		if len(transposition_table) >= TT_SIZE:
			# Simple eviction: remove first item (approximates FIFO)
			try:
				first_key = next(iter(transposition_table))
				del transposition_table[first_key]
			except StopIteration:
				pass
		transposition_table[pos_hash] = (depth, best_value, tt_flag, best_move)

	return (best_value, best_move)


if __name__ == "__main__":
	board = chess.Board()
	moves = []

	c = 0
	while not board.is_game_over():
		if c%2==0:
			move = input("move: \n\n")
			move = chess.Move.from_uci(move)
			if not move in board.legal_moves:
				continue
		else:
			start_time = time.time()
			move = search(board, color=-1, variant="standard", depth=4)
			elapsed = time.time() - start_time
			print("--- %s moves ---" % (len(list(board.legal_moves))))
			print("--- number of nodes: %s --" % poscount)
			print("--- %s seconds ---" % (elapsed))
			if elapsed > 0:
				print("--- nodes per second: %s ---" % str(poscount / elapsed))

		print(move)
		moves.append(str(move))
		board.push(move)
		c+=1
