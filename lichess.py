import requests
import json
import multiprocessing
from multiprocessing import Pool
import engine
import logging_pool
import chess
from keys import AUTHENTICATION_TOKEN
from engine import *
import random
from opening_book import Book
import chess.variant
import random

BASE_URL = 'https://lichess.org/'
BOT_ID = 'bottios'
headers = {'Authorization': 'Bearer %s' % AUTHENTICATION_TOKEN}

standard_book = Book("penguin.book")
atomic_black = Book("atomic_black.book")
atomic_white = Book("atomic_white.book")
threecheck_white = Book("threecheck_white.book")
threecheck_black = Book("threecheck_black.book")

def time_to_depth(time, variant="standard"):
	depth=2

	if variant=="antichess":
		if time > 60 * 1000:
			depth=5
		else:
			depth = 4

	if variant=="threeCheck":
		if time > 120 * 1000:
			depth= 3
		else:
			depth = 2

	return depth

def accept_challenge(game_id):
	#curl -H "Authorization: Bearer rSRtCAEFhYAYd66z" https://lichess.org/api/challenge/gdksij27/accept -X POST 
	print('ACCEPTING_CHALLENGE')
	response = requests.post('https://lichess.org/api/challenge/%s/accept' % (game_id), headers=headers)
	print('RESPONSE')
	print(response)
	return response.json()

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
	game_stream = game_updates(game_id).iter_lines()

	print('GAME_STREAM')
	print(game_stream)

	game = json.loads(next(game_stream).decode('utf-8'))
	variant = game['variant']['key']

	in_book = True
	current_book = None

	if variant == 'atomic':
		board = chess.variant.AtomicBoard()
	if variant == 'antichess':
		board = chess.variant.GiveawayBoard()
	if variant == 'threeCheck':
		board = chess.variant.ThreeCheckBoard()
	if variant == 'standard':
		current_book = standard_book
		print("Choosing book standard_book")
		board = chess.Board()

	fens = []

	if game['white']['id'] == BOT_ID:
		start_color = -1
		my_time = 'wtime'

		if variant == 'atomic':
			print("Choosing book atomic_white")
			current_book = atomic_white

		if variant == 'threeCheck':
			print("Choosing book threecheck_white")
			current_book = threecheck_white

		#bot_move = search(board, color=-start_color, variant=variant, depth=3)

		if current_book:
			book_move = current_book.get_moves([])
		if variant == 'antichess':
			bot_move = random.choice(['e2e3', 'b2b3', 'g2g3'])
		else:
			bot_move = random.choice(book_move)

		make_move(game_id, bot_move)
		fens.append(board.fen()[:-9].strip())
	elif game['black']['id'] == BOT_ID and variant == 'atomic':
		print("Choosing book atomic_black")
		current_book = atomic_black
	elif game['black']['id'] == BOT_ID and variant == 'threeCheck':
		print("Choosing book threecheck_white")
		current_book = threecheck_black

	for event in game_stream:
		upd = json.loads(event.decode('utf-8')) if event else None
		_type = upd['type'] if upd else 'ping'
		if (_type == 'gameState'):
			last_move = upd['moves'].split(' ')[-1]
			last_move = chess.Move.from_uci(last_move)
			board.push(last_move)

			moves = upd['moves'].split(' ')

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
				bot_move = search(board, color=-start_color, variant=variant, depth=time_to_depth(upd[my_time], variant))

			print(bot_move)

			make_move(game_id, bot_move)
			fens.append(board.fen()[:-9].strip())

if __name__ == '__main__':
	manager = multiprocessing.Manager()
	challenge_queue = []
	event_queue = manager.Queue()

	control_stream = multiprocessing.Process(target=stream_events, args=[event_queue])
	control_stream.start()

	with logging_pool.LoggingPool(10) as pool:
		while True:
			event = event_queue.get()

			if event['type'] == 'challenge' and ((event['challenge']['variant']['key'] == 'standard') or (event['challenge']['variant']['key'] == 'atomic') or (event['challenge']['variant']['key'] == 'antichess') or (event['challenge']['variant']['key'] == 'threeCheck')):
				_id = event['challenge']['id'].strip()

				accept_challenge(_id)
			elif event['type'] == 'gameStart':
				game_id = event['game']['id']
				pool.apply_async(play_game, [game_id, event_queue])

	control_stream.terminate()
	control_stream.join()
