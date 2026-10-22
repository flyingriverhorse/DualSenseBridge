"""Controls tab: stick and trigger deadzones, button remapping (Xbox mode)."""

import tkinter as tk
from tkinter import ttk

import mapping as m

SIZE = 96          # stick picture


class ControlsTab(ttk.Frame):
    """`cfg` is the stored dict (settings["controls"]); `on_change(cfg)` saves and applies it."""

    def __init__(self, parent, cfg, on_change):
        super().__init__(parent)
        self.cfg = m.clean(cfg)
        self.on_change = on_change
        self.sticks = (128, 128, 128, 128)
        self.triggers = (0, 0)
        pad = {"padx": 12, "pady": 4}

        ttk.Label(self, text="These apply in Xbox mode. Defaults leave the controller exactly as it is.",
                  foreground="#666").pack(anchor="w", padx=12, pady=(8, 0))

        # sticks
        box = ttk.LabelFrame(self, text="Stick deadzones (stops drift)")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=6)
        self.canvases, self.vars = {}, {}
        for side, key in (("Left stick", "ls_deadzone"), ("Right stick", "rs_deadzone")):
            col = ttk.Frame(row)
            col.pack(side="left", expand=True)
            ttk.Label(col, text=side).pack()
            c = tk.Canvas(col, width=SIZE, height=SIZE, bg="white", highlightthickness=0)
            c.pack(pady=2)
            self.canvases[key] = c
            self._slider(col, key, "Deadzone %")

        # triggers
        box = ttk.LabelFrame(self, text="Triggers (L2 / R2)")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(6, 0))
        self._slider(row, "trigger_deadzone", "Ignore the first %", side="left")
        self._slider(row, "trigger_full", "Full press at %", side="left")
        self.lbl_trig = ttk.Label(box, text="", foreground="#666")
        self.lbl_trig.pack(anchor="w", padx=8, pady=(2, 6))

        # buttons
        box = ttk.LabelFrame(self, text="Buttons")
        box.pack(fill="x", **pad)
        grid = ttk.Frame(box)
        grid.pack(fill="x", padx=8, pady=6)
        self.cmbs = {}
        half = (len(m.SOURCES) + 1) // 2
        for i, src in enumerate(m.SOURCES):
            r, c = i % half, (i // half) * 2
            ttk.Label(grid, text=src).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 18, 6), pady=1)
            cmb = ttk.Combobox(grid, values=m.TARGETS, state="readonly", width=15)
            cmb.set(self.cfg["remap"].get(src, m.DEFAULT_REMAP[src]))
            cmb.bind("<<ComboboxSelected>>", lambda e, s=src: self._remap(s))
            cmb.grid(row=r, column=c + 1, sticky="w", pady=1)
            self.cmbs[src] = cmb
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(row, text="Reset buttons", command=self.reset_buttons).pack(side="left")
        ttk.Label(row, text="Tip: Touchpad → Back is handy for maps and scoreboards.",
                  foreground="#666").pack(side="left", padx=8)
        self._draw()

    # ------------------------------------------------ widgets

    def _slider(self, parent, key, text, side=None):
        lo, hi = m.LIMITS[key]
        frame = ttk.Frame(parent)
        frame.pack(side=side or "top", padx=(0, 16) if side else 0)
        ttk.Label(frame, text=text).pack(side="left", anchor="s")
        var = tk.IntVar(value=self.cfg[key])
        tk.Scale(frame, from_=lo, to=hi, orient="horizontal", length=120, width=10, variable=var,
                 bd=0, highlightthickness=0, font=("Segoe UI", 8),
                 command=lambda v, k=key: self._set(k, int(float(v)))).pack(side="left")
        self.vars[key] = var

    def _set(self, key, value):
        if self.cfg[key] != value:
            self.cfg[key] = value
            self._apply()

    def _remap(self, src):
        self.cfg["remap"][src] = self.cmbs[src].get()
        self._apply()

    def reset_buttons(self):
        for src, cmb in self.cmbs.items():
            cmb.set(m.DEFAULT_REMAP[src])
        self.cfg["remap"] = {}
        self._apply()

    def _apply(self):
        self.cfg = m.clean(self.cfg)
        self.on_change(self.cfg)
        self._draw()

    # ------------------------------------------------ live picture

    def update_live(self, sticks, l2, r2):
        if sticks != self.sticks or (l2, r2) != self.triggers:
            self.sticks, self.triggers = sticks, (l2, r2)
            self._draw()

    def _draw(self):
        lx, ly, rx, ry = self.sticks
        for key, (x, y) in (("ls_deadzone", (lx, ly)), ("rs_deadzone", (rx, ry))):
            c = self.canvases[key]
            c.delete("all")
            mid, r = SIZE / 2, SIZE / 2 - 4
            c.create_oval(mid - r, mid - r, mid + r, mid + r, outline="#c8ccd4")
            dz = r * self.cfg[key] / 100
            if dz:
                c.create_oval(mid - dz, mid - dz, mid + dz, mid + dz, fill="#f1d9d9", outline="#d08080")
            px, py = mid + (x - 127.5) / 127.5 * r, mid + (y - 127.5) / 127.5 * r
            c.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#999", outline="")          # raw
            ox, oy = m.stick(x, y, self.cfg[key])
            qx, qy = mid + ox / 32767 * r, mid - oy / 32767 * r
            c.create_oval(qx - 4, qy - 4, qx + 4, qy + 4, fill="#1f7a3f", outline="")       # sent to games
        dzt, full = self.cfg["trigger_deadzone"], self.cfg["trigger_full"]
        l2, r2 = self.triggers
        self.lbl_trig.config(text=f"Now: L2 {l2} → {m.trigger(l2, dzt, full)}    R2 {r2} → "
                                  f"{m.trigger(r2, dzt, full)}   (what games get, 0–255)")
