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
        self.num_players = 4
        
        # CRITICAL: This MUST be set by the server
        self.must_play_three_diamonds = False
        
        # Track if the game has started and 3D has been played
        self.three_diamonds_played_in_game = False

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

        self.connect_btn = tk.Button(btn_frame, text="Connect", command=self.show_connection_dialog, width=10, font=("Arial", 12), bg='lightgreen')
        self.connect_btn.pack(side=tk.LEFT, padx=5)

        self.bind_mouse()
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
        name_entry.insert(0, "Player")

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
            self.root.after(0, lambda: messagebox.showinfo("Connected", f"Connected to server"))

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
        self.must_play_three_diamonds = False
        self.three_diamonds_played_in_game = False
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

        # Check each card rectangle for the current player
        if hasattr(self, 'card_rects') and len(self.card_rects) > self.player_id:
            for rect, card in reversed(self.card_rects[self.player_id]):
                left, top, right, bottom = rect
                padding = 5
                if (left - padding) <= x <= (right + padding) and (top - padding) <= y <= (bottom + padding):
                    is_three_diamonds = (card.rank == '3' and card.suit == 'd')
                    
                    # CRITICAL FIX: Check if 3D must be played
                    if self.must_play_three_diamonds:
                        print(f"DEBUG: must_play_three_diamonds is TRUE - enforcing 3D rule")
                        
                        # Only allow selecting 3 of diamonds first
                        if is_three_diamonds:
                            # Select ONLY the 3 of diamonds
                            self.selected_cards = [card]
                            self.status_label.config(text="✅ 3♦ selected! Now add other cards for your play")
                            self.redraw()
                            break
                        else:
                            # Check if 3D is already selected
                            has_3d = any(c.rank == '3' and c.suit == 'd' for c in self.selected_cards)
                            if has_3d:
                                # 3D is selected, allow toggling other cards
                                if card in self.selected_cards:
                                    self.selected_cards.remove(card)
                                else:
                                    self.selected_cards.append(card)
                                self.redraw()
                                break
                            else:
                                # 3D not selected - block selection
                                messagebox.showwarning(
                                    "3 of Diamonds Required!",
                                    "You MUST select the 3♦ card first!\n\n"
                                    "Click on the 3♦ card (it has a red border) before selecting other cards."
                                )
                                self.redraw()
                                break
                    else:
                        # Normal selection
                        if card in self.selected_cards:
                            self.selected_cards.remove(card)
                        else:
                            self.selected_cards.append(card)
                        self.redraw()
                        break

    def play_selected(self):
        # CRITICAL FIX: Check 3D rule BEFORE anything else
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

        # CRITICAL FIX: Enforce 3D rule here
        if self.must_play_three_diamonds:
            print(f"DEBUG: play_selected - must_play_three_diamonds is TRUE")
            has_three_diamonds = any(c.rank == '3' and c.suit == 'd' for c in self.selected_cards)
            
            if not has_three_diamonds:
                messagebox.showerror(
                    "❌ 3 of Diamonds Required!",
                    "You MUST include the 3 of diamonds in your play!\n\n"
                    "This is the first play of the game.\n"
                    "Select the 3♦ card and try again."
                )
                self.selected_cards = []
                self.redraw()
                return
            
            print(f"DEBUG: 3D found in selection - proceeding")
        
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
        
        # CRITICAL FIX: Block pass if 3D must be played
        if self.must_play_three_diamonds:
            hand = self.hands[self.player_id] if self.player_id < len(self.hands) else []
            has_three_diamonds = any(c.rank == '3' and c.suit == 'd' for c in hand)
            if has_three_diamonds:
                messagebox.showerror(
                    "❌ Cannot Pass!",
                    "You MUST play the 3 of diamonds!\n\n"
                    "You have the 3♦ and must play it first.\n"
                    "Click on the 3♦ card, select additional cards if desired, then click Play."
                )
                return
            
        self.send_to_server("pass", {
            "player_id": self.player_id
        })
        self.waiting_for_next_player = True
        self.redraw()

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
            
            if "3 of diamonds" in error_msg.lower() or "3♦" in error_msg:
                messagebox.showerror("❌ 3 of Diamonds Required!", 
                    f"{error_msg}\n\n"
                    "Remember: The first play MUST include the 3 of diamonds (3♦)!")
                # Auto-select 3D for the player
                if self.player_id is not None and self.player_id < len(self.hands):
                    for card in self.hands[self.player_id]:
                        if card.rank == '3' and card.suit == 'd':
                            self.selected_cards = [card]
                            break
            else:
                messagebox.showerror("Invalid Play", error_msg)
            
            self.waiting_for_next_player = False
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
        
        # CRITICAL FIX: Update the 3D flag from server
        self.must_play_three_diamonds = game_state.get("must_play_three_diamonds", False)
        
        print(f"DEBUG: update_game_state - must_play_three_diamonds = {self.must_play_three_diamonds}")
        
        if self.player_id is not None:
            self.is_my_turn = (self.current_player == self.player_id)
            if self.is_my_turn:
                self.waiting_for_next_player = False
                self.play_btn.config(state='normal')
                self.pass_btn.config(state='normal')
                
                # If 3D must be played, auto-select it
                if self.must_play_three_diamonds and self.player_id < len(self.hands):
                    self.selected_cards = []
                    for card in self.hands[self.player_id]:
                        if card.rank == '3' and card.suit == 'd':
                            self.selected_cards = [card]
                            print(f"DEBUG: Auto-selected 3D for player {self.player_id}")
                            break
                    self.status_label.config(text="🔴 3♦ auto-selected! Click Play to play it, or add more cards")
            else:
                self.waiting_for_next_player = True
                self.play_btn.config(state='disabled')
                self.pass_btn.config(state='disabled')

        if "your_hand" in game_state and self.player_id is not None:
            new_hand = [Card.from_dict(c) for c in game_state["your_hand"]]
            self.hands[self.player_id] = new_hand

        if "last_played_cards" in game_state:
            self.last_played_cards = [Card.from_dict(c) for c in game_state["last_played_cards"]]
            
            # Check if 3D was played
            if self.last_played_cards:
                self.three_diamonds_played_in_game = any(
                    c.rank == '3' and c.suit == 'd' for c in self.last_played_cards
                )
                if self.three_diamonds_played_in_game:
                    print(f"DEBUG: 3D was played in the game!")

        if not self.is_my_turn or self.game_over:
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

        # Calculate dynamic card sizes
        max_cards = max(self.hand_sizes) if self.hand_sizes else 13
        
        if max_cards > 20:
            card_scale = 0.5
            overlap = 0.65
        elif max_cards > 15:
            card_scale = 0.65
            overlap = 0.7
        elif max_cards > 10:
            card_scale = 0.8
            overlap = 0.75
        else:
            card_scale = 1.0
            overlap = 0.8
        
        window_scale = min(canvas_width/1200, canvas_height/800)
        final_scale = card_scale * window_scale
        
        card_w = 60 * final_scale
        card_h = 90 * final_scale

        # Positions based on number of players
        if self.num_players == 2:
            positions = [(0.3, 0.25), (0.3, 0.65)]
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

            # Player label
            label = f"Player {i}"
            if self.player_names and i < len(self.player_names):
                label = self.player_names[i]
            if self.player_id is not None and i == self.player_id:
                label += " (you)"
            if self.game_started and self.current_player == i:
                label += " ←"
            self.canvas.create_text(x, y - card_h/2 - 20, text=label, font=("Arial", 12, "bold"), fill='white')

            # BIG WARNING for 3D requirement
            if self.must_play_three_diamonds and i == self.player_id and self.current_player == i:
                self.canvas.create_text(x, y - card_h/2 - 55, text="🔴🔴🔴 3♦ REQUIRED FIRST! 🔴🔴🔴", 
                                       font=("Arial", 14, "bold"), fill='#FF0000')
                self.canvas.create_text(x, y - card_h/2 - 80, text="Click 3♦ card first!", 
                                       font=("Arial", 10, "bold"), fill='#FFA500')

            if i == self.player_id:
                hand = self.hands[i] if i < len(self.hands) else []
                self.canvas.create_text(x, y + card_h/2 + 20, text=f"{len(hand)} cards", font=("Arial", 10), fill="white")
                
                if len(hand) > 0:
                    total_width = (len(hand) - 1) * card_w * overlap + card_w
                    start_x = x - total_width / 2
                    
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
        
        base_w, base_h = 60, 90
        w = base_w * scale
        h = base_h * scale
        
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

        # Check if this is the 3 of diamonds
        is_three_diamonds = (card.rank == '3' and card.suit == 'd')
        must_play_3d = self.must_play_three_diamonds and is_three_diamonds and self.current_player == self.player_id

        color = 'black' if card.suit in ['s','c'] else 'red'
        self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill='white', outline=color, width=max(1, int(3*scale)))
        
        # SUPER PROMINENT 3D HIGHLIGHTING
        if must_play_3d:
            # Multiple pulsing borders
            self.canvas.create_rectangle(x-w/2-8*scale, y-h/2-8*scale, x+w/2+8*scale, y+h/2+8*scale, 
                                        outline='#FF0000', width=max(5, int(8*scale)))
            self.canvas.create_rectangle(x-w/2-4*scale, y-h/2-4*scale, x+w/2+4*scale, y+h/2+4*scale, 
                                        outline='#FFA500', width=max(3, int(5*scale)))
            # Big text labels
            if scale > 0.3:
                self.canvas.create_text(x, y - h/2 - 18*scale, text="🔴 MUST PLAY FIRST!", 
                                       font=('Arial', int(10*scale), 'bold'), fill='#FF0000')
                self.canvas.create_text(x, y + h/2 + 18*scale, text="CLICK ME FIRST!", 
                                       font=('Arial', int(9*scale), 'bold'), fill='#FFA500')
        
        # Selection highlight
        if highlight:
            self.canvas.create_rectangle(x-w/2-4*scale, y-h/2-4*scale, x+w/2+4*scale, y+h/2+4*scale, 
                                        outline='yellow', width=max(3, int(6*scale)))
            self.canvas.create_text(x, y + h/2 - 8*scale, text="✓ SELECTED", 
                                   font=('Arial', int(10*scale), 'bold'), fill='yellow')

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
                if self.must_play_three_diamonds:
                    self.status_label.config(
                        text=f"🔴🔴🔴 MUST PLAY 3♦ FIRST! Click the 3♦ card! 🔴🔴🔴"
                    )
                else:
                    self.status_label.config(
                        text=f"🎯 YOUR TURN | Cards: {len(self.hands[self.player_id]) if self.player_id is not None else '?'}"
                    )
            else:
                self.status_label.config(
                    text=f"Player {turn_player}'s turn | Your cards: {len(self.hands[self.player_id]) if self.player_id is not None else '?'}"
                )

if __name__ == "__main__":
    app = Big2App()
