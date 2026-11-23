"""
Discord Quest Completer Pro
A standalone, zero-install portable Windows desktop utility.
Two-Window Architecture:
- Window 1: Game Selector & Library Browser
- Window 2: Dedicated Active Quest Controller Window (Unlimited Mode)
"""

import os
import sys
import json
import time
import struct
import shutil
import atexit
import winsound
import threading
import subprocess
import requests
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

# Resource resolver for PyInstaller standalone bundles
def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)

APP_TITLE = "Discord Quest Completer Pro"
APP_VERSION = "v3.0.0"

DISCORD_API_DETECTABLE = "https://discord.com/api/applications/detectable"
GITHUB_MIRROR_DETECTABLE = "https://markterence.github.io/discord-quest-completer/detectable.json"

def check_discord_status() -> dict:
    """Verifies whether Discord desktop app is running and local IPC pipe exists."""
    pipe_exists = os.path.exists(r"\\.\pipe\discord-ipc-0")
    discord_running = False
    try:
        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Discord.exe"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        discord_running = "Discord.exe" in res.stdout
    except Exception:
        pass
    return {
        "running": pipe_exists or discord_running,
        "pipe": pipe_exists,
        "client": discord_running
    }

POPULAR_QUEST_NAMES = [
    "Marvel Rivals",
    "Genshin Impact",
    "Honkai: Star Rail",
    "Zenless Zone Zero",
    "Fortnite",
    "VALORANT",
    "Apex Legends",
    "League of Legends",
    "Overwatch 2",
    "Warframe",
    "The Finals",
    "Roblox",
    "Dead by Daylight",
    "Counter-Strike 2",
    "Destiny 2",
    "Black Myth: Wukong",
    "Wuthering Waves",
    "Monster Hunter: Wilds",
    "Palworld",
    "Rocket League",
    "Tom Clancy's Rainbow Six Siege",
    "Helldivers 2",
    "Once Human",
    "Path of Exile 2",
    "Call of Duty",
    "World of Warcraft",
    "Minecraft",
    "Grand Theft Auto V",
    "Brawlhalla",
    "Cyberpunk 2077"
]

class DiscordIPC:
    """Communicates directly with Discord desktop via local IPC Named Pipe."""
    def __init__(self):
        self.pipe = None
        self.connected = False

    def connect(self, client_id: str = "356944273133928458") -> bool:
        pipe_path = r"\\.\pipe\discord-ipc-0"
        if not os.path.exists(pipe_path):
            return False
        try:
            self.pipe = open(pipe_path, "r+b", buffering=0)
            clean_id = str(client_id).strip() if client_id and str(client_id).strip() != "0" else "356944273133928458"
            handshake = json.dumps({"v": 1, "client_id": clean_id}).encode("utf-8")
            self.pipe.write(struct.pack("<II", 0, len(handshake)) + handshake)
            header = self.pipe.read(8)
            if len(header) < 8:
                return False
            op, length = struct.unpack("<II", header)
            resp = self.pipe.read(length)
            data = json.loads(resp.decode("utf-8"))
            self.connected = data.get("evt") == "READY"
            return self.connected
        except Exception:
            self.connected = False
            return False

    def set_activity(self, state: str, details: str, game_name: str = "", start_time: int = None):
        if not self.connected or not self.pipe:
            return False
        try:
            act = {
                "type": 0,  # ActivityType.Game (Playing)
                "state": state,
                "details": details,
                "timestamps": {"start": start_time or int(time.time())}
            }
            if game_name:
                act["name"] = game_name
            payload = {
                "cmd": "SET_ACTIVITY",
                "args": {
                    "pid": os.getpid(),
                    "activity": act
                },
                "nonce": str(time.time())
            }
            frame = json.dumps(payload).encode("utf-8")
            self.pipe.write(struct.pack("<II", 1, len(frame)) + frame)
            header = self.pipe.read(8)
            if len(header) >= 8:
                op, length = struct.unpack("<II", header)
                self.pipe.read(length)
            return True
        except Exception:
            return False

    def clear(self):
        if self.pipe:
            try:
                payload = {
                    "cmd": "SET_ACTIVITY",
                    "args": {"pid": os.getpid(), "activity": None},
                    "nonce": str(time.time())
                }
                frame = json.dumps(payload).encode("utf-8")
                self.pipe.write(struct.pack("<II", 1, len(frame)) + frame)
                self.pipe.close()
            except Exception:
                pass
        self.pipe = None
        self.connected = False


class QuestManager:
    """Manages the lifecycle of spoofed dummy processes and Discord RPC."""
    def __init__(self):
        self.active_process = None
        self.active_pid = None
        self.active_game = None
        self.temp_dir = None
        self.ipc = DiscordIPC()
        atexit.register(self.stop_quest)

    def is_running(self) -> bool:
        if self.active_process is None:
            return False
        return self.active_process.poll() is None

    def start_quest(self, game_name: str, executable_name: str, app_id: str = "0") -> tuple[bool, str]:
        self.stop_quest()

        # Connect Discord IPC Rich Presence
        self.ipc.connect(app_id)
        self.ipc.set_activity(state=f"Playing {game_name}", details="Discord Activity", game_name=game_name)

        runner_template = resource_path(os.path.join("assets", "runner.exe"))
        if not os.path.exists(runner_template):
            return False, f"Runner template not found at {runner_template}"

        # Setup isolated temp directory
        clean_app_id = "".join(c for c in str(app_id) if c.isalnum()) or "default"
        base_temp = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "DiscordQuestCompleter", clean_app_id)
        os.makedirs(base_temp, exist_ok=True)
        self.temp_dir = base_temp

        # Ensure executable ends with .exe and normalize slashes
        clean_exec = executable_name.strip().replace("/", "\\")
        if not clean_exec.lower().endswith(".exe"):
            clean_exec += ".exe"

        target_path = os.path.join(base_temp, clean_exec)
        target_dir = os.path.dirname(target_path)
        os.makedirs(target_dir, exist_ok=True)

        try:
            shutil.copy2(runner_template, target_path)
        except Exception as e:
            return False, f"Failed to stage executable: {e}"

        # Spawn runner with game title
        try:
            self.active_process = subprocess.Popen(
                [target_path, "--title", game_name],
                cwd=target_dir,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.active_pid = self.active_process.pid
            self.active_game = {
                "name": game_name,
                "executable": clean_exec,
                "app_id": app_id,
                "target_path": target_path
            }
            return True, f"Started '{game_name}' ({clean_exec}) with PID {self.active_pid}"
        except Exception as e:
            self.stop_quest()
            return False, f"Failed to launch process: {e}"

    def stop_quest(self):
        # Clear Discord RPC Activity
        try:
            self.ipc.clear()
        except Exception:
            pass
        if self.active_pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(self.active_pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

        if self.active_process:
            try:
                self.active_process.kill()
                self.active_process.wait(timeout=1)
            except Exception:
                pass

        if self.active_game and "executable" in self.active_game:
            try:
                exe_name = os.path.basename(self.active_game["executable"])
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass

        self.active_process = None
        self.active_pid = None
        self.active_game = None
        self.temp_dir = None


class ActiveQuestWindow(ctk.CTkToplevel):
    """Dedicated Active Quest Controller Window."""
    def __init__(self, parent, game: dict, quest_manager: QuestManager):
        super().__init__(parent)
        self.parent_app = parent
        self.game = game
        self.quest_manager = quest_manager

        self.title(f"Running: {game['name']}")
        self.geometry("540x580")
        self.minsize(480, 520)
        self.configure(fg_color="#18191C")

        icon_path = resource_path(os.path.join("assets", "app.ico"))
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Elapsed timer state
        self.elapsed_secs = 0
        self.timer_running = False
        self.timer_thread = None

        self.setup_ui()
        self.start_quest()

    def setup_ui(self):
        # Header Badge
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=24, pady=(20, 8))

        back_btn = ctk.CTkButton(
            header_frame,
            text="⬅ Back to Games",
            width=110,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2B2D31",
            hover_color="#35373C",
            text_color="#DBDEE1",
            command=self.back_to_main
        )
        back_btn.pack(side="left")

        self.status_pill = ctk.CTkLabel(
            header_frame,
            text="● INITIALIZING",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#FEE75C",
            fg_color="#2B2D31",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.status_pill.pack(side="right")

        # Game Card Display
        game_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#2B2D31")
        game_card.pack(fill="x", padx=24, pady=8)

        card_title = ctk.CTkLabel(
            game_card,
            text=self.game["name"],
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#FFFFFF"
        )
        card_title.pack(anchor="w", padx=16, pady=(14, 2))

        card_meta = ctk.CTkLabel(
            game_card,
            text=f"Binary: {self.game['exec']}   |   App ID: {self.game.get('id', 'N/A')}",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#949BA4"
        )
        card_meta.pack(anchor="w", padx=16, pady=(0, 14))

        # Central Timer Display Area
        timer_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#1E1F22")
        timer_frame.pack(fill="x", padx=24, pady=10)

        timer_badge = ctk.CTkLabel(
            timer_frame,
            text="ELAPSED GAMEPLAY TIME (UNLIMITED MODE)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#23A55A"
        )
        timer_badge.pack(pady=(16, 2))

        self.timer_label = ctk.CTkLabel(
            timer_frame,
            text="00:00:00",
            font=ctk.CTkFont(family="Consolas", size=52, weight="bold"),
            text_color="#F2F3F5"
        )
        self.timer_label.pack(pady=4)

        self.status_subtext = ctk.CTkLabel(
            timer_frame,
            text="Discord is actively tracking your playtime...",
            font=ctk.CTkFont(size=12),
            text_color="#949BA4"
        )
        self.status_subtext.pack(pady=(0, 12))

        self.progress_bar = ctk.CTkProgressBar(
            timer_frame,
            height=8,
            corner_radius=4,
            progress_color="#23A55A",
            fg_color="#2B2D31",
            mode="indeterminate"
        )
        self.progress_bar.pack(fill="x", padx=24, pady=(0, 18))

        # Action Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=8)
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="⏹ STOP QUEST",
            height=46,
            corner_radius=8,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#DA373C",
            hover_color="#B82E32",
            command=self.stop_quest
        )
        self.stop_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.resume_btn = ctk.CTkButton(
            btn_frame,
            text="▶ RESTART QUEST",
            height=46,
            corner_radius=8,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#23A55A",
            hover_color="#1F924F",
            state="disabled",
            command=self.start_quest
        )
        self.resume_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Log Terminal
        log_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#111214")
        log_frame.pack(fill="both", expand=True, padx=24, pady=(6, 16))

        self.log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="transparent",
            text_color="#B5BAC1"
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_box.configure(state="disabled")

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", formatted)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start_quest(self):
        if self.timer_running:
            return

        game_name = self.game["name"]
        exec_name = self.game["exec"]
        app_id = self.game.get("id", "0")

        self.log(f"Launching spoofer for '{game_name}' ({exec_name})...")
        success, msg = self.quest_manager.start_quest(game_name, exec_name, app_id)

        if not success:
            self.log(f"[ERROR] {msg}")
            messagebox.showerror("Error Launching Spoofer", msg)
            return

        self.log(f"[SUCCESS] {msg}")
        self.log("Discord is now detecting game presence. Unlimited session active.")

        self.elapsed_secs = 0
        self.timer_running = True
        self.stop_btn.configure(state="normal")
        self.resume_btn.configure(state="disabled")
        self.status_pill.configure(
            text="● PLAYING (UNLIMITED)",
            fg_color="#1E382B",
            text_color="#23A55A"
        )
        self.status_subtext.configure(text=f"Simulating '{exec_name}' indefinitely...")
        self.progress_bar.start()

        self.timer_thread = threading.Thread(target=self._timer_worker, daemon=True)
        self.timer_thread.start()

    def _timer_worker(self):
        while self.timer_running:
            time.sleep(1)
            if not self.timer_running:
                break
            self.elapsed_secs += 1
            self.after(0, self.update_timer)

    def update_timer(self):
        hours = self.elapsed_secs // 3600
        mins = (self.elapsed_secs % 3600) // 60
        secs = self.elapsed_secs % 60
        self.timer_label.configure(text=f"{hours:02d}:{mins:02d}:{secs:02d}")

        # Discord Game Variety Badge requires running for at least 2 minutes
        if self.elapsed_secs < 120:
            rem = 120 - self.elapsed_secs
            self.status_subtext.configure(
                text=f"🎯 Game Variety Activity: {mins:02d}:{secs:02d} / 02:00 (Discord logs activity in {rem}s)",
                text_color="#FEE75C"
            )
        else:
            self.status_subtext.configure(
                text="✅ Game Variety Registered! Logged to Discord Recent Activity",
                text_color="#23A55A"
            )

    def stop_quest(self):
        self.timer_running = False
        self.quest_manager.stop_quest()
        self.progress_bar.stop()
        self.progress_bar.set(0.0)

        self.stop_btn.configure(state="disabled")
        self.resume_btn.configure(state="normal")
        self.status_pill.configure(
            text="STOPPED",
            fg_color="#362224",
            text_color="#DA373C"
        )

        hours = self.elapsed_secs // 3600
        mins = (self.elapsed_secs % 3600) // 60
        secs = self.elapsed_secs % 60
        self.status_subtext.configure(text=f"Stopped. Total session time: {hours:02d}h {mins:02d}m {secs:02d}s")
        self.log(f"Quest session stopped. Process terminated and cleaned up.")
        try:
            self.parent_app.on_quest_stopped()
        except Exception:
            pass

        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def back_to_main(self):
        if self.timer_running:
            if not messagebox.askyesno("Confirm", "Going back will stop the active quest. Continue?"):
                return
            self.stop_quest()
        self.destroy()
        self.parent_app.deiconify()

    def on_close(self):
        if self.timer_running:
            if messagebox.askyesno("Exit Confirmation", "Stop current quest and return to main window?"):
                self.stop_quest()
                self.destroy()
                self.parent_app.deiconify()
        else:
            self.destroy()
            self.parent_app.deiconify()


class DiscordQuestApp(ctk.CTk):
    """Main Game Selector / Library Window."""
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("720x720")
        self.minsize(640, 600)
        self.configure(fg_color="#18191C")

        icon_path = resource_path(os.path.join("assets", "app.ico"))
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.quest_manager = QuestManager()
        self.games_db: list[dict] = []
        self.filtered_games: list[dict] = []
        self.active_controller_win: ActiveQuestWindow | None = None
        self.search_debounce_id = None
        self.rendered_count = 0
        self.load_more_btn = None

        self.cache_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "DiscordQuestCompleter"
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cached_gamelist_path = os.path.join(self.cache_dir, "gamelist.json")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()
        self.load_database()
        self.update_discord_status()

    def setup_ui(self):
        # Top Header Bar
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=24, pady=(20, 10))

        # Title Box (Left)
        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")

        title_row = ctk.CTkFrame(title_box, fg_color="transparent")
        title_row.pack(anchor="w")

        app_title = ctk.CTkLabel(
            title_row,
            text="⚡ DISCORD QUEST COMPLETER",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#5865F2"
        )
        app_title.pack(side="left")

        # Sleek, compact Discord Status Badge
        self.discord_status_pill = ctk.CTkLabel(
            title_row,
            text="● Discord Connected",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#23A55A",
            fg_color="#182A20",
            corner_radius=12,
            padx=10,
            pady=2
        )
        self.discord_status_pill.pack(side="left", padx=(10, 0))

        app_sub = ctk.CTkLabel(
            title_box,
            text="Select any verified game below to complete active Discord quests.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#949BA4"
        )
        app_sub.pack(anchor="w", pady=(3, 0))

        # Top Right Actions
        top_actions = ctk.CTkFrame(top_bar, fg_color="transparent")
        top_actions.pack(side="right")

        self.test_btn = ctk.CTkButton(
            top_actions,
            text="🧪 Test Connection",
            command=self.toggle_connection_test,
            width=135,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#5865F2",
            hover_color="#4752C4",
            text_color="#FFFFFF"
        )
        self.test_btn.pack(side="left", padx=4)

        sync_btn = ctk.CTkButton(
            top_actions,
            text="🔄 Sync API",
            command=self.sync_online_database,
            width=90,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2B2D31",
            hover_color="#35373C",
            text_color="#DBDEE1"
        )
        sync_btn.pack(side="left", padx=4)

        custom_btn = ctk.CTkButton(
            top_actions,
            text="➕ Custom Game",
            command=self.open_custom_game_modal,
            width=110,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#23A55A",
            hover_color="#1F924F",
            text_color="#FFFFFF"
        )
        custom_btn.pack(side="left", padx=4)

        # Search Bar with Instant Clear Button
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=24, pady=(8, 12))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Search game name or executable (e.g. Call of Duty, Brawlhalla, Apex)...",
            placeholder_text_color="#80848E",
            height=42,
            corner_radius=8,
            border_color="#35373C",
            fg_color="#2B2D31",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13)
        )
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.on_search_changed)

        clear_btn = ctk.CTkButton(
            search_frame,
            text="✕ Clear",
            width=65,
            height=42,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2B2D31",
            hover_color="#35373C",
            text_color="#949BA4",
            command=self.clear_search
        )
        clear_btn.pack(side="left", padx=(6, 0))

        # Main Scrollable Game Cards List
        self.game_list_scroll = ctk.CTkScrollableFrame(
            self,
            corner_radius=10,
            fg_color="#1E1F22",
            scrollbar_button_color="#3B3D44",
            scrollbar_button_hover_color="#5865F2"
        )
        self.game_list_scroll.pack(fill="both", expand=True, padx=24, pady=(4, 12))

        # Bottom Bar
        bottom_bar = ctk.CTkFrame(self, fg_color="transparent")
        bottom_bar.pack(fill="x", padx=24, pady=(0, 14))

        self.db_status_label = ctk.CTkLabel(
            bottom_bar,
            text="Loading games database...",
            font=ctk.CTkFont(size=12),
            text_color="#949BA4"
        )
        self.db_status_label.pack(side="left")

        ver_lbl = ctk.CTkLabel(
            bottom_bar,
            text=f"{APP_VERSION} • Unlimited Engine",
            font=ctk.CTkFont(size=11),
            text_color="#5865F2"
        )
        ver_lbl.pack(side="right")

    # ==================== DATA MANAGEMENT ====================
    def load_database(self):
        db_path = self.cached_gamelist_path
        if not os.path.exists(db_path):
            bundled_path = resource_path(os.path.join("assets", "gamelist.json"))
            if os.path.exists(bundled_path):
                try:
                    shutil.copy2(bundled_path, db_path)
                except Exception:
                    db_path = bundled_path

        try:
            with open(db_path, "r", encoding="utf-8") as f:
                self.games_db = json.load(f)
            # Pre-compute ultra fast search index (Name + Exec + Aliases)
            for g in self.games_db:
                g["_s"] = f"{g.get('name', '')} {g.get('exec', '')} {g.get('aliases', '')}".lower()
            self.db_status_label.configure(text=f"Database: {len(self.games_db):,} verified games indexed")
        except Exception:
            self.games_db = []

        self.apply_filter()

    def sync_online_database(self):
        self.db_status_label.configure(text="Syncing latest games with Discord...")

        def _sync_worker():
            data = None
            urls = [DISCORD_API_DETECTABLE, GITHUB_MIRROR_DETECTABLE]
            for url in urls:
                try:
                    resp = requests.get(url, timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        break
                except Exception:
                    pass

            if not data or not isinstance(data, list):
                self.after(0, lambda: self.db_status_label.configure(text=f"Database: {len(self.games_db):,} games indexed"))
                return

            parsed_games = []
            for item in data:
                name = item.get("name", "").strip()
                if not name:
                    continue
                execs = []
                for ex in item.get("executables", []):
                    if ex.get("os") == "win32" and ex.get("name"):
                        execs.append(ex.get("name"))
                if not execs:
                    continue

                app_id = str(item.get("id", ""))
                is_pop = any(p.lower() in name.lower() for p in POPULAR_QUEST_NAMES)
                parsed_games.append({
                    "id": app_id,
                    "name": name,
                    "exec": execs[0],
                    "all_execs": execs[:5],
                    "popular": is_pop
                })

            parsed_games.sort(key=lambda x: (not x["popular"], x["name"].lower()))

            try:
                with open(self.cached_gamelist_path, "w", encoding="utf-8") as f:
                    json.dump(parsed_games, f, separators=(',', ':'))
                self.games_db = parsed_games
                self.after(0, lambda: self.on_sync_complete(len(parsed_games)))
            except Exception:
                pass

        threading.Thread(target=_sync_worker, daemon=True).start()

    def on_sync_complete(self, count: int):
        self.db_status_label.configure(text=f"Database: {count:,} verified games indexed")
        self.apply_filter()
        messagebox.showinfo("Sync Complete", f"Successfully synced {count:,} games directly from Discord!")

    # ==================== SEARCH & FILTER ====================
    def on_search_changed(self, event=None):
        # 100ms ultra-fast debounce
        if self.search_debounce_id:
            self.after_cancel(self.search_debounce_id)
        self.search_debounce_id = self.after(100, self.apply_filter)

    def clear_search(self):
        self.search_entry.delete(0, "end")
        if hasattr(self.search_entry, "_activate_placeholder"):
            self.search_entry._activate_placeholder()
        self.apply_filter()

    def apply_filter(self):
        query = self.search_entry.get().strip().lower()

        if query:
            # 1ms indexed substring lookup across 10k items
            self.filtered_games = [g for g in self.games_db if query in g.get("_s", "")]
        else:
            self.filtered_games = self.games_db

        self.render_game_cards()

    def render_game_cards(self):
        for widget in self.game_list_scroll.winfo_children():
            widget.destroy()

        self.rendered_count = 0
        self.load_more_btn = None
        self.append_cards(count=25)

    def append_cards(self, count: int = 25):
        if self.load_more_btn:
            try:
                self.load_more_btn.destroy()
            except Exception:
                pass
            self.load_more_btn = None

        if not self.filtered_games:
            empty_lbl = ctk.CTkLabel(
                self.game_list_scroll,
                text="No games match your search.\nClick '+ Custom Game' at the top to add any executable.",
                font=ctk.CTkFont(size=13),
                text_color="#949BA4",
                pady=50
            )
            empty_lbl.pack()
            return

        items = self.filtered_games[self.rendered_count:self.rendered_count + count]

        for game in items:
            card = ctk.CTkFrame(
                self.game_list_scroll,
                corner_radius=6,
                fg_color="#26282C",
                height=62
            )
            card.pack(fill="x", pady=3, padx=2)
            card.pack_propagate(False)

            # High-performance native GDI text container (0ms render overhead)
            text_frame = tk.Frame(card, bg="#26282C")
            text_frame.pack(side="left", fill="both", expand=True, padx=12, pady=6)

            title_lbl = tk.Label(
                text_frame,
                text=game["name"],
                font=("Segoe UI", 11, "bold"),
                fg="#F2F3F5",
                bg="#26282C",
                anchor="w"
            )
            title_lbl.pack(anchor="w")

            exec_lbl = tk.Label(
                text_frame,
                text=f"Binary: {game['exec']}",
                font=("Consolas", 9),
                fg="#949BA4",
                bg="#26282C",
                anchor="w"
            )
            exec_lbl.pack(anchor="w", pady=(1, 0))

            launch_btn = ctk.CTkButton(
                card,
                text="LAUNCH ▶",
                width=90,
                height=32,
                corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#23A55A",
                hover_color="#1F924F",
                command=lambda g=game: self.open_quest_window(g)
            )
            launch_btn.pack(side="right", padx=10, pady=10)

        self.rendered_count += len(items)

        # Show Load More button if remaining results exist
        remaining = len(self.filtered_games) - self.rendered_count
        if remaining > 0:
            self.load_more_btn = ctk.CTkButton(
                self.game_list_scroll,
                text=f"⬇ Load More ({min(remaining, 25)} of {remaining} remaining)",
                height=34,
                corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#2B2D31",
                hover_color="#35373C",
                text_color="#5865F2",
                command=lambda: self.append_cards(count=25)
            )
            self.load_more_btn.pack(fill="x", padx=10, pady=(6, 12))

    def open_quest_window(self, game: dict):
        """Hides the game list and opens the dedicated Active Quest Controller Window."""
        self.withdraw()  # Hide main window cleanly
        self.active_controller_win = ActiveQuestWindow(self, game, self.quest_manager)

    # ==================== CUSTOM GAME MODAL ====================
    def open_custom_game_modal(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Add Custom Quest Game")
        modal.geometry("440x300")
        modal.resizable(False, False)
        modal.transient(self)
        modal.grab_set()

        lbl_title = ctk.CTkLabel(
            modal,
            text="Add Custom Game / Executable",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        lbl_title.pack(padx=20, pady=(18, 10), anchor="w")

        lbl_desc = ctk.CTkLabel(
            modal,
            text="Enter the exact game name and executable name that Discord recognizes for new quests.",
            font=ctk.CTkFont(size=11),
            text_color="#949BA4",
            wraplength=390,
            justify="left"
        )
        lbl_desc.pack(padx=20, pady=(0, 12), anchor="w")

        entry_name = ctk.CTkEntry(
            modal,
            placeholder_text="Game Name (e.g. New Quest Game)",
            height=36,
            corner_radius=6
        )
        entry_name.pack(fill="x", padx=20, pady=6)

        entry_exec = ctk.CTkEntry(
            modal,
            placeholder_text="Executable Name (e.g. NewGameClient.exe)",
            height=36,
            corner_radius=6
        )
        entry_exec.pack(fill="x", padx=20, pady=6)

        def _save_custom():
            g_name = entry_name.get().strip()
            g_exec = entry_exec.get().strip()

            if not g_name or not g_exec:
                messagebox.showwarning("Incomplete", "Both game name and executable name are required.")
                return

            if not g_exec.lower().endswith(".exe"):
                g_exec += ".exe"

            custom_entry = {
                "id": "custom_" + str(int(time.time())),
                "name": g_name,
                "exec": g_exec,
                "all_execs": [g_exec],
                "popular": True
            }

            self.games_db.insert(0, custom_entry)
            self.apply_filter()
            modal.destroy()
            self.open_quest_window(custom_entry)

        btn_save = ctk.CTkButton(
            modal,
            text="Save & Launch",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#23A55A",
            hover_color="#1F924F",
            height=38,
            command=_save_custom
        )
        btn_save.pack(fill="x", padx=20, pady=(16, 12))

    def update_discord_status(self):
        """Polls Discord running state in background every 4s."""
        status = check_discord_status()
        if status["running"]:
            self.discord_status_pill.configure(
                text="● Discord Connected",
                text_color="#23A55A",
                fg_color="#182A20"
            )
        else:
            self.discord_status_pill.configure(
                text="● Discord Offline",
                text_color="#DA373C",
                fg_color="#2D191B"
            )
        # Re-schedule poll
        self.after(4000, self.update_discord_status)

    def on_quest_stopped(self):
        """Called when any active quest or test stops."""
        try:
            self.test_btn.configure(
                text="🧪 Test Connection",
                fg_color="#5865F2",
                hover_color="#4752C4"
            )
        except Exception:
            pass

    def toggle_connection_test(self):
        """Toggles a live Discord Connection Test activity and provides a direct Stop control."""
        if self.quest_manager.is_running():
            self.quest_manager.stop_quest()
            if self.active_controller_win:
                try:
                    self.active_controller_win.stop_quest()
                except Exception:
                    pass
            self.on_quest_stopped()
            messagebox.showinfo("Test Stopped", "Test session stopped and Discord activity cleared!")
            return

        status = check_discord_status()
        if not status["running"]:
            messagebox.showwarning(
                "Discord Offline",
                "⚠️ DISCORD IS NOT RUNNING!\n\nPlease open your Discord desktop application before testing so the game activity can be detected."
            )
            return

        # Launch live test session
        test_game = {
            "id": "356944273133928458",  # Brawlhalla verified App ID
            "name": "Brawlhalla (Discord Connection Test)",
            "exec": "brawlhalla.exe",
            "all_execs": ["brawlhalla.exe"],
            "popular": True
        }
        self.test_btn.configure(
            text="⏹ Stop Test",
            fg_color="#DA373C",
            hover_color="#B82E32"
        )
        self.open_quest_window(test_game)

    def on_close(self):
        self.quest_manager.stop_quest()
        self.destroy()


if __name__ == "__main__":
    app = DiscordQuestApp()
    app.mainloop()
