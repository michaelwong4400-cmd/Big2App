# server.py - Complete Big 2 Multiplayer Server with 3 of Diamonds Enforcement
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

TYPE_ORDER = {
    'single': 0,
    'pair': 1,
    'triple': 2,
    'straight': 3,
    'flush': 4,
    'full_house': 5,
    'four_kind': 6,
    'straight_flush': 7
}

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
    def __init__(self):
        self.players = []
        self.game_state = {
            "hands": [[] for _ in range(4)],
            "current_player": 0,
            "previous_move": None,
            "passes": 0,
            "last_played_cards": [],
            "game_over": False,
            "winner": None,
            "game_started": False,
            "must_play_three_diamonds": False  # CRITICAL: This flag must be here
        }
        self.min_players = 2
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
    
    def can_start_game(self):
        return len(self.players) >= self.min_players and not self.game_state["game_started"]
    
    def start_game(self):
        if not self.can_start_game():
            return False
        
        self.game_state["game_started"] = True
        self.deal_cards()
        # CRITICAL: Set this flag to True when game starts
        self.game_state["must_play_three_diamonds"] = True
        self.broadcast_game_state()
        return True
    
    def deal_cards(self):
        deck = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(deck)
        
        num_players = len(self.players)
        hands = [[] for _ in range(4)]
        
        # Deal cards evenly
        for i in range(52):
            hands[i % num_players].append(deck[i])
        
        # Sort each hand
        for i in range(num_players):
            hands[i].sort(key=lambda c: c.key())
        
        # Find who has 3 of diamonds
        starter = 0
        for i in range(num_players):
            if any(c.rank == '3' and c.suit == 'd' for c in hands[i]):
                starter = i
                break
        
        self.game_state["hands"] = [[c.to_dict() for c in hand] for hand in hands]
        self.game_state["current_player"] = starter
        self.game_state["num_players"] = num_players
    
    def get_hand_type(self, cards):
        if not cards:
            return None
        
        n = len(cards)
        rank_count = defaultdict(int)
        for c in cards:
            rank_count[c.rank] += 1
        counts = sorted(rank_count.values(), reverse=True)
        
        # Single
        if n == 1:
            return ('single', cards[0].key(), 1)
        
        # Pair
        if n == 2 and counts == [2]:
            return ('pair', max(cards, key=lambda c: c.key()).key(), 2)
        
        # Triple
        if n == 3 and counts == [3]:
            return ('triple', max(cards, key=lambda c: c.key()).key(), 3)
        
        # 5-card combos
        if n == 5:
            ranks_idx = sorted(RANK_ORDER[c.rank] for c in cards)
            is_seq = ranks_idx[4] - ranks_idx[0] == 4 and len(set(ranks_idx)) == 5
            is_fl = len(set(c.suit for c in cards)) == 1
            
            if is_seq and is_fl:
                return ('straight_flush', max(cards, key=lambda c: c.key()).key(), 5)
            if 4 in counts:
                quad_r = next(r for r,c in rank_count.items() if c==4)
                return ('four_kind', (RANK_ORDER[quad_r], 0), 5)
            if 3 in rank_count.values() and 2 in rank_count.values():
                trip_r = next(r for r,c in rank_count.items() if c==3)
                return ('full_house', (RANK_ORDER[trip_r], 0), 5)
            if is_fl:
                return ('flush', max(cards, key=lambda c: c.key()).key(), 5)
            if is_seq:
                return ('straight', max(cards, key=lambda c: c.key()).key(), 5)
        
        return None
    
    def can_beat(self, new_hand, prev_hand):
        if prev_hand is None:
            return True
        if new_hand is None:
            return False
        
        new_type, new_key, new_count = new_hand
        prev_type, prev_key, prev_count = prev_hand
        
        # Must have same number of cards
        if new_count != prev_count:
            return False
        
        # For 5-card hands, any type can beat any other if ranked higher
        if new_count == 5:
            if new_type == prev_type:
                return new_key > prev_key
            else:
                return TYPE_ORDER.get(new_type, -1) > TYPE_ORDER.get(prev_type, -1)
        else:
            # For 1,2,3 card hands, must be same type
            if new_type != prev_type:
                return False
            return new_key > prev_key
    
    def validate_move(self, player_id, selected_cards):
        if not self.game_state["game_started"]:
            return False, "Game hasn't started"
        
        if player_id != self.game_state["current_player"]:
            return False, "Not your turn"
        
        if self.game_state["game_over"]:
            return False, "Game is over"
        
        cards = [Card.from_dict(c) for c in selected_cards]
        
        # CRITICAL: Check 3 of diamonds rule
        if self.game_state.get("must_play_three_diamonds", False):
            has_three_diamonds = any(c.rank == '3' and c.suit == 'd' for c in cards)
            if not has_three_diamonds:
                return False, "You MUST include the 3 of diamonds in your play!"
        
        hand_type = self.get_hand_type(cards)
        if not hand_type:
            return False, "Invalid hand combination"
        
        if self.can_beat(hand_type, self.game_state["previous_move"]):
            return True, hand_type
        else:
            return False, "This doesn't beat the previous move"
    
    def make_move(self, player_id, selected_cards):
        # Remove cards from hand
        hand = [Card.from_dict(c) for c in self.game_state["hands"][player_id]]
        cards_to_remove = [Card.from_dict(c) for c in selected_cards]
        
        for card in cards_to_remove:
            for h_card in hand:
                if h_card.rank == card.rank and h_card.suit == card.suit:
                    hand.remove(h_card)
                    break
        
        self.game_state["hands"][player_id] = [c.to_dict() for c in hand]
        
        hand_type = self.get_hand_type(cards_to_remove)
        self.game_state["previous_move"] = hand_type
        self.game_state["last_played_cards"] = selected_cards
        self.game_state["passes"] = 0
        
        # CRITICAL: Turn off the 3D requirement after first play
        self.game_state["must_play_three_diamonds"] = False
        
        if len(hand) == 0:
            self.game_state["game_over"] = True
            self.game_state["winner"] = player_id
        else:
            num_players = len(self.players)
            self.game_state["current_player"] = (player_id + 1) % num_players
        
        return True
    
    def make_pass(self, player_id):
        # CRITICAL: Cannot pass if 3D must be played
        if self.game_state.get("must_play_three_diamonds", False):
            hand = [Card.from_dict(c) for c in self.game_state["hands"][player_id]]
            has_three_diamonds = any(c.rank == '3' and c.suit == 'd' for c in hand)
            if has_three_diamonds:
                return False, "You MUST play the 3 of diamonds! You cannot pass."
        
        self.game_state["passes"] += 1
        num_players = len(self.players)
        
        if self.game_state["passes"] >= num_players:
            self.game_state["previous_move"] = None
            self.game_state["passes"] = 0
        
        self.game_state["current_player"] = (player_id + 1) % num_players
        return True, None
    
    def broadcast_game_state(self):
        for player in self.players:
            try:
                state = self.get_player_view(player["id"])
                asyncio.create_task(player["websocket"].send(json.dumps({
                    "type": "game_state",
                    "game_state": state
                })))
            except Exception as e:
                print(f"Error broadcasting: {e}")
    
    def get_player_view(self, player_id):
        state = self.game_state.copy()
        state["player_id"] = player_id
        state["your_hand"] = state["hands"][player_id] if state["game_started"] else []
        state["hand_sizes"] = [len(h) for h in state["hands"]]
        state["player_names"] = [p["name"] for p in self.players]
        state["hands"] = None
        
        # CRITICAL: Include the 3D flag in the game state sent to clients
        state["must_play_three_diamonds"] = self.game_state.get("must_play_three_diamonds", False)
        
        return state

class GameServer:
    def __init__(self):
        self.room = GameRoom()
    
    async def handle_client(self, websocket):
        print("New client connected")
        player_id = None
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    print(f"Invalid JSON: {message}")
                    continue
                
                if data["type"] == "join":
                    player_name = data.get("player_name", "Player")
                    player_id, error = self.room.add_player(websocket, player_name)
                    
                    if error:
                        await websocket.send(json.dumps({"type": "error", "message": error}))
                        continue
                    
                    await websocket.send(json.dumps({
                        "type": "joined",
                        "player_id": player_id,
                        "players_in_room": len(self.room.players),
                        "min_players": self.room.min_players,
                        "waiting_for_players": not self.room.game_state["game_started"]
                    }))
                    
                    await self.broadcast_count()
                    
                    if self.room.can_start_game():
                        print(f"Starting game with {len(self.room.players)} players!")
                        self.room.start_game()
                
                elif data["type"] == "play":
                    if not self.room.game_state["game_started"]:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Game hasn't started yet"
                        }))
                        continue
                    
                    valid, result = self.room.validate_move(player_id, data["data"]["selected_cards"])
                    if valid:
                        self.room.make_move(player_id, data["data"]["selected_cards"])
                        self.room.broadcast_game_state()
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result
                        }))
                
                elif data["type"] == "pass":
                    if not self.room.game_state["game_started"]:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Game hasn't started yet"
                        }))
                        continue
                    
                    success, error = self.room.make_pass(player_id)
                    if success:
                        self.room.broadcast_game_state()
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": error
                        }))
        
        except websockets.exceptions.ConnectionClosed:
            print("Client disconnected")
        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            if player_id is not None:
                self.room.remove_player(websocket)
                await self.broadcast_count()
    
    async def broadcast_count(self):
        message = {
            "type": "player_count",
            "players_in_room": len(self.room.players),
            "min_players": self.room.min_players,
            "game_started": self.room.game_state["game_started"]
        }
        for player in self.room.players:
            try:
                await player["websocket"].send(json.dumps(message))
            except:
                pass

async def main():
    server = GameServer()
    
    # Try ports 8765-8770
    for port in range(8765, 8771):
        try:
            async with websockets.serve(server.handle_client, "0.0.0.0", port):
                print("=" * 60)
                print("🃏 BIG 2 MULTIPLAYER SERVER")
                print("=" * 60)
                print(f"Server running on ws://0.0.0.0:{port}")
                print(f"Minimum players: 2 | Maximum players: 4")
                print("\n📡 Waiting for players to connect...")
                print("=" * 60)
                await asyncio.Future()
                return
        except OSError as e:
            if "10048" in str(e) or "Address already in use" in str(e):
                print(f"Port {port} is in use, trying next port...")
                continue
            else:
                raise e

if __name__ == "__main__":
    asyncio.run(main())
