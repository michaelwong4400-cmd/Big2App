# server.py - Complete multiplayer server for Big 2
import asyncio
import websockets
import json
from collections import defaultdict
import random

# Game constants (same as your client)
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
            "winner": None
        }
        self.game_started = False
    
    def add_player(self, websocket, player_name):
        player_id = len(self.players)
        self.players.append({
            "websocket": websocket,
            "id": player_id,
            "name": player_name
        })
        return player_id
    
    def remove_player(self, websocket):
        self.players = [p for p in self.players if p["websocket"] != websocket]
    
    def all_players_ready(self):
        return len(self.players) == 4
    
    def start_game(self):
        """Initialize the game when 4 players join"""
        self.game_started = True
        self.deal_cards()
        self.broadcast_game_state()
    
    def deal_cards(self):
        """Deal cards to all players"""
        # Create and shuffle deck
        deck = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(deck)
        
        # Deal 13 cards to each player
        hands = [[] for _ in range(4)]
        for i in range(52):
            hands[i % 4].append(deck[i])
        
        # Sort each hand
        for hand in hands:
            hand.sort(key=lambda c: (RANK_ORDER[c.rank], SUIT_ORDER[c.suit]))
        
        # Find who has 3 of diamonds (starts)
        starter = -1
        for i, hand in enumerate(hands):
            if any(c.rank == '3' and c.suit == 'd' for c in hand):
                starter = i
                break
        
        self.game_state["hands"] = [[c.to_dict() for c in hand] for hand in hands]
        self.game_state["current_player"] = starter
    
    def validate_move(self, player_id, selected_cards):
        """Validate if a move is legal"""
        if player_id != self.game_state["current_player"]:
            return False, "Not your turn"
        
        if self.game_state["game_over"]:
            return False, "Game is over"
        
        # Convert dict cards back to Card objects for validation
        cards = [Card.from_dict(c) for c in selected_cards]
        
        # Get hand type
        hand_type = self.get_hand_type(cards)
        
        # Check if beats previous move
        if self.beats(hand_type, self.game_state["previous_move"]):
            return True, hand_type
        else:
            return False, "Invalid play"
    
    def get_hand_type(self, cards):
        """Same validation logic as client"""
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
        """Same beat logic as client"""
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
            # Move to next player
            self.game_state["current_player"] = (player_id + 1) % 4
        
        return True
    
    def make_pass(self, player_id):
        """Execute a pass"""
        self.game_state["passes"] += 1
        
        if self.game_state["passes"] >= 3:
            self.game_state["previous_move"] = None
            self.game_state["passes"] = 0
        
        self.game_state["current_player"] = (player_id + 1) % 4
    
    def broadcast_game_state(self):
        """Send current game state to all players"""
        message = {
            "type": "game_state",
            "game_state": self.game_state
        }
        
        for player in self.players:
            try:
                # Send personalized view (hide other players' cards)
                personalized_state = self.get_player_view(player["id"])
                message["game_state"] = personalized_state
                asyncio.create_task(player["websocket"].send(json.dumps(message)))
            except:
                pass
    
    def get_player_view(self, player_id):
        """Return game state from specific player's perspective"""
        state = self.game_state.copy()
        
        # Only show this player their own cards, others see card count only
        state["player_id"] = player_id
        state["your_hand"] = state["hands"][player_id]
        state["hand_sizes"] = [len(hand) for hand in state["hands"]]
        state["hands"] = None  # Don't send full hands to hide other players' cards
        
        return state

class GameServer:
    def __init__(self):
        self.rooms = {}  # room_id -> GameRoom
        self.waiting_room = GameRoom("waiting")
    def process_game_message(self, data):
        if data["type"] == "game_state":
            game_state = data["game_state"]
            
            # Check if game is waiting for players
            if game_state.get("waiting_for_players", False):
                self.show_waiting_screen(game_state)
                return
            
            # Update local game state from server
            self.current_player = game_state["current_player"]
            self.previous_move = game_state["previous_move"]
            self.passes = game_state["passes"]
            self.game_over = game_state["game_over"]
            self.game_started = game_state.get("game_started", True)
            
            # Update your hand (only your cards)
            if "your_hand" in game_state:
                # Convert dict cards back to Card objects
                self.hands[self.player_id] = [Card(c["rank"], c["suit"]) for c in game_state["your_hand"]]
            
            # Update hand sizes display
            self.hand_sizes = game_state["hand_sizes"]
            self.num_players = game_state.get("num_players", 4)
            
            # Update last played cards display
            if "last_played_cards" in game_state:
                self.last_played_cards = [Card(c["rank"], c["suit"]) for c in game_state["last_played_cards"]]
            
            # Show player names if available
            if "player_names" in game_state:
                self.player_names = game_state["player_names"]
            
            # Redraw the UI
            self.redraw()
            
            # Show winner if game over
            if self.game_over:
                winner = game_state.get("winner")
                messagebox.showinfo("Game Over", f"Player {winner} wins!")
        
        elif data["type"] == "player_count":
            players = data["players_in_room"]
            min_players = data["min_players"]
            game_started = data["game_started"]
            
            if not game_started:
                self.status_label.config(
                    text=f"Waiting for players... ({players}/{min_players}) connected. Game will start when {min_players} players join."
                )
        
        elif data["type"] == "joined":
            self.player_id = data["player_id"]
            players = data["players_in_room"]
            min_players = data["min_players"]
            
            messagebox.showinfo("Connected", 
                f"Connected to server as Player {self.player_id}\n"
                f"Players in room: {players}/{min_players}\n"
                f"Waiting for {min_players - players} more player(s) to start..."
            )

    def show_waiting_screen(self, game_state):
        """Display a waiting screen until game starts"""
        self.canvas.delete("all")
        num_players = game_state.get("num_players", 0)
        min_players = 2
        
        # Display waiting message
        self.canvas.create_text(
            self.canvas.winfo_width() // 2,
            self.canvas.winfo_height() // 2 - 50,
            text="Waiting for Game to Start",
            font=("Arial", 24, "bold"),
            fill="white"
        )
        
        self.canvas.create_text(
            self.canvas.winfo_width() // 2,
            self.canvas.winfo_height() // 2,
            text=f"Players connected: {num_players}/{min_players}",
            font=("Arial", 18),
            fill="white"
        )
        
        if num_players < min_players:
            self.canvas.create_text(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2 + 50,
                text=f"Waiting for {min_players - num_players} more player(s)...",
                font=("Arial", 14),
                fill="yellow"
            )
        
        self.update_status()

    def play_selected(self):
        """Modified to send move to server instead of processing locally"""
        if not self.connected or self.game_over or self.waiting_for_next_player:
            return
        
        if not self.game_started:
            messagebox.showinfo("Waiting", "Game hasn't started yet!")
            return
        
        if not self.selected_cards:
            messagebox.showerror("No Cards", "Please select cards to play!")
            return
        
        # Convert selected cards to serializable format
        cards_data = [{"rank": c.rank, "suit": c.suit} for c in self.selected_cards]
        
        # Send to server
        self.send_to_server("play", {
            "player_id": self.player_id,
            "selected_cards": cards_data
        })
        
        # Clear selection (will be redrawn when server confirms)
        self.selected_cards = []
        self.waiting_for_next_player = True
        self.redraw()

    def pass_turn(self):
        """Modified to send pass to server"""
        if not self.connected or self.game_over or self.waiting_for_next_player:
            return
        
        if not self.game_started:
            messagebox.showinfo("Waiting", "Game hasn't started yet!")
            return
        
        self.send_to_server("pass", {
            "player_id": self.player_id
        })
        
        self.waiting_for_next_player = True
        self.redraw()
        
    async def handle_client(self, websocket, path):
        """Handle a new client connection"""
        print(f"New client connected")
        
        try:
            # Assign to waiting room
            player_name = None
            
            async for message in websocket:
                data = json.loads(message)
                
                if data["type"] == "join":
                    player_name = data.get("player_name", f"Player_{id(websocket)}")
                    player_id = self.waiting_room.add_player(websocket, player_name)
                    
                    # Send acknowledgment
                    await websocket.send(json.dumps({
                        "type": "joined",
                        "player_id": player_id,
                        "players_in_room": len(self.waiting_room.players)
                    }))
                    
                    # Check if we have 4 players
                    if self.waiting_room.all_players_ready():
                        print("Starting game with 4 players!")
                        self.waiting_room.start_game()
                        self.waiting_room.broadcast_game_state()
                
                elif data["type"] == "play" and self.waiting_room.game_started:
                    player_id = data["player_id"]
                    selected_cards = data["selected_cards"]
                    
                    valid, result = self.waiting_room.validate_move(player_id, selected_cards)
                    if valid:
                        self.waiting_room.make_move(player_id, selected_cards)
                        self.waiting_room.broadcast_game_state()
                    else:
                        # Send error to just this player
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result
                        }))
                
                elif data["type"] == "pass" and self.waiting_room.game_started:
                    player_id = data["player_id"]
                    self.waiting_room.make_pass(player_id)
                    self.waiting_room.broadcast_game_state()
        
        except websockets.exceptions.ConnectionClosed:
            print("Client disconnected")
        finally:
            self.waiting_room.remove_player(websocket)

async def main():
    server = GameServer()
    async with websockets.serve(server.handle_client, "0.0.0.0", 8765):
        print("Big 2 Game Server running on port 8765")
        print("Waiting for players to connect...")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
