# server.py - Complete Big 2 Multiplayer Server (Fixed for newer websockets)
import asyncio
import websockets
import json
from collections import defaultdict
import random

# Game constants
SUITS = ['d', 'c', 'h', 's']
RANKS = ['3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A', '2']
RANK_ORDER = {r:i for i,r in enumerate(RANKS)}
SUIT_ORDER = {'d':0, 'c':1, 'h':2, 's':3}

class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
    
    def to_dict(self):
        return {"rank": self.rank, "suit": self.suit}
    
    @classmethod
    def from_dict(cls, data):
        return cls(data["rank"], data["suit"])
    
    def key(self):
        return (RANK_ORDER[self.rank], SUIT_ORDER[self.suit])

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = []  # List of (websocket, player_id, player_name)
        self.game_state = {
            "hands": [[] for _ in range(4)],
            "current_player": 0,
            "previous_move": None,
            "passes": 0,
            "last_played_cards": [],
            "game_over": False,
            "winner": None,
            "game_started": False,
            "waiting_for_players": True
        }
        self.min_players = 4
        self.max_players = 4
    
    def add_player(self, websocket, player_name):
        if len(self.players) >= self.max_players:
            return None, "Room is full"
        
        player_id = len(self.players)
        self.players.append({
            "websocket": websocket,
            "id": player_id,
            "name": player_name
        })
        return player_id, None
    
    def remove_player(self, websocket):
        self.players = [p for p in self.players if p["websocket"] != websocket]
        
        # Reset game if player leaves before start
        if not self.game_state["game_started"]:
            self.reset_waiting_state()
    
    def reset_waiting_state(self):
        """Reset the waiting state when players disconnect"""
        self.game_state["game_started"] = False
        self.game_state["waiting_for_players"] = True
        self.game_state["hands"] = [[] for _ in range(4)]
        self.game_state["current_player"] = 0
        self.game_state["previous_move"] = None
        self.game_state["passes"] = 0
        self.game_state["last_played_cards"] = []
        self.game_state["game_over"] = False
        self.game_state["winner"] = None
    
    def can_start_game(self):
        """Check if we have enough players to start"""
        return len(self.players) >= self.min_players and not self.game_state["game_started"]
    
    def start_game(self):
        """Initialize the game when enough players join"""
        if not self.can_start_game():
            return False
        
        self.game_state["game_started"] = True
        self.game_state["waiting_for_players"] = False
        self.deal_cards()
        self.broadcast_game_state()
        return True
    
    def deal_cards(self):
        """Deal cards to all players (up to 4 players)"""
        # Create and shuffle deck
        deck = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(deck)
        
        # Calculate cards per player
        num_players = len(self.players)
        cards_per_player = 52 // num_players
        remaining_cards = 52 % num_players
        
        # Deal cards
        hands = [[] for _ in range(4)]
        card_index = 0
        
        for i in range(num_players):
            cards_for_player = cards_per_player + (1 if i < remaining_cards else 0)
            for j in range(cards_for_player):
                hands[i].append(deck[card_index])
                card_index += 1
        
        # Sort each hand
        for i in range(num_players):
            hands[i].sort(key=lambda c: c.key())
        
        # Find who has 3 of diamonds (starts)
        starter = -1
        for i in range(num_players):
            if any(c.rank == '3' and c.suit == 'd' for c in hands[i]):
                starter = i
                break
        
        if starter == -1:
            starter = 0
        
        self.game_state["hands"] = [[c.to_dict() for c in hand] for hand in hands]
        self.game_state["current_player"] = starter
        self.game_state["num_players"] = num_players
    
    def get_hand_type(self, cards):
        """Determine the type of hand (single, pair, etc.)"""
        if not cards:
            return None
        n = len(cards)
        rank_count = defaultdict(int)
        suit_count = defaultdict(int)
        for c in cards:
            rank_count[c.rank] += 1
            suit_count[c.suit] += 1
        counts = sorted(rank_count.values(), reverse=True)
        
        if n == 1:
            return ('single', cards[0].key())
        if n == 2 and counts == [2]:
            return ('pair', max(cards, key=lambda c: c.key()).key())
        if n == 3 and counts == [3]:
            return ('triple', max(cards, key=lambda c: c.key()).key())
        if n == 5:
            ranks_idx = sorted(RANK_ORDER[c.rank] for c in cards)
            is_seq = ranks_idx[4] - ranks_idx[0] == 4 and len(set(ranks_idx)) == 5
            is_fl = len(set(c.suit for c in cards)) == 1
            if is_seq and is_fl:
                return ('straight_flush', max(cards, key=lambda c: c.key()).key())
            if 4 in counts:
                quad_r = next(r for r,c in rank_count.items() if c==4)
                return ('four_kind', (RANK_ORDER[quad_r], 0))
            if counts == [3,2]:
                trip_r = next(r for r,c in rank_count.items() if c==3)
                return ('full_house', (RANK_ORDER[trip_r], 0))
            if is_fl:
                return ('flush', max(cards, key=lambda c: c.key()).key())
            if is_seq:
                return ('straight', max(cards, key=lambda c: c.key()).key())
        return None
    
    def beats(self, hand_type, prev_type):
        """Check if hand_type beats prev_type"""
        if not prev_type:
            return True
        if not hand_type:
            return False
        t1, _ = hand_type
        t2, _ = prev_type
        type_order = {'single':0, 'pair':1, 'triple':2, 'straight':3, 
                      'flush':4, 'full_house':5, 'four_kind':6, 'straight_flush':7}
        if type_order.get(t1, -1) != type_order.get(t2, -1):
            return type_order.get(t1, -1) > type_order.get(t2, -1)
        return hand_type[1] > prev_type[1]
    
    def validate_move(self, player_id, selected_cards):
        """Validate if a move is legal"""
        if not self.game_state["game_started"]:
            return False, "Game hasn't started yet"
        
        if player_id >= len(self.players):
            return False, "Invalid player"
        
        if player_id != self.game_state["current_player"]:
            return False, "Not your turn"
        
        if self.game_state["game_over"]:
            return False, "Game is over"
        
        cards = [Card.from_dict(c) for c in selected_cards]
        hand_type = self.get_hand_type(cards)
        
        if self.beats(hand_type, self.game_state["previous_move"]):
            return True, hand_type
        else:
            return False, "Invalid play"
    
    def make_move(self, player_id, selected_cards):
        """Execute a validated move"""
        # Remove cards from player's hand
        hand = [Card.from_dict(c) for c in self.game_state["hands"][player_id]]
        cards_to_remove = [Card.from_dict(c) for c in selected_cards]
        
        for card in cards_to_remove:
            for h_card in hand:
                if h_card.rank == card.rank and h_card.suit == card.suit:
                    hand.remove(h_card)
                    break
        
        self.game_state["hands"][player_id] = [c.to_dict() for c in hand]
        
        # Update game state
        hand_type = self.get_hand_type(cards_to_remove)
        self.game_state["previous_move"] = hand_type
        self.game_state["last_played_cards"] = selected_cards
        self.game_state["passes"] = 0
        
        # Check win condition
        if len(hand) == 0:
            self.game_state["game_over"] = True
            self.game_state["winner"] = player_id
        else:
            num_players = len(self.players)
            self.game_state["current_player"] = (player_id + 1) % num_players
        
        return True
    
    def make_pass(self, player_id):
        """Execute a pass"""
        self.game_state["passes"] += 1
        
        num_players = len(self.players)
        if self.game_state["passes"] >= num_players - 1:
            self.game_state["previous_move"] = None
            self.game_state["passes"] = 0
        
        self.game_state["current_player"] = (player_id + 1) % num_players
    
    def broadcast_game_state(self):
        """Send current game state to all players"""
        for player in self.players:
            try:
                personalized_state = self.get_player_view(player["id"])
                message = {
                    "type": "game_state",
                    "game_state": personalized_state
                }
                asyncio.create_task(player["websocket"].send(json.dumps(message)))
            except:
                pass
    
    def get_player_view(self, player_id):
        """Return game state from specific player's perspective"""
        state = self.game_state.copy()
        
        state["player_id"] = player_id
        state["your_hand"] = state["hands"][player_id] if state["game_started"] else []
        state["hand_sizes"] = [len(hand) for hand in state["hands"]]
        state["num_players"] = len(self.players)
        state["player_names"] = [p["name"] for p in self.players]
        state["hands"] = None
        
        return state

class GameServer:
    def __init__(self):
        self.waiting_room = GameRoom("waiting")
    
    # FIXED: Removed the 'path' parameter
    async def handle_client(self, websocket):
        """Handle a new client connection"""
        print(f"New client connected")
        
        try:
            player_name = None
            player_id = None
            
            async for message in websocket:
                data = json.loads(message)
                
                if data["type"] == "join":
                    player_name = data.get("player_name", f"Player_{id(websocket)}")
                    player_id, error = self.waiting_room.add_player(websocket, player_name)
                    
                    if error:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": error
                        }))
                        continue
                    
                    # Send acknowledgment
                    await websocket.send(json.dumps({
                        "type": "joined",
                        "player_id": player_id,
                        "players_in_room": len(self.waiting_room.players),
                        "min_players": self.waiting_room.min_players,
                        "waiting_for_players": not self.waiting_room.game_state["game_started"]
                    }))
                    
                    # Broadcast player count
                    self.broadcast_player_count()
                    
                    # Check if we can start the game
                    if self.waiting_room.can_start_game():
                        print(f"Starting game with {len(self.waiting_room.players)} players!")
                        self.waiting_room.start_game()
                
                elif data["type"] == "play" and self.waiting_room.game_state["game_started"]:
                    player_id = data["data"]["player_id"]
                    selected_cards = data["data"]["selected_cards"]
                    
                    valid, result = self.waiting_room.validate_move(player_id, selected_cards)
                    if valid:
                        self.waiting_room.make_move(player_id, selected_cards)
                        self.waiting_room.broadcast_game_state()
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result
                        }))
                
                elif data["type"] == "pass" and self.waiting_room.game_state["game_started"]:
                    player_id = data["data"]["player_id"]
                    self.waiting_room.make_pass(player_id)
                    self.waiting_room.broadcast_game_state()
        
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected")
        finally:
            self.waiting_room.remove_player(websocket)
            self.broadcast_player_count()
            
            if not self.waiting_room.can_start_game():
                self.waiting_room.reset_waiting_state()
                self.waiting_room.broadcast_game_state()
    
    def broadcast_player_count(self):
        """Send player count update to all connected clients"""
        message = {
            "type": "player_count",
            "players_in_room": len(self.waiting_room.players),
            "min_players": self.waiting_room.min_players,
            "game_started": self.waiting_room.game_state["game_started"]
        }
        
        for player in self.waiting_room.players:
            try:
                asyncio.create_task(player["websocket"].send(json.dumps(message)))
            except:
                pass

async def main():
    server = GameServer()
    # FIXED: Removed the 'path' parameter from serve()
    async with websockets.serve(server.handle_client, "0.0.0.0", 8765):
        print("=" * 60)
        print("🃏 BIG 2 MULTIPLAYER SERVER")
        print("=" * 60)
        print(f"Server running on ws://0.0.0.0:8765")
        print(f"Minimum players: 2 | Maximum players: 4")
        print("\n📡 Waiting for players to connect...")
        print("=" * 60)
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
