import requests
import json
import multiprocessing
from multiprocessing import Pool
import queue
import time
import signal
import sys
import logging
import engine
import logging_pool
import chess
from keys import AUTHENTICATION_TOKEN
from engine import search_with_time, calculate_move_time
import random
from opening_book import Book
import chess.variant

# Configure logging
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s [%(levelname)s] %(message)s',
	datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

BASE_URL = 'https://lichess.org/'
BOT_ID = 'bottios'
headers = {'Authorization': 'Bearer %s' % AUTHENTICATION_TOKEN}

# Configuration
MAX_CONCURRENT_GAMES = 5
REQUEST_TIMEOUT = 30  # seconds
RATE_LIMIT_WAIT = 60  # seconds to wait after 429

# Track active games
active_games = set()


def api_request(method, url, max_retries=3, **kwargs):
	"""Make an API request with timeout, retry logic, and rate limit handling."""
	kwargs.setdefault('timeout', REQUEST_TIMEOUT)
	kwargs.setdefault('headers', headers)

	for attempt in range(max_retries):
		try:
			if method == 'GET':
				response = requests.get(url, **kwargs)
			else:
				response = requests.post(url, **kwargs)

			if response.status_code == 429:
				logger.warning(f"Rate limited (429), waiting {RATE_LIMIT_WAIT}s before retry...")
				time.sleep(RATE_LIMIT_WAIT)
				continue

			return response

		except requests.exceptions.Timeout:
			logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries}): {url}")
			if attempt < max_retries - 1:
				time.sleep(2 ** attempt)  # Exponential backoff
		except requests.exceptions.ConnectionError as e:
			logger.warning(f"Connection error (attempt {attempt + 1}/{max_retries}): {e}")
			if attempt < max_retries - 1:
				time.sleep(2 ** attempt)
		except Exception as e:
			logger.error(f"Unexpected error in API request: {e}")
			if attempt < max_retries - 1:
				time.sleep(2 ** attempt)

	return None


standard_book = Book("penguin.book")
atomic_black = Book("atomic_black.book")
atomic_white = Book("atomic_white.book")
threecheck_white = Book("threecheck_white.book")
threecheck_black = Book("threecheck_black.book")

def accept_challenge(game_id):
	logger.info(f'Accepting challenge: {game_id}')
	response = api_request('POST', f'{BASE_URL}api/challenge/{game_id}/accept')
	if response is None:
		logger.error(f'Failed to accept challenge {game_id}: no response')
		return {'error': 'no response'}
	logger.info(f'Accept response: {response.status_code}')
	if response.status_code != 200:
		logger.error(f'Error accepting challenge: {response.text}')
	try:
		return response.json()
	except:
		return {'error': response.text}

def decline_challenge(game_id, reason='generic'):
	"""
	Decline a challenge with a reason.
	Valid reasons: generic, later, tooFast, tooSlow, timeControl, rated, casual, standard, variant, noBot, onlyBot
	"""
	logger.info(f'Declining challenge {game_id}: {reason}')
	response = api_request('POST', f'{BASE_URL}api/challenge/{game_id}/decline', data={'reason': reason})
	if response:
		logger.info(f'Decline response: {response.status_code}')
	return response

def make_move(game_id, move):
	response = api_request('POST', f'{BASE_URL}api/bot/game/{game_id}/move/{move}')
	if response is None:
		return {'ok': False, 'error': 'no response'}
	try:
		return response.json()
	except:
		return {'ok': False, 'error': response.text if response else 'unknown'}

def game_updates(game_id):
	"""Get game stream. Note: streams use longer timeout."""
	try:
		response = requests.get(
			f'{BASE_URL}api/bot/game/stream/{game_id}',
			headers=headers,
			stream=True,
			timeout=(10, 600)  # 10s connect, 10min read timeout (games can pause)
		)
		return response
	except Exception as e:
		logger.error(f"Failed to connect to game stream {game_id}: {e}")
		return None

def chat(game_id, txt):
	body = {"room": "player", "text": txt}
	response = api_request('POST', f'{BASE_URL}api/bot/game/{game_id}/chat', data=body)
	return response

def bot_upgrade():
	response = api_request('POST', f'{BASE_URL}bot/account/upgrade')
	if response is None:
		return {'error': 'no response'}
	try:
		return response.json()
	except:
		return {'error': response.text if response else 'unknown'}

def stream_events(event_queue):
	while True:
		try:
			logger.info("Connecting to Lichess event stream...")
			response = requests.get(
				f'{BASE_URL}api/stream/event',
				headers=headers,
				stream=True,
				timeout=(10, 300)  # 10s connect, 5min read timeout
			)

			if response.status_code == 429:
				logger.warning(f"Rate limited on event stream, waiting {RATE_LIMIT_WAIT}s...")
				time.sleep(RATE_LIMIT_WAIT)
				continue

			if response.status_code != 200:
				logger.error(f"Stream connection failed: {response.status_code}")
				time.sleep(5)
				continue

			logger.info("Connected to event stream")
			last_event_time = time.time()
			event_count = 0

			for event in response.iter_lines():
				last_event_time = time.time()
				event_count += 1

				# Log health every 100 events
				if event_count % 100 == 0:
					logger.info(f"Event stream healthy: {event_count} events received")

				if event:
					try:
						event_queue.put_nowait(json.loads(event.decode('utf-8')))
					except json.JSONDecodeError as e:
						logger.warning(f"Failed to decode event: {e}")
				else:
					event_queue.put_nowait({'type': 'ping'})

			# Stream ended gracefully - log duration
			duration = time.time() - last_event_time
			logger.warning(f"Event stream ended after {duration:.0f}s since last event (total: {event_count} events), reconnecting in 3s...")
			time.sleep(3)
		except requests.exceptions.ReadTimeout:
			logger.warning("Event stream read timeout (no data for 5min), reconnecting...")
			time.sleep(1)
		except requests.exceptions.Timeout:
			logger.warning("Event stream connection timeout, reconnecting in 5s...")
			time.sleep(5)
		except requests.exceptions.ConnectionError as e:
			logger.warning(f"Event stream connection error: {e}, reconnecting in 10s...")
			time.sleep(10)
		except Exception as e:
			logger.error(f"Event stream error: {e}, reconnecting in 5s...")
			time.sleep(5)

def play_game(game_id, event_queue):
	"""Play a single game. Runs in a separate process."""
	logger.info(f"[{game_id}] Starting game")

	try:
		start_color = 1
		my_time = 'btime'
		my_inc = 'binc'

		# Connect to game stream
		game_response = game_updates(game_id)
		if game_response is None or game_response.status_code != 200:
			logger.error(f"[{game_id}] Failed to connect to game stream")
			return

		game_stream = game_response.iter_lines()

		# Get initial game state
		try:
			first_line = next(game_stream)
			game = json.loads(first_line.decode('utf-8'))
		except (StopIteration, json.JSONDecodeError) as e:
			logger.error(f"[{game_id}] Failed to get initial game state: {e}")
			return

		variant = game['variant']['key']
		opponent = game['black']['name'] if game['white']['id'] == BOT_ID else game['white']['name']
		logger.info(f"[{game_id}] Playing {variant} vs {opponent}")

		in_book = True
		current_book = None
		moves_played = 0
		said_ouch = False
		said_haha = False

		if variant == 'atomic':
			board = chess.variant.AtomicBoard()
		elif variant == 'antichess':
			board = chess.variant.GiveawayBoard()
		elif variant == 'threeCheck':
			board = chess.variant.ThreeCheckBoard()
		elif variant == 'standard':
			current_book = standard_book
			logger.debug(f"[{game_id}] Using standard book")
			board = chess.Board()
		else:
			logger.warning(f"[{game_id}] Unknown variant {variant}, defaulting to standard")
			board = chess.Board()

		if game['white']['id'] == BOT_ID:
			start_color = -1
			my_time = 'wtime'
			my_inc = 'winc'

			if variant == 'atomic':
				current_book = atomic_white
			elif variant == 'threeCheck':
				current_book = threecheck_white

			# Determine first move as white
			if variant == 'antichess':
				bot_move = random.choice(['e2e3', 'b2b3', 'g2g3'])
			elif current_book:
				book_move = current_book.get_moves([])
				bot_move = random.choice(book_move)
			else:
				bot_move, _ = search_with_time(board, color=-start_color, variant=variant, time_limit=1.0)

			logger.info(f"[{game_id}] First move as white: {bot_move}")
			make_move(game_id, bot_move)
		elif game['black']['id'] == BOT_ID:
			if variant == 'atomic':
				current_book = atomic_black
			elif variant == 'threeCheck':
				current_book = threecheck_black

		# Main game loop
		for event in game_stream:
			try:
				upd = json.loads(event.decode('utf-8')) if event else None
			except json.JSONDecodeError as e:
				logger.warning(f"[{game_id}] JSON decode error: {e}")
				continue

			_type = upd['type'] if upd else 'ping'

			if _type == 'gameFinish':
				logger.info(f"[{game_id}] Game finished")
				break

			if _type == 'gameState':
				status = upd.get('status', 'started')
				if status != 'started':
					logger.info(f"[{game_id}] Game ended: {status}")
					break

				moves_str = upd.get('moves', '')
				moves = [m for m in moves_str.split(' ') if m]

				# Sync board with game state
				while len(list(board.move_stack)) < len(moves):
					move_idx = len(list(board.move_stack))
					move = chess.Move.from_uci(moves[move_idx])
					board.push(move)

				# Check if it's our turn
				is_white = (game['white']['id'] == BOT_ID)
				our_turn = (len(moves) % 2 == 0) if is_white else (len(moves) % 2 == 1)

				if not our_turn:
					continue

				moves_played = len(moves) // 2

				if in_book and current_book:
					book_move = current_book.get_moves(moves)
				else:
					book_move = None

				if in_book and not book_move:
					chat(game_id, "I'm out of book! :O")
					logger.info(f"[{game_id}] Out of book at move {moves_played}")
					in_book = False

				if book_move:
					bot_move = chess.Move.from_uci(random.choice(book_move))
					logger.info(f"[{game_id}] Book move: {bot_move}")
				else:
					my_time_remaining = upd.get(my_time, 60000)
					opp_time_remaining = upd.get('wtime' if my_time == 'btime' else 'btime', 60000)
					increment = upd.get(my_inc, 0)

					# Use min of our time and opponent's time to make it go for the flag if the opponent is low on time
					time_for_calc = min(my_time_remaining, opp_time_remaining)
					move_time = calculate_move_time(time_for_calc, increment, moves_played)

					if opp_time_remaining < my_time_remaining:
						logger.info(f"[{game_id}] Flagging mode! Opp: {opp_time_remaining/1000:.1f}s, us: {my_time_remaining/1000:.1f}s")
					else:
						logger.info(f"[{game_id}] Time: {my_time_remaining/1000:.1f}s, thinking for {move_time:.2f}s")

					bot_move, score = search_with_time(board, color=-start_color, variant=variant, time_limit=move_time)

					# React to evaluation
					if score <= -300 and not said_ouch:
						chat(game_id, "Ouch!")
						said_ouch = True
					elif score >= 500 and not said_haha:
						chat(game_id, "HAHA!")
						said_haha = True

				# Avoid draw at all cost
				def is_draw_move(b, move):
					"""Check if a move results in any kind of draw."""
					b.push(move)
					is_draw = (
						b.is_stalemate() or
						b.is_insufficient_material() or
						b.is_repetition(3) or
						b.can_claim_fifty_moves()
					)
					b.pop()
					return is_draw

				if is_draw_move(board, bot_move):
					# Find any move that doesn't draw
					non_draw_moves = [m for m in board.legal_moves if not is_draw_move(board, m)]

					if non_draw_moves:
						bot_move = random.choice(non_draw_moves)
						logger.info(f"[{game_id}] Avoided draw! Playing {bot_move} instead")
					else:
						logger.info(f"[{game_id}] All moves draw - no escape!")

				logger.info(f"[{game_id}] Playing: {bot_move}")
				response = make_move(game_id, bot_move)
				if not response.get('ok', False):
					logger.error(f"[{game_id}] Move failed: {response}")
				board.push(bot_move)

	except Exception as e:
		logger.error(f"[{game_id}] Unexpected error: {e}", exc_info=True)
	finally:
		logger.info(f"[{game_id}] Game handler exiting")

def game_error_callback(error):
	"""Called when a game process raises an exception."""
	logger.error(f"Game process error: {error}")


def game_done_callback(result):
	"""Called when a game process completes."""
	# Result is None for play_game, but we could return game_id to track
	pass


# Shared state for tracking active games (must be in main block for multiprocessing)
active_game_count = None  # Will be initialized in main


if __name__ == '__main__':
	# Set up graceful shutdown
	shutdown_requested = False

	def signal_handler(signum, frame):
		global shutdown_requested
		logger.info(f"Received signal {signum}, initiating graceful shutdown...")
		shutdown_requested = True

	signal.signal(signal.SIGINT, signal_handler)
	signal.signal(signal.SIGTERM, signal_handler)

	manager = multiprocessing.Manager()
	event_queue = manager.Queue()
	active_game_count = manager.Value('i', 0)  # Shared counter for active games

	control_stream = multiprocessing.Process(target=stream_events, args=[event_queue])
	control_stream.start()

	logger.info(f"Bot started. Max concurrent games: {MAX_CONCURRENT_GAMES}")

	def on_game_start(game_id):
		"""Track game start."""
		active_game_count.value += 1
		logger.info(f"Game started: {game_id} (active: {active_game_count.value})")

	def on_game_end(result):
		"""Track game completion."""
		active_game_count.value = max(0, active_game_count.value - 1)
		logger.debug(f"Game ended (active: {active_game_count.value})")

	try:
		with logging_pool.LoggingPool(MAX_CONCURRENT_GAMES) as pool:
			while not shutdown_requested:
				try:
					# Use timeout to allow checking shutdown flag
					event = event_queue.get(timeout=1.0)
				except queue.Empty:
					continue  # Normal timeout, check shutdown flag
				except Exception as e:
					logger.error(f"Error getting event from queue: {e}")
					continue

				if event['type'] == 'challenge':
					challenge = event['challenge']
					_id = challenge['id'].strip()
					variant = challenge['variant']['key']
					challenger = challenge.get('challenger', {})
					challenger_title = challenger.get('title', '')
					challenger_name = challenger.get('name', 'Unknown')
					time_control = challenge.get('timeControl', {})
					speed = challenge.get('speed', 'unknown')

					logger.info(f"Challenge from {challenger_name}: variant={variant}, speed={speed}")

					# Check if at max concurrent games
					if active_game_count.value >= MAX_CONCURRENT_GAMES:
						logger.info(f"Declining {challenger_name}: at max games ({MAX_CONCURRENT_GAMES})")
						decline_challenge(_id, reason='later')
						continue

					# Check if variant is supported
					supported_variants = ['standard', 'atomic', 'antichess', 'threeCheck']
					if variant not in supported_variants:
						logger.info(f"Declining {challenger_name}: unsupported variant {variant}")
						decline_challenge(_id, reason='variant')
						continue

					# Don't accept challenges from other bots
					if challenger_title == 'BOT':
						logger.info(f"Declining {challenger_name}: is a BOT")
						decline_challenge(_id, reason='noBot')
						continue

					# Decline ultrabullet - too fast for this bot
					if speed == 'ultraBullet':
						logger.info(f"Declining {challenger_name}: ultrabullet too fast")
						decline_challenge(_id, reason='tooFast')
						continue

					logger.info(f"Accepting challenge from {challenger_name} ({variant}, {speed})")
					accept_challenge(_id)

				elif event['type'] == 'gameStart':
					game_id = event['game']['id']
					on_game_start(game_id)
					pool.apply_async(
						play_game,
						[game_id, event_queue],
						callback=on_game_end,
						error_callback=game_error_callback
					)

				elif event['type'] == 'gameFinish':
					# Also track via event stream (backup)
					game_id = event.get('game', {}).get('id', 'unknown')
					logger.debug(f"Game finish event: {game_id}")

	except KeyboardInterrupt:
		logger.info("Keyboard interrupt received")
	finally:
		logger.info("Shutting down...")
		control_stream.terminate()
		control_stream.join(timeout=5)
		logger.info("Bot stopped")
