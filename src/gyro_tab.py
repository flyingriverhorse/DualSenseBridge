"""Gyro tab: aim by turning the controller (adds to the right stick in Xbox mode)."""

import tkinter as tk
from tkinter import ttk

import gyro as gy

SIZE = 110


class GyroTab(ttk.Frame):
    """`cfg` is settings["gyro"]; `on_change(cfg)` saves and applies it; `calibrate()` starts it."""

    def __init__(self, parent, cfg, on_change, calibrate):
        super().__init__(parent)
        self.cfg = gy.clean(cfg)
        self.on_change, self.calibrate = on_change, calibrate
        pad = {"padx": 12, "pady": 4}

        box = ttk.LabelFrame(self, text="Gyro aiming")
        box.pack(fill="x", **pad)
        self.var_on = tk.BooleanVar(value=self.cfg["enabled"])
        ttk.Checkbutton(box, text="Aim by turning the controller (moves the right stick)",
                        variable=self.var_on, command=self._changed).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Label(box, text="Xbox mode, DualSense or DualShock 4, USB or Bluetooth. Works in any game "
                            "that aims with the right stick.", foreground="#666", wraplength=460,
                  justify="left").pack(anchor="w", padx=26, pady=(0, 4))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Active", width=20).pack(side="left")
        self.var_act = tk.StringVar(value=self.cfg["activate"])
        cmb = ttk.Combobox(row, textvariable=self.var_act, values=gy.ACTIVATE, state="readonly", width=28)
        cmb.pack(side="left")
        cmb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Turn with", width=20).pack(side="left")
        self.var_axis = tk.StringVar(value=self.cfg["turn_axis"])
        for value, text in (("yaw", "turning left / right"), ("roll", "leaning left / right")):
            ttk.Radiobutton(row, text=text, value=value, variable=self.var_axis,
                            command=self._changed).pack(side="left", padx=(0, 8))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(2, 8))
        self.var_ix = tk.BooleanVar(value=self.cfg["invert_x"])
        self.var_iy = tk.BooleanVar(value=self.cfg["invert_y"])
        ttk.Checkbutton(row, text="Invert left / right", variable=self.var_ix,
                        command=self._changed).pack(side="left")
        ttk.Checkbutton(row, text="Invert up / down", variable=self.var_iy,
                        command=self._changed).pack(side="left", padx=12)

        box = ttk.LabelFrame(self, text="Feel")
        box.pack(fill="x", **pad)
        self.vars = {}
        for key, text in (("full_speed", "Full stick at (°/s)"), ("deadzone", "Ignore below (°/s)"),
                          ("game_deadzone", "Skip game deadzone (%)")):
            row = ttk.Frame(box)
            row.pack(fill="x", padx=8, pady=1)
            ttk.Label(row, text=text, width=22).pack(side="left", anchor="s")
            lo, hi = gy.LIMITS[key]
            var = tk.IntVar(value=self.cfg[key])
            tk.Scale(row, from_=lo, to=hi, orient="horizontal", length=180, width=10, variable=var, bd=0,
                     highlightthickness=0, font=("Segoe UI", 8),
                     command=lambda v: self._changed()).pack(side="left")
            self.vars[key] = var
        ttk.Label(box, text="Lower 'full stick' = more sensitive. If small turns do nothing, raise "
                            "'skip game deadzone'; if the view creeps on its own, raise it less.",
                  foreground="#666", wraplength=460, justify="left").pack(anchor="w", padx=8, pady=(2, 8))

        box = ttk.LabelFrame(self, text="Live")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=6)
        self.canvas = tk.Canvas(row, width=SIZE, height=SIZE, bg="white", highlightthickness=0)
        self.canvas.pack(side="left")
        right = ttk.Frame(row)
        right.pack(side="left", padx=12, fill="y")
        self.lbl_state = ttk.Label(right, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_state.pack(anchor="w")
        self.lbl_rates = ttk.Label(right, text="", foreground="#666")
        self.lbl_rates.pack(anchor="w", pady=(2, 8))
        ttk.Button(right, text="Calibrate", command=self.calibrate).pack(anchor="w")
        ttk.Label(right, text="Lay the controller flat and still, then press.\n"
                              "Drift is also corrected on its own while it rests.",
                  foreground="#666", justify="left").pack(anchor="w", pady=(2, 0))
        self.update_live({"has": False, "active": False, "calibrating": False, "rates": (0, 0, 0),
                          "out": (0, 0)}, False, False)

    def _changed(self):
        self.cfg = gy.clean({"enabled": self.var_on.get(), "activate": self.var_act.get(),
                             "turn_axis": self.var_axis.get(), "invert_x": self.var_ix.get(),
                             "invert_y": self.var_iy.get(),
                             **{k: int(float(v.get())) for k, v in self.vars.items()}})
        self.on_change(self.cfg)

    def update_live(self, g, connected, xbox):
        if not connected:
            state, color = "No controller", "#a04030"
        elif not g["has"]:
            state, color = "No gyro data yet (Bluetooth simple mode?)", "#a04030"
        elif g["calibrating"]:
            state, color = "Calibrating… keep it still", "#b08d1f"
        elif not self.cfg["enabled"]:
            state, color = "Gyro aiming is off", "#666"
        elif not xbox:
            state, color = "Waiting for Xbox mode", "#666"
        elif g["active"]:
            state, color = "● Aiming", "#1f7a3f"
        else:
            state, color = f"Ready ({self.cfg['activate'].lower()})", "#1f5fbf"
        if self.lbl_state.cget("text") != state:
            self.lbl_state.config(text=state, foreground=color)
        p, y, r = g["rates"]
        self.lbl_rates.config(text=f"Up/down {p:+6.1f} °/s   Turn {y:+6.1f} °/s   Lean {r:+6.1f} °/s")
        c = self.canvas
        c.delete("all")
        mid, rad = SIZE / 2, SIZE / 2 - 4
        c.create_oval(mid - rad, mid - rad, mid + rad, mid + rad, outline="#c8ccd4")
        gd = rad * self.cfg["game_deadzone"] / 100
        if gd:
            c.create_oval(mid - gd, mid - gd, mid + gd, mid + gd, outline="#d8dce4", dash=(2, 2))
        ox, oy = g["out"]
        qx, qy = mid + ox * rad, mid - oy * rad
        c.create_line(mid, mid, qx, qy, fill="#1f7a3f", width=2)
        c.create_oval(qx - 4, qy - 4, qx + 4, qy + 4, fill="#1f7a3f", outline="")
