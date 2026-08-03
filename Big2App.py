import tkinter as tk
from tkinter import messagebox
import random
from collections import Counter
import math
import asyncio
import websockets
import threading
import json
import socket

# Core game logic
SUITS = ['d', 'c', 'h', 's']
SUIT_NAMES = {'d':'Diamonds', 'c':'Clubs', 'h':'Hearts', 's':'Spades'}
SUIT_ORDER = {'d':0, 'c':1, 'h':2, 's':3}
RANKS = ['3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A', '2']
RANK_NAMES = {'10':'10', 'J':'J', 'Q':'Q', 'K':'K', 'A':'A', '2':'2'}
RANK_ORDER = {r:i for i,r in enumerate(RANKS)}

class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def __str__(self):
        return f"{self.rank}{self.suit.upper()}"

    def key(self):
        return (RANK_ORDER[self.rank], SUIT_ORDER[self.suit])

    def image_path(self):
        r_disp = RANK_NAMES.get(self.rank, self.rank)
        return f"cards/{r_disp}{self.suit.upper()}.png"

    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit

    def __hash__(self):
        return hash((self.rank, self.suit))

    def to_dict(self):
        return {"rank": self.rank, "suit": self.suit}

    @classmethod
    def from_dict(cls, data):
        return cls(data["rank"], data["suit"])

class Big2App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Big 2 Card Game - Multiplayer")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)

        # Game state
        self.deck = []
        self.hands = [[] for _ in range(4)]
        self.selected_cards = []
        self.last_played_cards = []
        self.current_player = 0
        self.previous_move = None
        self.passes = 0
        self.game_over = False
        self.starter_idx = 0
        self.waiting_for_next_player = False
        self.game_started = False
        self.player_id = None
        self.connected = False
        self.websocket = None
        self.hand_sizes = [0, 0, 0, 0]
        self.player_names = []
        self.is_my_turn = False
        self.num_players = 4  # Default

        # Canvas and UI
        self.canvas = tk.Canvas(self.root, bg='green', width=1200, height=800)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(self.root, text="Not connected", font=("Arial", 16), bg='green', fg='white')
        self.status_label.place(relx=0.5, rely=0.05, anchor='center')

        # Buttons frame
        btn_frame = tk.Frame(self.root, bg='green')
        btn_frame.place(relx=0.5, rely=0.9, anchor='center')

        self.pass_btn = tk.Button(btn_frame, text="Pass", command=self.pass_turn, width=10, font=("Arial", 12))
        self.pass_btn.pack(side=tk.LEFT, padx=5)

        self.play_btn = tk.Button(btn_frame, text="Play", command=self.play_selected, width=10, font=("Arial", 12))
        self.play_btn.pack(side=tk.LEFT, padx=5)

        self.new_game_btn = tk.Button(btn_frame, text="New Game", command=self.new_game, width=10, font=("Arial", 12))
        self.new_game_btn.pack(side=tk.LEFT, padx=5)

        self.next_player_btn = tk.Button(btn_frame, text="Next Player", command=self.next_player_manual, width=12, font=("Arial", 12), bg='lightblue')
        self.next_player_btn.pack(side=tk.LEFT, padx=5)

        self.connect_btn = tk.Button(btn_frame, text="Connect", command=self.show_connection_dialog, width=10, font=("Arial", 12), bg='lightgreen')
        self.connect_btn.pack(side=tk.LEFT, padx=5)

        self.bind_mouse()
        self.new_game()
        self.show_waiting_screen()

        self.root.mainloop()

    def bind_mouse(self):
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("<Escape>", lambda e: self.clear_selection())

    # ---------- Connection Methods ----------
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def show_connection_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Connect to Game Server")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Server Address:", font=("Arial", 10)).pack(pady=5)
        server_entry = tk.Entry(dialog, width=40)
        server_entry.pack(pady=5)
        server_entry.insert(0, f"ws://{self.get_local_ip()}:8765")

        tk.Label(dialog, text="Your Name:", font=("Arial", 10)).pack(pady=5)
        name_entry = tk.Entry(dialog, width=40)
        name_entry.pack(pady=5)
        name_entry.insert(0, f"Player")

        def do_connect():
            server = server_entry.get().strip()
            player_name = name_entry.get().strip() or "Player"
            dialog.destroy()
            self.connect_to_server(server, player_name)

        tk.Button(dialog, text="Connect", command=do_connect, width=15).pack(pady=15)
        tk.Button(dialog, text="Cancel", command=dialog.destroy, width=10).pack()

    def connect_to_server(self, server_address, player_name):
        def run_async_connect():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._connect(server_address, player_name))
            finally:
                loop.close()

        threading.Thread(target=run_async_connect, daemon=True).start()

    async def _connect(self, server_address, player_name):
        try:
            self.websocket = await websockets.connect(server_address)
            self.connected = True
            self.root.after(0, lambda: messagebox.showinfo("Connected", f"Connected to server at {server_address}"))

            await self.websocket.send(json.dumps({
                "type": "join",
                "player_name": player_name
            }))

            async for message in self.websocket:
                await self.handle_server_message(message)

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))
            self.connected = False

    async def handle_server_message(self, message):
        try:
            data = json.loads(message)
            self.root.after(0, lambda: self.process_game_message(data))
        except json.JSONDecodeError:
            print("Invalid JSON from server")

    def send_to_server(self, action_type, data):
        if not self.connected or not self.websocket:
            messagebox.showerror("Not Connected", "Not connected to server!")
            return

        def do_send():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                message = json.dumps({
                    "type": action_type,
                    "data": data
                })
                loop.run_until_complete(self.websocket.send(message))
                loop.close()
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Send Error", str(e)))

        threading.Thread(target=do_send, daemon=True).start()

    # ---------- Game Logic ----------
    def create_deck(self):
        self.deck = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

    def deal(self):
        self.create_deck()
        for i in range(52 // 4):
            for hand in self.hands:
                if self.deck:
                    hand.append(self.deck.pop())
        leftover = self.deck
        for h in self.hands:
            h.sort(key=lambda c: c.key())
        self.starter_idx = next(i for i, h in enumerate(self.hands) if Card('3','d') in h)
        self.hands[self.starter_idx].extend(leftover)
        self.hands[self.starter_idx].sort(key=lambda c: c.key())
        self.current_player = self.starter_idx

    def new_game(self):
        self.hands = [[] for _ in range(4)]
        self.selected_cards = []
        self.last_played_cards = []
        self.current_player = 0
        self.previous_move = None
        self.passes = 0
        self.game_over = False
        self.waiting_for_next_player = False
        self.game_started = False
        self.deal()
        self.redraw()
        self.update_status()

    # ---------- Event Handlers ----------
    def on_click(self, event):
        if not self.connected or self.game_over or self.waiting_for_next_player or not self.game_started:
            return
        
        if self.player_id is None:
            return
            
        if self.current_player != self.player_id:
            return
            
        x = event.x
        y = event.y

        if hasattr(self, 'card_rects') and len(self.card_rects) > self.player_id:
            for rect, card in self.card_rects[self.player_id]:
                left, top, right, bottom = rect
                if left <= x <= right and top <= y <= bottom:
                    if card in self.selected_cards:
                        self.selected_cards.remove(card)
                    else:
                        self.selected_cards.append(card)
                    self.redraw()
                    break

    def play_selected(self):
        if not self.connected or self.game_over or self.waiting_for_next_player or not self.game_started:
            return
        
        if self.player_id is None:
            return
            
        if self.current_player != self.player_id:
            messagebox.showinfo("Not Your Turn", "Please wait for your turn!")
            return
            
        if not self.selected_cards:
            messagebox.showerror("No Cards", "Please select cards to play!")
            return

        cards_data = [c.to_dict() for c in self.selected_cards]
        
        self.send_to_server("play", {
            "player_id": self.player_id,
            "selected_cards": cards_data
        })
        
        self.play_btn.config(state='disabled')
        self.pass_btn.config(state='disabled')

    def pass_turn(self):
        if not self.connected or self.game_over or self.waiting_for_next_player or not self.game_started:
            return
        
        if self.player_id is None:
            return
            
        if self.current_player != self.player_id:
            messagebox.showinfo("Not Your Turn", "Please wait for your turn!")
            return
            
        self.send_to_server("pass", {
            "player_id": self.player_id
        })
        self.waiting_for_next_player = True
        self.redraw()

    def next_player_manual(self):
        if not self.connected:
            if self.game_over:
                return
            if self.passes >= 3:
                self.previous_move = None
                self.passes = 0
            self.current_player = (self.current_player + 1) % 4
            self.waiting_for_next_player = False
            self.selected_cards = []
            self.redraw()
            self.update_status()
            if len(self.hands[self.current_player]) == 0:
                self.game_over = True
                messagebox.showinfo("Game Over", f"Player {self.current_player} wins!")

    def clear_selection(self):
        self.selected_cards = []
        self.redraw()

    # ---------- Server Message Processing ----------
    def process_game_message(self, data):
        msg_type = data.get("type")

        if msg_type == "joined":
            self.player_id = data["player_id"]
            players = data["players_in_room"]
            min_players = data["min_players"]
            waiting = data["waiting_for_players"]
            self.status_label.config(text=f"Connected as Player {self.player_id}. Waiting for players... ({players}/{min_players})")
            if waiting:
                self.show_waiting_screen()

        elif msg_type == "player_count":
            players = data["players_in_room"]
            min_players = data["min_players"]
            game_started = data["game_started"]
            if not game_started:
                self.status_label.config(text=f"Waiting for players... ({players}/{min_players})")
                self.show_waiting_screen()
            else:
                self.status_label.config(text=f"Game started! {players} players connected.")

        elif msg_type == "game_state":
            game_state = data["game_state"]
            self.update_game_state(game_state)

        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            messagebox.showerror("Invalid Play", error_msg)
            
            self.waiting_for_next_player = False
            self.selected_cards = []
            self.play_btn.config(state='normal')
            self.pass_btn.config(state='normal')
            self.redraw()

    def update_game_state(self, game_state):
        self.game_started = game_state.get("game_started", False)
        
        if not self.game_started:
            self.show_waiting_screen()
            return

        self.current_player = game_state["current_player"]
        self.previous_move = game_state["previous_move"]
        self.passes = game_state["passes"]
        self.game_over = game_state["game_over"]
        self.hand_sizes = game_state.get("hand_sizes", [0, 0, 0, 0])
        self.player_names = game_state.get("player_names", [])
        self.num_players = game_state.get("num_players", 4)
        
        if self.player_id is not None:
            self.is_my_turn = (self.current_player == self.player_id)
            if self.is_my_turn:
                self.waiting_for_next_player = False
                self.play_btn.config(state='normal')
                self.pass_btn.config(state='normal')
            else:
                self.waiting_for_next_player = True
                self.play_btn.config(state='disabled')
                self.pass_btn.config(state='disabled')

        if "your_hand" in game_state and self.player_id is not None:
            new_hand = [Card.from_dict(c) for c in game_state["your_hand"]]
            self.hands[self.player_id] = new_hand

        if "last_played_cards" in game_state:
            self.last_played_cards = [Card.from_dict(c) for c in game_state["last_played_cards"]]

        self.selected_cards = []

        self.redraw()
        self.update_status()

        if self.game_over:
            winner = game_state.get("winner")
            messagebox.showinfo("Game Over", f"Player {winner} wins!")

    # ---------- Drawing ----------
    def show_waiting_screen(self, message=None):
        self.canvas.delete("all")
        w = self.canvas.winfo_width() or 1200
        h = self.canvas.winfo_height() or 800
        self.canvas.create_text(w//2, h//2 - 50, text="Waiting for Game to Start", font=("Arial", 28, "bold"), fill="white")
        if message:
            self.canvas.create_text(w//2, h//2 + 20, text=message, font=("Arial", 18), fill="yellow")
        else:
            self.canvas.create_text(w//2, h//2 + 20, text="Connect to server and wait for enough players", font=("Arial", 18), fill="yellow")
        self.update_status()

    def redraw(self):
        self.canvas.delete("all")
        self.card_rects = [[] for _ in range(4)]

        canvas_width = self.canvas.winfo_width() or 1200
        canvas_height = self.canvas.winfo_height() or 800

        # Calculate dynamic card sizes based on number of cards and players
        max_cards = max(self.hand_sizes) if self.hand_sizes else 13
        
        # Base card dimensions
        base_card_w, base_card_h = 60, 90
        
        # Calculate scale based on hand size
        # For 13+ cards, make cards smaller
        if max_cards > 20:
            card_scale = 0.5  # Very small for 2 players (26 cards)
        elif max_cards > 15:
            card_scale = 0.65  # Small for 3 players (17-18 cards)
        elif max_cards > 10:
            card_scale = 0.8  # Normal for 4 players (13 cards)
        else:
            card_scale = 1.0  # Large for late game
        
        # Also scale based on window size
        window_scale = min(canvas_width/1200, canvas_height/800)
        final_scale = card_scale * window_scale
        
        card_w = base_card_w * final_scale
        card_h = base_card_h * final_scale
        
        # Calculate overlap based on number of cards
        # More cards = more overlap to fit on screen
        if max_cards > 20:
            overlap = 0.65  # 65% overlap for 26 cards
        elif max_cards > 15:
            overlap = 0.7
        elif max_cards > 10:
            overlap = 0.75
        else:
            overlap = 0.8

        # Positions for player hands - adjust for number of players
        if self.num_players == 2:
            positions = [(0.3, 0.25), (0.3, 0.65)]  # Top and bottom for 2 players
        elif self.num_players == 3:
            positions = [(0.3, 0.15), (0.3, 0.45), (0.3, 0.75)]
        else:
            positions = [(0.3, 0.15), (0.3, 0.35), (0.3, 0.55), (0.3, 0.75)]

        # Draw each player's hand
        for i in range(4):
            if i >= len(positions):
                continue
                
            x_rel, y_rel = positions[i]
            x = x_rel * canvas_width
            y = y_rel * canvas_height

            # Draw player label
            label = f"Player {i}"
            if self.player_names and i < len(self.player_names):
                label = self.player_names[i]
            if self.player_id is not None and i == self.player_id:
                label += " (you)"
            if self.game_started and self.current_player == i:
                label += " ←"
            self.canvas.create_text(x, y - card_h/2 - 20, text=label, font=("Arial", 12, "bold"), fill='white')

            if i == self.player_id:
                hand = self.hands[i] if i < len(self.hands) else []
                self.canvas.create_text(x, y + card_h/2 + 20, text=f"{len(hand)} cards", font=("Arial", 10), fill="white")
                
                if len(hand) > 0:
                    total_width = (len(hand) - 1) * card_w * overlap + card_w
                    start_x = x - total_width / 2
                    
                    # Adjust start_x if cards would go off screen
                    if start_x < 10:
                        start_x = 10
                    if start_x + total_width > canvas_width - 10:
                        start_x = canvas_width - total_width - 10
                    
                    for j, card in enumerate(hand):
                        cx = start_x + j * card_w * overlap
                        left = cx - card_w/2
                        top = y - card_h/2
                        right = cx + card_w/2
                        bottom = y + card_h/2
                        rect = (left, top, right, bottom)
                        self.card_rects[i].append((rect, card))
                        
                        can_highlight = (self.game_started and not self.game_over and 
                                       self.current_player == self.player_id and not self.waiting_for_next_player)
                        highlight = can_highlight and card in self.selected_cards
                        self.draw_card(cx, y, card, highlight=highlight, face_down=False, scale=final_scale)
                else:
                    self.canvas.create_text(x, y, text="(empty hand)", font=("Arial", 14, "bold"), fill="white")
            else:
                count = self.hand_sizes[i] if i < len(self.hand_sizes) else 0
                self.canvas.create_text(x, y + card_h/2 + 20, text=f"{count} cards", font=("Arial", 10), fill="white")
                
                if count > 0:
                    num_to_show = min(count, 3)
                    card_scale_small = final_scale * 0.6
                    small_w = base_card_w * card_scale_small
                    small_h = base_card_h * card_scale_small
                    for j in range(num_to_show):
                        offset_x = (j - (num_to_show - 1) / 2) * 15 * final_scale
                        offset_y = (j - (num_to_show - 1) / 2) * 3 * final_scale
                        self.draw_card(x + offset_x, y + offset_y, None, face_down=True, scale=card_scale_small)
                    
                    if count > 3:
                        self.canvas.create_text(x + 30*final_scale, y, text=f"+{count - 3}", font=("Arial", int(10*final_scale)), fill="white")
                else:
                    self.canvas.create_text(x, y, text="(empty)", font=("Arial", 12), fill="white")

        # Draw last played cards
        if self.last_played_cards:
            x = 0.7 * canvas_width
            y = 0.45 * canvas_height
            total_width = (len(self.last_played_cards) - 1) * card_w * overlap + card_w
            start_x = x - total_width / 2
            for j, card in enumerate(self.last_played_cards):
                cx = start_x + j * card_w * overlap
                self.draw_card(cx, y, card, highlight=False, face_down=False, scale=final_scale)
            self.canvas.create_text(x, y - card_h/2 - 10, text="Last Played:", font=("Arial", 12, "bold"), fill='white')

        if self.game_started and not self.game_over:
            self.draw_turn_indicator(positions)
        
        self.update_status()

    def draw_turn_indicator(self, positions):
        if not self.game_started:
            return
        canvas_width = self.canvas.winfo_width() or 1200
        canvas_height = self.canvas.winfo_height() or 800
        if self.current_player < len(positions):
            x_rel, y_rel = positions[self.current_player]
            x = x_rel * canvas_width
            y = y_rel * canvas_height
            self.canvas.create_rectangle(x - 150, y - 60, x + 150, y + 60,
                                         outline='gold', width=3, dash=(5,5))

    def draw_card(self, x, y, card, highlight=False, face_down=False, scale=1.0):
        canvas_width = self.canvas.winfo_width() or 1200
        canvas_height = self.canvas.winfo_height() or 800
        window_scale = min(canvas_width/1200, canvas_height/800)
        
        # Base card dimensions
        base_w, base_h = 60, 90
        w = base_w * scale
        h = base_h * scale
        
        # Ensure minimum card size
        if w < 20:
            w = 20
            h = 30

        if face_down:
            self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill='blue', outline='white', width=2)
            if scale > 0.3:
                self.canvas.create_text(x, y, text="?", font=('Arial', int(24*scale), 'bold'), fill='white')
            return

        if card is None:
            self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill='gray', outline='white')
            return

        color = 'black' if card.suit in ['s','c'] else 'red'
        self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill='white', outline=color, width=max(1, int(3*scale)))
        
        if highlight:
            self.canvas.create_rectangle(x-w/2+3*scale, y-h/2+3*scale, x+w/2-3*scale, y+h/2-3*scale, outline='yellow', width=max(2, int(4*scale)))

        # Only draw text if cards are large enough to read
        if scale > 0.25:
            font_size = max(6, int(14*scale))
            self.canvas.create_text(x-w/2+10*scale, y-h/2+10*scale, text=card.rank, font=('Arial', font_size, 'bold'), fill=color)
            self.canvas.create_text(x+w/2-10*scale, y+h/2-10*scale, text=card.rank, font=('Arial', font_size, 'bold'), fill=color)
            suit_sym = {'s':'♠', 'h':'♥', 'd':'♦', 'c':'♣'}[card.suit]
            sym_size = max(8, int(20*scale))
            self.canvas.create_text(x, y-h/2+25*scale, text=suit_sym, font=('Arial', sym_size), fill=color)
            self.canvas.create_text(x, y+h/2-25*scale, text=suit_sym, font=('Arial', sym_size), fill=color)

    def update_status(self):
        if not self.connected:
            self.status_label.config(text="Not connected to server. Click 'Connect' to join.")
        elif self.game_over:
            self.status_label.config(text="Game Over! Click 'New Game' to restart.")
        elif not self.game_started:
            self.status_label.config(text="Waiting for game to start...")
        elif self.waiting_for_next_player:
            self.status_label.config(text="Waiting for other players to take their turn...")
        else:
            turn_player = self.current_player
            is_your_turn = (self.player_id == turn_player)
            if is_your_turn:
                turn_text = "🎯 YOUR TURN - Select cards and click Play"
                self.status_label.config(
                    text=f"{turn_text} | Passes: {self.passes} | Your cards: {len(self.hands[self.player_id]) if self.player_id is not None else '?'}"
                )
            else:
                turn_text = f"Player {turn_player}'s turn"
                self.status_label.config(
                    text=f"{turn_text} | Passes: {self.passes} | Your cards: {len(self.hands[self.player_id]) if self.player_id is not None else '?'}"
                )

if __name__ == "__main__":
    app = Big2App()
