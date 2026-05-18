"""
MouseShifter  —  per-device mouse sensitivity switcher
pip install pywin32 customtkinter
"""

import ctypes, ctypes.wintypes as wt, winreg, re, threading, queue
import json, os, sys
import tkinter as tk
import customtkinter as ctk
import win32gui
from PIL import Image, ImageDraw
import pystray

# ──────────────────────────────────────────────────────────────────────────────
#  Theme
# ──────────────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG       = "#111111"
CARD     = "#191919"
CARD2    = "#202020"
CARD3    = "#272727"
BORDER   = "#2b2b2b"
BORDER_A = "#c47c20"
TEXT     = "#d4cfc6"
SUBT     = "#999999"
ACCENT   = "#e07d20"
ACCH     = "#f09030"
MONO     = "Consolas"

# ──────────────────────────────────────────────────────────────────────────────
#  Persistence
# ──────────────────────────────────────────────────────────────────────────────

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devices.json")

def load_saved() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_all(devices: dict):
    data = {}
    for h, dev in devices.items():
        data[h] = {
            "raw_id":        dev.raw_id,
            "name":          dev.name,
            "speed":         dev.speed,
            "accel":         dev.accel,
            "default_speed": dev.default_speed,
            "default_accel": dev.default_accel,
        }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────────────────────────
#  Windows API
# ──────────────────────────────────────────────────────────────────────────────

def win_get_speed() -> int:
    v = ctypes.c_int(0)
    ctypes.windll.user32.SystemParametersInfoW(0x0070, 0, ctypes.byref(v), 0)
    return v.value

def win_get_accel() -> bool:
    p = (ctypes.c_int * 3)()
    ctypes.windll.user32.SystemParametersInfoW(0x0003, 0, p, 0)
    return bool(p[2])

def win_set_speed(s: int):
    ctypes.windll.user32.SystemParametersInfoW(
        0x0071, 0, ctypes.c_void_p(max(1, min(20, s))), 0x03)

def win_set_accel(on: bool):
    p = (ctypes.c_int * 3)(0, 0, int(on))
    ctypes.windll.user32.SystemParametersInfoW(0x0004, 0, p, 0x03)

def registry_name(raw_id: str) -> str:
    try:
        path  = raw_id.strip("\\\\?\\").replace("#", "\\")
        parts = path.split("\\")
        key   = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    "SYSTEM\\CurrentControlSet\\Enum\\" + "\\".join(parts[:3]))
        name, _ = winreg.QueryValueEx(key, "DeviceDesc")
        winreg.CloseKey(key)
        return name.split(";")[-1].strip() if ";" in name else name.strip()
    except Exception:
        m = re.search(r'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})', raw_id)
        return f"VID:{m.group(1)} PID:{m.group(2)}" if m else "Unknown Mouse"

def vid_pid(raw_id: str) -> str:
    m = re.search(r'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})', raw_id)
    return f"VID: {m.group(1)}   PID: {m.group(2)}" if m else raw_id[-36:]

# ──────────────────────────────────────────────────────────────────────────────
#  Raw Input structures
# ──────────────────────────────────────────────────────────────────────────────

class _RID(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.WORD), ("usUsage", wt.WORD),
                ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]

class _RIH(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD),
                ("hDevice", ctypes.c_void_p), ("wParam", ctypes.c_ulonglong)]

class _RIM(ctypes.Structure):
    _fields_ = [("usFlags", wt.WORD), ("usButtonFlags", wt.WORD),
                ("usButtonData", wt.WORD), ("ulRawButtons", wt.ULONG),
                ("lLastX", wt.LONG), ("lLastY", wt.LONG),
                ("ulExtraInformation", wt.ULONG)]

class _RI(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mouse", _RIM)]
    _fields_ = [("header", _RIH), ("data", _U)]

def get_raw_id(hdev) -> str:
    sz = ctypes.c_uint(0)
    ctypes.windll.user32.GetRawInputDeviceInfoW(hdev, 0x20000007, None, ctypes.byref(sz))
    buf = ctypes.create_unicode_buffer(sz.value)
    ctypes.windll.user32.GetRawInputDeviceInfoW(hdev, 0x20000007, buf, ctypes.byref(sz))
    return buf.value

# ──────────────────────────────────────────────────────────────────────────────
#  Device model
# ──────────────────────────────────────────────────────────────────────────────

class Device:
    def __init__(self, handle: str, raw_id: str, saved: dict | None = None):
        self.handle      = handle
        self.raw_id      = raw_id
        self.vid_pid_str = vid_pid(raw_id)
        cur_speed        = win_get_speed()
        cur_accel        = win_get_accel()
        if saved:
            self.name          = saved.get("name", registry_name(raw_id))
            self.default_speed = saved.get("default_speed", cur_speed)
            self.default_accel = saved.get("default_accel", cur_accel)
            self.speed         = saved.get("speed", self.default_speed)
            self.accel         = saved.get("accel", self.default_accel)
        else:
            self.name          = registry_name(raw_id)
            self.default_speed = cur_speed
            self.default_accel = cur_accel
            self.speed         = cur_speed
            self.accel         = cur_accel

    def apply(self):
        win_set_speed(self.speed)
        win_set_accel(self.accel)

# ──────────────────────────────────────────────────────────────────────────────
#  Shared state
# ──────────────────────────────────────────────────────────────────────────────

_saved   = load_saved()
_devices: dict[str, Device] = {}
_lock    = threading.Lock()
_q: queue.Queue[str] = queue.Queue(maxsize=256)

for _h, _s in _saved.items():
    _devices[_h] = Device(_h, _s["raw_id"], saved=_s)

# ──────────────────────────────────────────────────────────────────────────────
#  Raw Input thread  —  only puts handle into queue
# ──────────────────────────────────────────────────────────────────────────────

def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == 0x00FF:
        sz = ctypes.c_uint(0)
        ctypes.windll.user32.GetRawInputData(
            lparam, 0x10000003, None, ctypes.byref(sz), ctypes.sizeof(_RIH))
        buf = ctypes.create_string_buffer(sz.value)
        ctypes.windll.user32.GetRawInputData(
            lparam, 0x10000003, buf, ctypes.byref(sz), ctypes.sizeof(_RIH))
        ri = _RI.from_buffer(buf)
        if ri.header.dwType == 0 and (ri.data.mouse.lLastX or ri.data.mouse.lLastY):
            h = str(ri.header.hDevice)
            with _lock:
                if h not in _devices:
                    rid   = get_raw_id(ri.header.hDevice)
                    saved = _saved.get(h)
                    _devices[h] = Device(h, rid, saved=saved)
            try:
                _q.put_nowait(h)
            except queue.Full:
                pass
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

def _raw_thread():
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc   = _wnd_proc
    wc.lpszClassName = "MSRaw"
    win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(wc.lpszClassName, "", 0, 0, 0, 0, 0, 0, 0, None, None)
    rid  = _RID()
    rid.usUsagePage = 0x01; rid.usUsage = 0x02
    rid.dwFlags = 0x00000100; rid.hwndTarget = hwnd
    ctypes.windll.user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid))
    win32gui.PumpMessages()

# ──────────────────────────────────────────────────────────────────────────────
#  DeviceCard  — customtkinter frame
# ──────────────────────────────────────────────────────────────────────────────

class DeviceCard(ctk.CTkFrame):
    def __init__(self, parent, dev: Device, save_fn, remove_fn, **kw):
        super().__init__(parent, fg_color=CARD, corner_radius=6,
                         border_width=1, border_color=BORDER, **kw)
        self.dev        = dev
        self._save_fn   = save_fn
        self._remove_fn = remove_fn
        self._active    = False
        self._deb       = None
        self._build()

    def _lbl(self, parent, text, size=10, color=SUBT, weight="normal", anchor="w", **kw):
        return ctk.CTkLabel(parent, text=text, anchor=anchor,
                            font=ctk.CTkFont(family=MONO, size=size, weight=weight),
                            text_color=color, **kw)

    def _build(self):
        # ── Header row: VID/PID  +  status dot ────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 0))

        self._lbl(hdr, self.dev.vid_pid_str, size=11, color=SUBT).pack(side="left")

        self._dot = self._lbl(hdr, "●", size=10, color=BORDER)
        self._dot.pack(side="right")

        # ── Name entry ─────────────────────────────────────────────────────────
        self._name_var = ctk.StringVar(value=self.dev.name)
        self._name_var.trace_add("write", self._on_name)

        name_entry = ctk.CTkEntry(
            self, textvariable=self._name_var,
            font=ctk.CTkFont(family=MONO, size=13, weight="bold"),
            fg_color=CARD2, border_color=BORDER, border_width=1,
            text_color=TEXT, placeholder_text="isim ver…",
            placeholder_text_color=SUBT, height=32, corner_radius=4)
        name_entry.pack(fill="x", padx=14, pady=(4, 0))

        # ── Divider ────────────────────────────────────────────────────────────
        tk.Frame(self, bg="#292929", height=1).pack(fill="x", padx=14, pady=(12, 0))

        # ── Sensitivity ────────────────────────────────────────────────────────
        sens_hdr = ctk.CTkFrame(self, fg_color="transparent")
        sens_hdr.pack(fill="x", padx=14, pady=(10, 0))
        self._lbl(sens_hdr, "HASSASİYET", size=11, color=SUBT).pack(side="left")

        self._sens_val_lbl = self._lbl(
            sens_hdr, f"{self.dev.speed} / 20",
            size=14, color=ACCENT, weight="bold", anchor="e")
        self._sens_val_lbl.pack(side="right")

        self._slider_var = tk.DoubleVar(value=self.dev.speed)
        self._slider = ctk.CTkSlider(
            self, from_=1, to=20, number_of_steps=19,
            variable=self._slider_var,
            fg_color=CARD3, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCH,
            command=self._on_slider)
        self._slider.pack(fill="x", padx=14, pady=(6, 0))

        self._def_s_lbl = self._lbl(self, f"Varsayılan: {self.dev.default_speed}",
                                    size=11, color="#666666")
        self._def_s_lbl.pack(fill="x", padx=14, pady=(3, 0))

        # ── Divider ────────────────────────────────────────────────────────────
        tk.Frame(self, bg="#292929", height=1).pack(fill="x", padx=14, pady=(10, 0))

        # ── Acceleration ───────────────────────────────────────────────────────
        accel_row = ctk.CTkFrame(self, fg_color="transparent")
        accel_row.pack(fill="x", padx=14, pady=(10, 14))

        self._lbl(accel_row, "MOUSE İVMESİ", size=11, color=SUBT).pack(side="left")

        self._accel_var = ctk.BooleanVar(value=self.dev.accel)
        self._accel_sw = ctk.CTkSwitch(
            accel_row, text="", variable=self._accel_var,
            width=40, height=20, switch_width=40, switch_height=20,
            fg_color=CARD3, progress_color=ACCENT,
            button_color="#888888", button_hover_color=TEXT,
            command=self._on_accel)
        self._accel_sw.pack(side="right")

        self._accel_lbl = self._lbl(
            accel_row,
            "Açık" if self.dev.accel else "Kapalı",
            size=11, color=ACCENT if self.dev.accel else SUBT)
        self._accel_lbl.pack(side="right", padx=(0, 8))

        self._def_a_lbl = self._lbl(
            self,
            f"Varsayılan: {'Açık' if self.dev.default_accel else 'Kapalı'}",
            size=11, color="#666666")
        self._def_a_lbl.pack(fill="x", padx=14, pady=(0, 0))

        # ── Remove button (bottom-right) ───────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkButton(
            btn_row, text="🗑", width=36, height=28,
            font=ctk.CTkFont(size=15),
            fg_color="transparent", hover_color="#2a0a0a",
            border_width=1, border_color="#6b1a1a",
            text_color="#cc2222", corner_radius=3,
            command=self._remove_fn,
        ).pack(side="right")

    # ── Active highlight ───────────────────────────────────────────────────────
    def set_active(self, on: bool):
        if self._active == on:
            return
        self._active = on
        GREEN = "#4caf7a"
        self.configure(
            fg_color=("#111d16" if on else CARD),
            border_color=(GREEN if on else BORDER),
            border_width=(2 if on else 1))
        self._dot.configure(text_color=(GREEN if on else BORDER),
                            font=ctk.CTkFont(size=(14 if on else 11)))

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _on_name(self, *_):
        self.dev.name = self._name_var.get()
        self._schedule(500, self._save)

    def _on_slider(self, val):
        v = round(float(val))
        self.dev.speed = v
        self._sens_val_lbl.configure(text=f"{v} / 20")
        self._schedule(120, self._commit)

    def _on_accel(self):
        on = self._accel_var.get()
        self.dev.accel = on
        self._accel_lbl.configure(
            text="Açık" if on else "Kapalı",
            text_color=ACCENT if on else SUBT)
        self._schedule(120, self._commit)

    def _schedule(self, ms: int, fn):
        if self._deb:
            self.after_cancel(self._deb)
        self._deb = self.after(ms, fn)

    def _commit(self):
        if self._active:
            self.dev.apply()
        self._save()

    def _save(self):
        self._save_fn()

# ──────────────────────────────────────────────────────────────────────────────
#  Main App
# ──────────────────────────────────────────────────────────────────────────────

COLS    = 3
GAP     = 12      # gap between cards
PAD     = 16      # left/right padding of the window
CARD_W  = 260     # fixed card width
TOP_PAD = 18      # extra top padding so cards start 6px lower

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MouseShifter")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self._set_icon()

        self._cards: dict[str, DeviceCard] = {}
        self._last_active: str | None = None
        self._card_h: int | None = None

        self._build()

        # pre-create cards for saved devices
        with _lock:
            for h, dev in _devices.items():
                self._create_card(h, dev)

        # tray
        self._tray: pystray.Icon | None = None
        self._start_tray()

        # minimize → tray, X → quit
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.bind("<Unmap>", self._on_unmap)

        # start hidden — show via tray
        self.withdraw()

        self._poll()

    # ── Layout helpers ─────────────────────────────────────────────────────────
    def _card_col_row(self, idx: int):
        return idx % COLS, idx // COLS

    def _win_w(self) -> int:
        # PAD + card + gap + card + gap + card + PAD
        return PAD * 2 + COLS * CARD_W + (COLS - 1) * GAP - 56

    def _win_h(self, rows: int) -> int:
        ftr = 34
        ch  = self._card_h or 260
        return TOP_PAD + rows * ch + (rows - 1) * GAP + GAP + ftr

    def _apply_geometry(self):
        rows = max(1, (len(self._cards) + COLS - 1) // COLS)
        self.geometry(f"{self._win_w()}x{self._win_h(rows)}")

    def _set_icon(self):
        sz  = 64
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.rounded_rectangle([14,  6, 50, 58], radius=14, fill="#1e1e1e", outline="#4caf7a", width=2)
        d.rounded_rectangle([27, 12, 37, 28], radius=4,  fill="#4caf7a")
        d.line([14, 32, 50, 32], fill="#4caf7a", width=1)
        d.rounded_rectangle([12,  4, 52, 60], radius=16, outline="#33aa6644", width=1)

        ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        img.save(ico_path, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
        self.iconbitmap(ico_path)

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        # ── Card grid container ────────────────────────────────────────────────
        self._grid_frame = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._grid_frame.pack(fill="both", expand=True)

        # ── Footer ────────────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=BORDER, height=1, corner_radius=0).pack(
            fill="x", side="bottom")
        ftr = ctk.CTkFrame(self, fg_color="#0d0d0d", corner_radius=0, height=28)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)

        # left — startup checkbox
        startup_row = ctk.CTkFrame(ftr, fg_color="transparent")
        startup_row.pack(side="left", padx=(12, 0))
        self._startup_var = tk.BooleanVar(value=self._get_startup())
        ctk.CTkCheckBox(
            startup_row, text="Başlangıçta Çalıştır",
            variable=self._startup_var,
            font=ctk.CTkFont(family=MONO, size=11),
            text_color=SUBT,
            fg_color="#3a7bd5", hover_color="#2e6bc4",
            border_color=BORDER,
            checkbox_width=14, checkbox_height=14,
            corner_radius=2,
            command=self._on_startup_toggle,
        ).pack(side="left")

        # right — active status
        self._stat_lbl = ctk.CTkLabel(
            ftr, text="Fare bekleniyor…",
            font=ctk.CTkFont(family=MONO, size=11),
            text_color=SUBT)
        self._stat_lbl.pack(side="right", padx=(4, 8))

        self._stat_dot = ctk.CTkLabel(
            ftr, text="●",
            font=ctk.CTkFont(size=11),
            text_color=SUBT)
        self._stat_dot.pack(side="right", padx=(0, 2))

        # center — system info (place after pack so it's truly centered)
        self._footer_lbl = ctk.CTkLabel(
            ftr, text="",
            font=ctk.CTkFont(family=MONO, size=11),
            text_color=SUBT, anchor="center")
        self._footer_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self._refresh_footer()

    # ── Card management ────────────────────────────────────────────────────────
    def _create_card(self, handle: str, dev: Device):
        if handle in self._cards:
            return
        card = DeviceCard(
            self._grid_frame, dev,
            save_fn=self._save,
            remove_fn=lambda h=handle: self._remove_device(h))
        self._cards[handle] = card
        self._reflow_cards()

    def _remove_device(self, handle: str):
        card = self._cards.pop(handle, None)
        if card:
            card.destroy()
        with _lock:
            _devices.pop(handle, None)
        _saved.pop(handle, None)
        self._save()
        self._reflow_cards()
        if self._last_active == handle:
            self._last_active = None
            if hasattr(self, "_stat_dot"):
                self._stat_dot.configure(text_color=SUBT)
                self._stat_lbl.configure(text="Fare bekleniyor…", text_color=SUBT)

    def _reflow_cards(self):
        for card in self._cards.values():
            card.grid_forget()

        n = len(self._cards)
        for idx, card in enumerate(self._cards.values()):
            col = idx % COLS
            row = idx // COLS
            # left padding for first col, gap between cols, right padding for last col
            padx_l = PAD if col == 0 else GAP // 2
            padx_r = PAD if col == COLS - 1 else GAP // 2
            pady_t = TOP_PAD if row == 0 else GAP
            pady_b = 0
            card.grid(row=row, column=col,
                      padx=(padx_l, padx_r),
                      pady=(pady_t, pady_b),
                      sticky="n")

        for c in range(COLS):
            self._grid_frame.columnconfigure(c, weight=0, minsize=CARD_W)

        rows_used = max(1, (n + COLS - 1) // COLS)
        self._grid_frame.rowconfigure(rows_used, minsize=GAP)

        if self._card_h is None and self._cards:
            self.after(60, self._measure_and_fit)
        else:
            self._apply_geometry()

    def _measure_and_fit(self):
        if self._card_h is None and self._cards:
            self.update_idletasks()
            h = next(iter(self._cards.values())).winfo_reqheight()
            if h > 10:
                self._card_h = h
        self._apply_geometry()

    # ── Persistence ───────────────────────────────────────────────────────────
    def _save(self):
        with _lock:
            save_all(_devices)

    # ── Footer ────────────────────────────────────────────────────────────────
    def _refresh_footer(self):
        self._footer_lbl.configure(
            text=f"Sistem Hızı: {win_get_speed()}/20"
                 f"   İvme: {'Açık' if win_get_accel() else 'Kapalı'}")

    # ── Startup ───────────────────────────────────────────────────────────────
    _STARTUP_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _STARTUP_NAME = "MouseShifter"

    def _get_startup(self) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._STARTUP_KEY, 0,
                                 winreg.KEY_READ)
            winreg.QueryValueEx(key, self._STARTUP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def _on_startup_toggle(self):
        exe = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._STARTUP_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            if self._startup_var.get():
                winreg.SetValueEx(key, self._STARTUP_NAME, 0, winreg.REG_SZ,
                                  f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, self._STARTUP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Startup registry error: {e}")

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _make_tray_image(self) -> Image.Image:
        sz  = 64
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.rounded_rectangle([14,  6, 50, 58], radius=14, fill="#1e1e1e", outline="#4caf7a", width=2)
        d.rounded_rectangle([27, 12, 37, 28], radius=4,  fill="#4caf7a")
        d.line([14, 32, 50, 32], fill="#4caf7a", width=1)
        return img

    def _start_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Aç",   self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Çıkış", self._quit),
        )
        self._tray = pystray.Icon(
            "MouseShifter", self._make_tray_image(), "MouseShifter", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _show_window(self, *_):
        self.after(0, self._do_show)

    def _do_show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_unmap(self, event):
        if self.state() == "iconic":
            self.withdraw()

    def _quit(self, *_):
        if self._tray:
            self._tray.stop()
        self.after(0, self.destroy)

    # ── Queue poll ────────────────────────────────────────────────────────────
    def _poll(self):
        # Drain the entire queue but only keep the last handle seen.
        # This prevents the UI from processing thousands of move events
        # when multiple mice move simultaneously.
        last_handle = None
        new_handles: set[str] = set()
        try:
            while True:
                h = _q.get_nowait()
                last_handle = h
                new_handles.add(h)
        except queue.Empty:
            pass

        # Create cards for any newly seen devices
        for h in new_handles:
            with _lock:
                dev = _devices.get(h)
            if dev and h not in self._cards:
                self._create_card(h, dev)

        # Only update active state / apply settings if active device changed
        if last_handle is not None and last_handle != self._last_active:
            with _lock:
                dev = _devices.get(last_handle)
            if dev:
                self._last_active = last_handle
                dev.apply()
                for h, c in self._cards.items():
                    c.set_active(h == last_handle)
                self._stat_dot.configure(text_color="#4caf7a")
                self._stat_lbl.configure(text=f"Aktif  →  {dev.name}", text_color=TEXT)
                self._refresh_footer()
                self._save()

        self.after(16, self._poll)

# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Thread(target=_raw_thread, daemon=True).start()
    App().mainloop()

# pyinstaller --onefile --windowed --icon=icon.ico --name=MouseShifter main.py