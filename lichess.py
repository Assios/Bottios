import requests
import json
import multiprocessing
from multiprocessing import Pool
import engine
import logging_pool
import chess
from keys import AUTHENTICATION_TOKEN
from engine import search_with_time, calculate_move_time
import random
from opening_book import Book
import chess.variant

BASE_URL = 'https://lichess.org/'
BOT_ID = 'bottios'
headers = {'Authorization': 'Bearer %s' % AUTHENTICATION_TOKEN}

standard_book = Book("penguin.book")
atomic_black = Book("atomic_black.book")
atomic_white = Book("atomic_white.book")
threecheck_white = Book("threecheck_white.book")
threecheck_black = Book("threecheck_black.book")

def accept_challenge(game_id):
	print('ACCEPTING_CHALLENGE')
	response = requests.post('https://lichess.org/api/challenge/%s/accept' % (game_id), headers=headers)
	print(f'RESPONSE: {response.status_code}')
	if response.status_code != 200:
		print(f'ERROR: {response.text}')
	try:
		return response.json()
	except:
		return {'error': response.text}

def decline_challenge(game_id, reason='generic'):
	"""
	Decline a challenge with a reason.
	Valid reasons: generic, later, tooFast, tooSlow, timeControl, rated, casual, standard, variant, noBot, onlyBot
	"""
	print(f'DECLINING_CHALLENGE: {reason}')
	response = requests.post(
		'https://lichess.org/api/challenge/%s/decline' % (game_id),
		headers=headers,
		data={'reason': reason}
	)
	print(f'RESPONSE: {response.status_code}')
	return response

def make_move(game_id, move):
	response = requests.post('https://lichess.org/api/bot/game/%s/move/%s' % (game_id, move), headers=headers)
	return response.json()

def game_updates(game_id):
	response = requests.get('https://lichess.org/api/bot/game/stream/%s' % (game_id), headers=headers, stream=True)
	return response

def chat(game_id, txt):
	body = {
		"room": "player",
		"text": txt
	}
	response = requests.post('https://lichess.org/api/bot/game/%s/chat' % (game_id), headers=headers, data=body)
	return response	

def bot_upgrade():
	response = requests.post(BASE_URL + 'bot/account/upgrade', headers=headers)
	return response.json()

def stream_events(event_queue):
	response = requests.get(BASE_URL + 'api/stream/event', headers=headers, stream=True)
	
	for event in response.iter_lines():
		if event:
			event_queue.put_nowait(json.loads(event.decode('utf-8')))
		else:
			event_queue.put_nowait({'type': 'ping'})

def play_game(game_id, event_queue):
	start_color = 1
	my_time = 'btime'
	my_inc = 'binc'
	game_stream = game_updates(game_id).iter_lines()

	print('GAME_STREAM')
	print(game_stream)

	game = json.loads(next(game_stream).decode('utf-8'))
	variant = game['variant']['key']

	in_book = True
	current_book = None
	moves_played = 0

	if variant == 'atomic':
		board = chess.variant.AtomicBoard()
	elif variant == 'antichess':
		board = chess.variant.GiveawayBoard()
	elif variant == 'threeCheck':
		board = chess.variant.ThreeCheckBoard()
	elif variant == 'standard':
		current_book = standard_book
		print("Choosing book standard_book")
		board = chess.Board()
	else:
		print(f"Unknown variant {variant}, defaulting to standard")
		board = chess.Board()

	fens = []

	if game['white']['id'] == BOT_ID:
		start_color = -1
		my_time = 'wtime'
		my_inc = 'winc'

		if variant == 'atomic':
			print("Choosing book atomic_white")
			current_book = atomic_white
		elif variant == 'threeCheck':
			print("Choosing book threecheck_white")
			current_book = threecheck_white

		# Determine first move as white
		if variant == 'antichess':
			bot_move = random.choice(['e2e3', 'b2b3', 'g2g3'])
		elif current_book:
			book_move = current_book.get_moves([])
			bot_move = random.choice(book_move)
		else:
			# Fallback: use engine for first move
			bot_move = search_with_time(board, color=-start_color, variant=variant, time_limit=1.0)

		print(f"First move as white: {bot_move}")
		make_move(game_id, bot_move)
		# Don't push here - we'll sync from game state
		fens.append(board.fen()[:-9].strip())
	elif game['black']['id'] == BOT_ID:
		if variant == 'atomic':
			print("Choosing book atomic_black")
			current_book = atomic_black
		elif variant == 'threeCheck':
			print("Choosing book threecheck_black")
			current_book = threecheck_black

	for event in game_stream:
		try:
			upd = json.loads(event.decode('utf-8')) if event else None
		except json.JSONDecodeError as e:
			print(f"JSON decode error: {e}, event: {event}")
			continue

		_type = upd['type'] if upd else 'ping'

		print(f"Event type: {_type}")

		if _type == 'gameFinish':
			print("Game finished!")
			break

		if (_type == 'gameState'):
			# Check if game has ended
			status = upd.get('status', 'started')
			if status != 'started':
				print(f"Game ended with status: {status}")
				break
			moves_str = upd.get('moves', '')
			moves = moves_str.split(' ') if moves_str else []
			moves = [m for m in moves if m]  # Filter empty strings

			print(f"Game state: {len(moves)} moves played: {moves}")
			print(f"Board has {len(list(board.move_stack))} moves")

			# Sync board with the game state
			# Only push moves we haven't seen yet
			while len(list(board.move_stack)) < len(moves):
				move_idx = len(list(board.move_stack))
				move = chess.Move.from_uci(moves[move_idx])
				board.push(move)
				print(f"Synced move {move_idx}: {move}")

			# Check if it's our turn
			# White moves on even indices (0, 2, 4...), Black on odd (1, 3, 5...)
			is_white = (game['white']['id'] == BOT_ID)
			our_turn = (len(moves) % 2 == 0) if is_white else (len(moves) % 2 == 1)

			print(f"is_white={is_white}, moves_count={len(moves)}, our_turn={our_turn}")

			if not our_turn:
				# Not our turn, wait for opponent
				print("Not our turn, waiting...")
				continue

			moves_played = len(moves) // 2  # Approximate moves by this side

			if (in_book and current_book):
				book_move = current_book.get_moves(moves)
			else:
				book_move = None

			if in_book and not book_move:
				print(in_book)
				chat(game_id, "I'm out of book! :O")
				print("Out of book!")
				in_book = False

			if book_move:
				print("Book moves:")
				print(book_move)
				bot_move = random.choice(book_move)
				bot_move = chess.Move.from_uci(bot_move)
			else:
				# Calculate time for this move based on clock
				time_remaining = upd.get(my_time, 60000)  # Default 60s if missing
				increment = upd.get(my_inc, 0)
				move_time = calculate_move_time(time_remaining, increment, moves_played)
				print(f"Time remaining: {time_remaining/1000:.1f}s, increment: {increment/1000:.1f}s, thinking for: {move_time:.2f}s")

				bot_move = search_with_time(board, color=-start_color, variant=variant, time_limit=move_time)

			print(f"Playing: {bot_move}")

			try:
				response = make_move(game_id, bot_move)
				print(f"Move response: {response}")
				board.push(bot_move)
				fens.append(board.fen()[:-9].strip())
			except Exception as e:
				print(f"Error making move: {e}")
				import traceback
				traceback.print_exc()

if __name__ == '__main__':
	manager = multiprocessing.Manager()
	challenge_queue = []
	event_queue = manager.Queue()

	control_stream = multiprocessing.Process(target=stream_events, args=[event_queue])
	control_stream.start()

	with logging_pool.LoggingPool(10) as pool:
		while True:
			event = event_queue.get()

			if event['type'] == 'challenge':
				challenge = event['challenge']
				_id = challenge['id'].strip()
				variant = challenge['variant']['key']
				challenger = challenge.get('challenger', {})
				challenger_title = challenger.get('title', '')
				challenger_name = challenger.get('name', 'Unknown')
				time_control = challenge.get('timeControl', {})
				speed = challenge.get('speed', 'unknown')

				print(f"Challenge from {challenger_name}: variant={variant}, speed={speed}, time={time_control}")

				# Check if variant is supported
				supported_variants = ['standard', 'atomic', 'antichess', 'threeCheck']
				if variant not in supported_variants:
					print(f"Declining challenge from {challenger_name}: unsupported variant {variant}")
					decline_challenge(_id, reason='variant')
					continue

				# Don't accept challenges from other bots
				if challenger_title == 'BOT':
					print(f"Declining challenge from {challenger_name}: is a BOT")
					decline_challenge(_id, reason='noBot')
					continue

				# Decline ultrabullet - too fast for this bot / not allowed by Lichess
				if speed == 'ultraBullet':
					print(f"Declining challenge from {challenger_name}: ultrabullet too fast")
					decline_challenge(_id, reason='tooFast')
					continue

				print(f"Accepting challenge from {challenger_name} ({variant}, {speed})")
				accept_challenge(_id)

			elif event['type'] == 'gameStart':
				game_id = event['game']['id']
				pool.apply_async(play_game, [game_id, event_queue])

	control_stream.terminate()
	control_stream.join()
