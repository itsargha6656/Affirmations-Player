import tkinter as tk
from tkinter import filedialog, font as tkfont
import pygame
import os
import math
import random
import calendar
from datetime import datetime, timedelta
from mutagen.mp3 import MP3

pygame.mixer.init()

# ── State ──────────────────────────────────────────────────────────────────────
current_audio     = None
audio_length      = 0
stop_pressed      = False
is_paused         = False
is_seeking        = False
_play_start_wall  = None
_play_seek_offset = 0.0
_session_start    = None      # wall-clock when play() pressed (for duration calc)

# ── Files ──────────────────────────────────────────────────────────────────────
HISTORY_FILE = "affirmation_history.txt"    # legacy: dates only (streak)
SESSION_FILE = "affirmation_sessions.txt"   # NEW: full session log

# ── Palette ────────────────────────────────────────────────────────────────────
BG       = "#0d0d12"
CARD     = "#16161f"
ACCENT   = "#7c5cfc"
ACCENT2  = "#b48eff"
TEXT     = "#e8e6f0"
SUBTEXT  = "#6b6880"
BAR_CLR  = "#2a2738"
WAVE_CLR = "#7c5cfc"
WAVE_DIM = "#2a2738"
BTN_BG   = "#1e1c2a"
BTN_HOV  = "#2d2a40"
GREEN    = "#4ade80"
AMBER    = "#fbbf24"

# ══════════════════════════════════════════════════════════════════════════════
#  SESSION LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def _write_session(filename, started, duration_s):
    """Append one session record: date|time|duration|filename"""
    date_str  = started.strftime("%Y-%m-%d")
    time_str  = started.strftime("%H:%M:%S")
    dur_str   = fmt(duration_s)
    fname     = os.path.basename(filename) if filename else "unknown"
    with open(SESSION_FILE, "a", encoding="utf-8") as f:
        f.write(f"{date_str}|{time_str}|{dur_str}|{fname}\n")

def read_sessions():
    """Return list of dicts newest-first."""
    sessions = []
    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) == 4:
                    sessions.append({
                        "date": parts[0], "time": parts[1],
                        "duration": parts[2], "file": parts[3],
                    })
    except FileNotFoundError:
        pass
    return list(reversed(sessions))

def _end_session():
    """Log session when playback stops (natural finish or Stop button)."""
    global _session_start
    if _session_start is None or current_audio is None:
        return
    played_s = int((datetime.now() - _session_start).total_seconds())
    if played_s >= 5:                          # ignore accidental 1-second presses
        _write_session(current_audio, _session_start, played_s)
        if _history_win_exists():
            _refresh_history()
    _session_start = None

def _history_win_exists():
    return (_hist_state["win"] is not None and
            _hist_state["win"].winfo_exists())

# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def load_audio():
    global current_audio, audio_length
    file = filedialog.askopenfilename(filetypes=[("MP3 files", "*.mp3")])
    if file:
        current_audio = file
        audio = MP3(file)
        audio_length = int(audio.info.length)
        timeline_var.set(0)
        timeline.config(to=max(1, audio_length))
        name = os.path.basename(file)
        file_label.config(text=name[:42] + ("…" if len(name) > 42 else ""))
        duration_label.config(text=f"00:00 / {fmt(audio_length)}")
        draw_waveform(idle=True)

def play_audio():
    global stop_pressed, _play_start_wall, _play_seek_offset, _session_start
    if current_audio is None:
        return
    stop_pressed = False
    is_paused    = False
    offset = float(timeline_var.get())
    pygame.mixer.music.load(current_audio)
    pygame.mixer.music.play(start=offset)
    _play_seek_offset = offset
    _play_start_wall  = datetime.now()
    _session_start    = datetime.now()
    log_affirmation()
    animate_waveform()
    _poll_position()

def pause_audio():
    global is_paused
    is_paused = True
    pygame.mixer.music.pause()
    stop_waveform_anim()

def resume_audio():
    global is_paused
    is_paused = False
    pygame.mixer.music.unpause()
    animate_waveform()

def stop_audio():
    global stop_pressed, is_paused
    stop_pressed = True
    is_paused    = False
    _end_session()
    pygame.mixer.music.stop()
    stop_waveform_anim()
    timeline_var.set(0)
    duration_label.config(text=f"00:00 / {fmt(audio_length)}")

def forward_audio():
    global _play_start_wall, _play_seek_offset
    if _play_start_wall is None:
        return
    elapsed = (datetime.now() - _play_start_wall).total_seconds()
    cur = _play_seek_offset + elapsed
    new_pos = min(audio_length, cur + 10)
    pygame.mixer.music.play(start=float(new_pos))
    _play_seek_offset = float(new_pos)
    _play_start_wall  = datetime.now()

def backward_audio():
    global _play_start_wall, _play_seek_offset
    if _play_start_wall is None:
        return
    elapsed = (datetime.now() - _play_start_wall).total_seconds()
    cur = _play_seek_offset + elapsed
    new_pos = max(0, cur - 10)
    pygame.mixer.music.play(start=float(new_pos))
    _play_seek_offset = float(new_pos)
    _play_start_wall  = datetime.now()

def sleep_pc():
    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

# ── Timeline ───────────────────────────────────────────────────────────────────

def on_timeline_press(event):
    global is_seeking
    is_seeking = True

def on_timeline_release(event):
    global is_seeking, _play_start_wall, _play_seek_offset
    is_seeking = False
    val = timeline_var.get()
    if current_audio:
        pygame.mixer.music.play(start=float(val))
        _play_seek_offset = float(val)
        _play_start_wall  = datetime.now()
        animate_waveform()

def _poll_position():
    if is_paused:
        # Still paused — keep the poll alive but don't advance position or sleep
        root.after(400, _poll_position)
        return

    if pygame.mixer.music.get_busy():
        if not is_seeking and _play_start_wall is not None:
            elapsed = (datetime.now() - _play_start_wall).total_seconds()
            pos = min(_play_seek_offset + elapsed, audio_length)
            timeline_var.set(pos)
            duration_label.config(text=f"{fmt(int(pos))} / {fmt(audio_length)}")
        root.after(400, _poll_position)
    else:
        # get_busy() is False AND we're not paused/stopped → track finished naturally
        if not stop_pressed:
            # Double-check: position must be near the end (within 3 s)
            if _play_start_wall is not None:
                elapsed = (datetime.now() - _play_start_wall).total_seconds()
                pos = _play_seek_offset + elapsed
                if pos >= audio_length - 3:
                    _end_session()
                    stop_waveform_anim()
                    root.after(2000, sleep_pc)

# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

# ── Streak + legacy history ────────────────────────────────────────────────────

def log_affirmation():
    today = datetime.now().strftime("%Y-%m-%d")
    with open(HISTORY_FILE, "a") as f:
        f.write(today + "\n")
    update_streak()
    draw_calendar()

def get_days():
    try:
        with open(HISTORY_FILE) as f:
            return set(f.read().splitlines())
    except FileNotFoundError:
        return set()

def update_streak():
    days = get_days()
    streak = sum(
        1 for i in range(7)
        if (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") in days
    )
    streak_label.config(text=f"🔥  {streak} / 7  day streak")

# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY WINDOW
# ══════════════════════════════════════════════════════════════════════════════

_hist_state = {"win": None, "canvas": None, "inner": None}

def _refresh_history():
    if not _history_win_exists():
        return
    for w in _hist_state["inner"].winfo_children():
        w.destroy()
    _populate_sessions(_hist_state["inner"])
    _hist_state["inner"].update_idletasks()
    _hist_state["canvas"].config(scrollregion=_hist_state["canvas"].bbox("all"))

def open_history_window():
    if _history_win_exists():
        _hist_state["win"].lift()
        return

    win = tk.Toplevel(root)
    win.title("Session History")
    win.geometry("560x580")
    win.resizable(False, True)
    win.configure(bg=BG)
    _hist_state["win"] = win

    # ── Top bar ───────────────────────────────────────────────────────────────
    top = tk.Frame(win, bg=BG)
    top.pack(fill="x", padx=22, pady=(18, 4))

    tk.Label(top, text="📋  SESSION HISTORY", fg=ACCENT2, bg=BG,
             font=tkfont.Font(family="Courier New", size=14, weight="bold")
             ).pack(side="left")

    sessions_all = read_sessions()
    days_set = {s["date"] for s in sessions_all}
    tk.Label(top,
             text=f"{len(sessions_all)} sessions  ·  {len(days_set)} active days",
             fg=SUBTEXT, bg=BG,
             font=tkfont.Font(family="Courier New", size=8)
             ).pack(side="right", pady=6)

    # ── Filter bar ────────────────────────────────────────────────────────────
    fbar = tk.Frame(win, bg=CARD)
    fbar.pack(fill="x", padx=22, pady=(0, 8))

    tk.Label(fbar, text=" 🔍 ", fg=SUBTEXT, bg=CARD,
             font=tkfont.Font(family="Courier New", size=9)).pack(side="left")

    filter_var = tk.StringVar()
    entry = tk.Entry(fbar, textvariable=filter_var,
                     bg=CARD, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=0,
                     font=tkfont.Font(family="Courier New", size=9),
                     width=28)
    entry.pack(side="left", ipady=6, padx=(0, 6))

    tk.Label(fbar, text="date (YYYY-MM-DD) or filename",
             fg=SUBTEXT, bg=CARD,
             font=tkfont.Font(family="Courier New", size=8)).pack(side="left")

    def _clear_filter():
        filter_var.set("")
        _apply_filter()

    tk.Button(fbar, text="✕",
              command=_clear_filter,
              fg=SUBTEXT, bg=CARD, activebackground=BTN_HOV,
              relief="flat", bd=0, cursor="hand2",
              font=tkfont.Font(family="Courier New", size=9),
              padx=8, pady=4).pack(side="right")

    def _apply_filter(*_):
        q = filter_var.get().strip().lower()
        filtered = [
            s for s in read_sessions()
            if not q or q in s["date"] or q in s["file"].lower()
        ]
        for w in _hist_state["inner"].winfo_children():
            w.destroy()
        _populate_sessions(_hist_state["inner"], filtered)
        _hist_state["inner"].update_idletasks()
        _hist_state["canvas"].config(
            scrollregion=_hist_state["canvas"].bbox("all"))

    entry.bind("<KeyRelease>", _apply_filter)

    # ── Scrollable list ───────────────────────────────────────────────────────
    container = tk.Frame(win, bg=BG)
    container.pack(fill="both", expand=True, padx=22, pady=(0, 4))

    hist_canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
    _hist_state["canvas"] = hist_canvas

    sb = tk.Scrollbar(container, orient="vertical",
                      command=hist_canvas.yview,
                      bg=CARD, troughcolor=BG, relief="flat")
    hist_canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    hist_canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(hist_canvas, bg=BG)
    _hist_state["inner"] = inner
    hist_canvas.create_window((0, 0), window=inner, anchor="nw")

    inner.bind("<Configure>",
               lambda e: hist_canvas.config(
                   scrollregion=hist_canvas.bbox("all")))

    def _mousewheel(e):
        hist_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    hist_canvas.bind_all("<MouseWheel>", _mousewheel)
    win.bind("<Destroy>", lambda e: hist_canvas.unbind_all("<MouseWheel>"))

    _populate_sessions(inner)

    # ── Footer ────────────────────────────────────────────────────────────────
    foot = tk.Frame(win, bg=BG)
    foot.pack(fill="x", padx=22, pady=(4, 14))

    tk.Button(foot, text="⬇  Export CSV",
              command=_export_csv,
              fg=TEXT, bg=BTN_BG, activebackground=BTN_HOV,
              relief="flat", bd=0, cursor="hand2",
              font=tkfont.Font(family="Courier New", size=9),
              padx=10, pady=5).pack(side="right")

    tk.Button(foot, text="↺  Refresh",
              command=_refresh_history,
              fg=SUBTEXT, bg=BTN_BG, activebackground=BTN_HOV,
              relief="flat", bd=0, cursor="hand2",
              font=tkfont.Font(family="Courier New", size=9),
              padx=10, pady=5).pack(side="right", padx=(0, 6))


def _populate_sessions(parent, sessions=None):
    """Render session rows grouped by date into parent frame."""
    if sessions is None:
        sessions = read_sessions()

    if not sessions:
        tk.Label(parent,
                 text="No sessions recorded yet.\nPress ▶ to start playing!",
                 fg=SUBTEXT, bg=BG, justify="center",
                 font=tkfont.Font(family="Courier New", size=10)
                 ).pack(pady=50)
        return

    # Group by date
    grouped = {}
    for s in sessions:
        grouped.setdefault(s["date"], []).append(s)

    for date_key, day_sessions in grouped.items():
        # Date heading
        try:
            dt       = datetime.strptime(date_key, "%Y-%m-%d")
            friendly = dt.strftime("%A, %d %B %Y")
            is_today = dt.date() == datetime.now().date()
            is_yest  = dt.date() == (datetime.now() - timedelta(days=1)).date()
            prefix   = "Today — " if is_today else ("Yesterday — " if is_yest else "")
        except ValueError:
            friendly = date_key
            is_today = False
            prefix   = ""

        drow = tk.Frame(parent, bg=BG)
        drow.pack(fill="x", pady=(12, 2), padx=4)

        tk.Label(drow,
                 text=f"  {prefix}{friendly}",
                 fg=ACCENT2 if is_today else TEXT,
                 bg=BG,
                 font=tkfont.Font(family="Courier New", size=9, weight="bold")
                 ).pack(side="left")

        total_dur = sum(
            int(s["duration"].split(":")[-1]) +
            int(s["duration"].split(":")[-2]) * 60 +
            (int(s["duration"].split(":")[0]) * 3600
             if s["duration"].count(":") == 2 else 0)
            for s in day_sessions
        )
        tk.Label(drow,
                 text=f"{len(day_sessions)} session{'s' if len(day_sessions)>1 else ''}  ·  {fmt(total_dur)} total",
                 fg=SUBTEXT, bg=BG,
                 font=tkfont.Font(family="Courier New", size=8)
                 ).pack(side="right", padx=8)

        tk.Frame(parent, height=1, bg=BAR_CLR).pack(fill="x", padx=6)

        # Session rows
        for s in day_sessions:
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill="x", padx=6, pady=2)

            # Time badge
            tk.Label(row,
                     text=f" {s['time']} ",
                     fg=BG, bg=ACCENT,
                     font=tkfont.Font(family="Courier New", size=8, weight="bold"),
                     padx=4, pady=3
                     ).pack(side="left", padx=(8, 10), pady=6)

            # File name
            fname = s["file"]
            display = fname[:34] + ("…" if len(fname) > 34 else "")
            tk.Label(row,
                     text=display, fg=TEXT, bg=CARD,
                     font=tkfont.Font(family="Courier New", size=9),
                     anchor="w"
                     ).pack(side="left", fill="x", expand=True)

            # Duration chip
            tk.Label(row,
                     text=f"⏱ {s['duration']}",
                     fg=GREEN, bg=CARD,
                     font=tkfont.Font(family="Courier New", size=8),
                     padx=8
                     ).pack(side="right", pady=6)

            # Hover
            def _enter(e, r=row):
                r.config(bg=BTN_HOV)
                for c in r.winfo_children():
                    try:
                        if c.cget("bg") == CARD:
                            c.config(bg=BTN_HOV)
                    except Exception:
                        pass

            def _leave(e, r=row):
                r.config(bg=CARD)
                for c in r.winfo_children():
                    try:
                        if c.cget("bg") == BTN_HOV:
                            c.config(bg=CARD)
                    except Exception:
                        pass

            row.bind("<Enter>", _enter)
            row.bind("<Leave>", _leave)


def _export_csv():
    out = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")],
        initialfile="affirmation_sessions.csv",
    )
    if not out:
        return
    sessions = list(reversed(read_sessions()))   # oldest first
    with open(out, "w", encoding="utf-8") as f:
        f.write("Date,Time,Duration Played,File\n")
        for s in sessions:
            f.write(f"{s['date']},{s['time']},{s['duration']},{s['file']}\n")

# ══════════════════════════════════════════════════════════════════════════════
#  WAVEFORM  — dynamic multi-layer visualizer
# ══════════════════════════════════════════════════════════════════════════════

BARS         = 52
W_CV, H_CV   = 430, 90          # canvas dimensions
Y_MID        = H_CV // 2

# Per-bar DNA: base amplitude shape (stays constant, gives each bar character)
_bar_dna     = [random.uniform(0.3, 1.0) for _ in range(BARS)]
# Smoothed current heights (eased toward targets every frame)
_bar_cur     = [0.08] * BARS
# Target heights (randomised each frame when playing)
_bar_tgt     = [0.08] * BARS

_wave_anim   = None
_wave_phase  = 0.0
_wave_tick   = 0               # frame counter for sparkle timing

# ── Colour helpers ─────────────────────────────────────────────────────────────

def _lerp_color(c1, c2, t):
    """Linearly interpolate between two '#rrggbb' colours."""
    r1,g1,b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    r = int(r1 + (r2-r1)*t)
    g = int(g1 + (g2-g1)*t)
    b = int(b1 + (b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"

# Gradient stops for active bars (bottom → top of bar = low → high energy)
_GRAD = ["#3b1fa8", "#7c5cfc", "#b48eff", "#e0c4ff"]

def _bar_color(norm_height, idle=False):
    """Return a colour for a bar based on its normalised height 0-1."""
    if idle:
        return _lerp_color("#1a1730", "#2a2350", norm_height)
    # map height → gradient position
    stops = _GRAD
    t = norm_height * (len(stops) - 1)
    idx = min(int(t), len(stops) - 2)
    return _lerp_color(stops[idx], stops[idx + 1], t - idx)

def _reflection_color(norm_height, idle=False):
    if idle:
        return _lerp_color("#0d0d12", "#1a1730", norm_height * 0.4)
    return _lerp_color("#0d0d12", "#3b1fa8", norm_height * 0.45)


# ── Sparkle particles ──────────────────────────────────────────────────────────
_sparks = []   # list of [x, y, vx, vy, life, max_life, color]

def _emit_sparks(x, y, color):
    for _ in range(random.randint(1, 3)):
        _sparks.append([
            x, y,
            random.uniform(-1.2, 1.2),   # vx
            random.uniform(-2.5, -0.5),  # vy  (fly upward)
            8, 8,                         # life, max_life
            color,
        ])

def _tick_sparks():
    dead = []
    for s in _sparks:
        s[0] += s[2]
        s[1] += s[3]
        s[3] += 0.18          # gravity
        s[4] -= 1
        if s[4] <= 0:
            dead.append(s)
    for s in dead:
        _sparks.remove(s)

def _draw_sparks():
    for s in _sparks:
        alpha = s[4] / s[5]   # 1 → 0
        c = _lerp_color("#0d0d12", s[6], alpha)
        r = max(1, int(alpha * 2.5))
        waveform_canvas.create_oval(
            s[0]-r, s[1]-r, s[0]+r, s[1]+r,
            fill=c, outline="")


# ── Core draw ──────────────────────────────────────────────────────────────────

def draw_waveform(idle=False):
    waveform_canvas.delete("all")
    bar_w = W_CV / BARS

    # ── 1. Glow centre line ──────────────────────────────────────────────────
    line_col = "#2a2350" if idle else "#5a3fd4"
    waveform_canvas.create_line(
        0, Y_MID, W_CV, Y_MID,
        fill=line_col, width=1)

    for i in range(BARS):
        h     = _bar_cur[i]          # normalised 0-1
        bh    = max(2, int(h * (Y_MID - 4)))   # pixel height (half-bar)
        x1    = int(i * bar_w) + 1
        x2    = int((i + 1) * bar_w) - 1
        cx    = (x1 + x2) // 2

        fill  = _bar_color(h, idle)
        refl  = _reflection_color(h, idle)
        cap   = _lerp_color(fill, "#ffffff", 0.55) if not idle else fill

        # ── 2. Reflection (below centre, faded + shorter) ────────────────────
        ref_h = int(bh * 0.45)
        if ref_h > 1:
            waveform_canvas.create_rectangle(
                x1, Y_MID + 2, x2, Y_MID + 2 + ref_h,
                fill=refl, outline="")

        # ── 3. Main bar (above centre) ───────────────────────────────────────
        waveform_canvas.create_rectangle(
            x1, Y_MID - bh, x2, Y_MID,
            fill=fill, outline="")

        # ── 4. Bright cap pixel on top of each bar ───────────────────────────
        if bh > 4 and not idle:
            waveform_canvas.create_rectangle(
                x1, Y_MID - bh, x2, Y_MID - bh + 2,
                fill=cap, outline="")

    # ── 5. Sparkle particles ─────────────────────────────────────────────────
    if not idle:
        _draw_sparks()


def animate_waveform():
    global _wave_phase, _wave_anim, _wave_tick
    _wave_phase += 0.14
    _wave_tick  += 1

    bar_w = W_CV / BARS

    # Update targets: layered sine waves give organic, non-repetitive motion
    for i in range(BARS):
        p  = i / BARS
        t  = (
            0.50 * abs(math.sin(_wave_phase * 1.1  + p * 6.3)) +
            0.25 * abs(math.sin(_wave_phase * 1.9  + p * 3.7)) +
            0.15 * abs(math.sin(_wave_phase * 0.7  + p * 9.1)) +
            0.10 * abs(math.sin(_wave_phase * 2.8  + p * 1.5))
        )
        _bar_tgt[i] = max(0.06, _bar_dna[i] * t)

    # Ease current → target (fast attack, slow decay)
    for i in range(BARS):
        diff = _bar_tgt[i] - _bar_cur[i]
        ease = 0.35 if diff > 0 else 0.12
        _bar_cur[i] += diff * ease

    # Emit sparks on tall bars every few frames
    if _wave_tick % 4 == 0:
        for i in range(BARS):
            if _bar_cur[i] > 0.78:
                x = int((i + 0.5) * bar_w)
                y = Y_MID - int(_bar_cur[i] * (Y_MID - 4))
                _emit_sparks(x, y, _bar_color(_bar_cur[i]))

    _tick_sparks()
    draw_waveform(idle=False)
    _wave_anim = root.after(33, animate_waveform)   # ~30 fps


def stop_waveform_anim():
    global _wave_anim
    if _wave_anim:
        root.after_cancel(_wave_anim)
        _wave_anim = None
    # Ease bars down to idle resting height
    _ease_to_idle()

def _ease_to_idle(step=0):
    """Smoothly shrink all bars to resting height over ~20 frames."""
    target = 0.08
    done   = True
    for i in range(BARS):
        _bar_cur[i] += (target - _bar_cur[i]) * 0.18
        if abs(_bar_cur[i] - target) > 0.005:
            done = False
    _sparks.clear()
    draw_waveform(idle=False)           # draw with current (shrinking) heights
    if not done and step < 40:
        root.after(33, lambda: _ease_to_idle(step + 1))
    else:
        for i in range(BARS):
            _bar_cur[i] = target
        draw_waveform(idle=True)

# ══════════════════════════════════════════════════════════════════════════════
#  CALENDAR
# ══════════════════════════════════════════════════════════════════════════════

CELL  = 32
CAL_W = 7 * CELL + 8
CAL_H = 5 * CELL + 36

def draw_calendar():
    cal_canvas.delete("all")
    days_done = get_days()
    today     = datetime.now()
    offset    = (today.replace(day=1).weekday() + 1) % 7

    for col, h in enumerate(["S","M","T","W","T","F","S"]):
        cal_canvas.create_text(col * CELL + CELL//2 + 4, 10,
                               text=h, fill=SUBTEXT,
                               font=("Courier New", 8, "bold"))

    for d in range(1, calendar.monthrange(today.year, today.month)[1] + 1):
        idx      = offset + d - 1
        cx       = (idx % 7) * CELL + CELL//2 + 4
        cy       = (idx // 7) * CELL + CELL//2 + 22
        date_str = today.replace(day=d).strftime("%Y-%m-%d")
        done     = date_str in days_done
        is_today = (d == today.day)

        if done:
            cal_canvas.create_oval(cx-12, cy-12, cx+12, cy+12,
                                   fill=ACCENT, outline="")
        elif is_today:
            cal_canvas.create_oval(cx-12, cy-12, cx+12, cy+12,
                                   fill="", outline=ACCENT, width=1.5)

        cal_canvas.create_text(cx, cy, text=str(d),
                               fill=TEXT if done or is_today else SUBTEXT,
                               font=("Courier New", 9,
                                     "bold" if is_today or done else "normal"))

# ══════════════════════════════════════════════════════════════════════════════
#  BUILD GUI
# ══════════════════════════════════════════════════════════════════════════════

root = tk.Tk()
root.title("Affirmation Player")
root.geometry("480x780")
root.resizable(False, False)
root.configure(bg=BG)

try:
    FONT_TITLE  = tkfont.Font(family="Courier New", size=18, weight="bold")
    FONT_SUB    = tkfont.Font(family="Courier New", size=9)
    FONT_TIME   = tkfont.Font(family="Courier New", size=10, weight="bold")
    FONT_STREAK = tkfont.Font(family="Courier New", size=11, weight="bold")
    FONT_CAL_H  = tkfont.Font(family="Courier New", size=11, weight="bold")
except Exception:
    FONT_TITLE = FONT_SUB = FONT_TIME = FONT_STREAK = FONT_CAL_H = None

def lbl(parent, text, fg=TEXT, bg=BG, fnt=None, **kw):
    return tk.Label(parent, text=text, fg=fg, bg=bg,
                    font=fnt or FONT_SUB, **kw)

def btn(parent, text, cmd, size=14):
    b = tk.Button(parent, text=text, command=cmd, fg=TEXT,
                  bg=BTN_BG, activebackground=BTN_HOV, activeforeground=ACCENT2,
                  relief="flat", bd=0, cursor="hand2",
                  font=tkfont.Font(family="Courier New", size=size),
                  padx=10, pady=6)
    b.bind("<Enter>", lambda e: b.config(bg=BTN_HOV))
    b.bind("<Leave>", lambda e: b.config(bg=BTN_BG))
    return b

# ── Header ─────────────────────────────────────────────────────────────────────
hdr = tk.Frame(root, bg=BG)
hdr.pack(fill="x", pady=(20, 4))
lbl(hdr, "🎧  AFFIRMATION PLAYER", fg=ACCENT2, fnt=FONT_TITLE).pack()
lbl(hdr, "daily mindset · sleep · growth", fg=SUBTEXT).pack()

# ── Player card ────────────────────────────────────────────────────────────────
card = tk.Frame(root, bg=CARD, bd=0)
card.pack(fill="x", padx=20, pady=10)

btn(card, "  ＋  Load MP3", load_audio, size=10).pack(pady=(14, 4))
file_label = lbl(card, "No file loaded", fg=SUBTEXT, bg=CARD)
file_label.pack()

tk.Frame(card, height=1, bg=BAR_CLR).pack(fill="x", padx=20, pady=8)
waveform_canvas = tk.Canvas(card, width=W_CV, height=H_CV,
                             bg=CARD, highlightthickness=0)
waveform_canvas.pack(pady=(0, 4))
draw_waveform(idle=True)
tk.Frame(card, height=1, bg=BAR_CLR).pack(fill="x", padx=20, pady=4)

time_row = tk.Frame(card, bg=CARD)
time_row.pack(fill="x", padx=20)
duration_label = lbl(time_row, "00:00 / 00:00",
                     fg=ACCENT2, bg=CARD, fnt=FONT_TIME)
duration_label.pack(side="right")

timeline_var = tk.DoubleVar(value=0)
timeline = tk.Scale(card,
    from_=0, to=1, orient="horizontal", length=W_CV,
    variable=timeline_var, showvalue=False,
    bg=CARD, troughcolor=BAR_CLR, activebackground=ACCENT,
    fg=ACCENT, highlightthickness=0, sliderrelief="flat",
    sliderlength=14, width=5)
timeline.pack(padx=20, pady=(4, 2))
timeline.bind("<ButtonPress-1>",   on_timeline_press)
timeline.bind("<ButtonRelease-1>", on_timeline_release)

ctrl = tk.Frame(card, bg=CARD)
ctrl.pack(pady=14)
btn(ctrl, "⏮", backward_audio, 16).grid(row=0, column=0, padx=6)
btn(ctrl, "▶", play_audio,     20).grid(row=0, column=1, padx=6)
btn(ctrl, "⏸", pause_audio,    16).grid(row=0, column=2, padx=6)
btn(ctrl, "⏵", resume_audio,   16).grid(row=0, column=3, padx=6)
btn(ctrl, "⏹", stop_audio,     16).grid(row=0, column=4, padx=6)
btn(ctrl, "⏭", forward_audio,  16).grid(row=0, column=5, padx=6)

# ── Streak row + History button ────────────────────────────────────────────────
srow = tk.Frame(root, bg=BG)
srow.pack(fill="x", padx=20, pady=(6, 0))

streak_label = lbl(srow, "🔥  0 / 7  day streak",
                   fg=ACCENT2, fnt=FONT_STREAK)
streak_label.pack(side="left")

hist_btn = tk.Button(srow,
    text="📋  History",
    command=open_history_window,
    fg=TEXT, bg=BTN_BG, activebackground=BTN_HOV, activeforeground=ACCENT2,
    relief="flat", bd=0, cursor="hand2",
    font=tkfont.Font(family="Courier New", size=9),
    padx=10, pady=4)
hist_btn.pack(side="right")
hist_btn.bind("<Enter>", lambda e: hist_btn.config(bg=BTN_HOV))
hist_btn.bind("<Leave>", lambda e: hist_btn.config(bg=BTN_BG))

# ── Calendar ───────────────────────────────────────────────────────────────────
cal_card = tk.Frame(root, bg=CARD, bd=0)
cal_card.pack(fill="x", padx=20, pady=10)

cal_hdr = tk.Frame(cal_card, bg=CARD)
cal_hdr.pack(fill="x", padx=12, pady=(10, 2))
lbl(cal_hdr, datetime.now().strftime("📅  %B %Y"),
    fg=TEXT, bg=CARD, fnt=FONT_CAL_H).pack(side="left")

cal_canvas = tk.Canvas(cal_card, width=CAL_W, height=CAL_H,
                        bg=CARD, highlightthickness=0)
cal_canvas.pack(padx=12, pady=(0, 12))

# ── Init ───────────────────────────────────────────────────────────────────────
update_streak()
draw_calendar()

root.mainloop()