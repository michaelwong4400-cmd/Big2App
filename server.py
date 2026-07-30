def process_game_message(self, data):
    """Process game state from server"""
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
