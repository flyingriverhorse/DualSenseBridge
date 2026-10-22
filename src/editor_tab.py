"""Profile editor tab: build L2 / R2 effects with sliders, feel them live, save them."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import profile_editor as pe

ZONE_W, STRIP_H, BAR_H = 23, 52, 32
COLORS = {"resist": "#3d7bd9", "vibrate": "#e08a2c", "snap": "#c94040", "": "#e6e9ef"}


class SidePanel(ttk.LabelFrame):
    """One trigger: mode, its parameters, and a 10-zone picture with the live position."""

    def __init__(self, parent, side, on_change):
        super().__init__(parent, text=f"{side} ({'left' if side == 'L2' else 'right'} trigger)")
        self.side, self.on_change = side, on_change
        self.value = pe.defaults("off")
        self.position = 0
        self._loading = False

        self.var_mode = tk.StringVar(value="off")
        cmb = ttk.Combobox(self, textvariable=self.var_mode, values=pe.MODES, state="readonly", width=14)
        cmb.pack(anchor="w", padx=8, pady=(6, 0))
        cmb.bind("<<ComboboxSelected>>", lambda e: self._mode_changed())
        self.lbl_help = ttk.Label(self, text="", foreground="#666", wraplength=230, justify="left")
        self.lbl_help.pack(anchor="w", padx=8, pady=(2, 2))

        self.canvas = tk.Canvas(self, width=ZONE_W * 10 + 1, height=STRIP_H, highlightthickness=0, bg="white")
        self.canvas.pack(padx=8, pady=(2, 4))
        self.params = ttk.Frame(self)
        self.params.pack(fill="x", padx=8, pady=(0, 8))
        self.set(self.value)

    # ------------------------------------------------ value

    def set(self, d):
        """Show a profile side (dict as in profiles.json)."""
        self.value = pe.normalize(d)
        self._loading = True
        self.var_mode.set(self.value["mode"])
        self._build_params()
        self._loading = False
        self._refresh()

    def _mode_changed(self):
        self.value = pe.defaults(self.var_mode.get())
        self._loading = True
        self._build_params()
        self._loading = False
        self._changed()

    def _build_params(self):
        for w in self.params.winfo_children():
            w.destroy()
        mode = self.value["mode"]
        self.lbl_help.config(text=pe.MODE_HELP.get(mode, ""))
        if mode == "multi":
            row = ttk.Frame(self.params)
            row.pack(anchor="w")
            for z in range(10):
                col = ttk.Frame(row)
                col.pack(side="left")
                var = tk.IntVar(value=self.value["strengths"][z])
                tk.Scale(col, from_=8, to=0, orient="vertical", length=84, width=10, showvalue=True,
                         font=("Segoe UI", 7), variable=var, bd=0, highlightthickness=0,
                         command=lambda v, z=z: self._multi(z, v)).pack()
                ttk.Label(col, text=str(z), foreground="#888").pack()
            return
        for name, lo, hi in pe.RANGES.get(mode, []):
            row = ttk.Frame(self.params)
            row.pack(fill="x")
            ttk.Label(row, text=pe.LABELS.get(name, name), width=17).pack(side="left", anchor="s")
            var = tk.IntVar(value=self.value[name])
            tk.Scale(row, from_=lo, to=hi, orient="horizontal", length=110, width=10, resolution=1,
                     variable=var, bd=0, highlightthickness=0, font=("Segoe UI", 8),
                     command=lambda v, n=name: self._param(n, v)).pack(side="left")

    def _param(self, name, v):
        if self._loading:
            return
        self.value[name] = int(float(v))
        self._changed()

    def _multi(self, zone, v):
        if self._loading:
            return
        self.value["strengths"][zone] = int(float(v))
        self._changed()

    def _changed(self):
        self.value = pe.normalize(self.value)
        self._refresh()
        self.on_change()

    # ------------------------------------------------ picture

    def show_position(self, value):
        if value != self.position:
            self.position = value
            self._refresh()

    def _refresh(self):
        c = self.canvas
        c.delete("all")
        here = pe.zone_of(self.position)
        for z, (strength, kind) in enumerate(pe.zone_view(self.value)):
            x = z * ZONE_W
            c.create_rectangle(x + 1, 4, x + ZONE_W - 1, 4 + BAR_H, fill=COLORS[""], outline="")
            if strength:
                h = max(3, round(BAR_H * strength / 8))
                c.create_rectangle(x + 1, 4 + BAR_H - h, x + ZONE_W - 1, 4 + BAR_H,
                                   fill=COLORS[kind], outline="")
            c.create_text(x + ZONE_W / 2, STRIP_H - 7, text=str(z), font=("Segoe UI", 7),
                          fill="#222" if z == here and self.position else "#999")
        if self.position:
            px = 1 + self.position / 255 * (ZONE_W * 10 - 2)
            c.create_line(px, 1, px, 6 + BAR_H, fill="#111", width=2)


class EditorTab(ttk.Frame):
    """The whole tab. `profiles()` returns the merged profile dict, `label(key)` its display name,
    `on_saved(key)` is called after a save or delete (key None), `current_game()` returns the
    last game .exe seen in the foreground (or None)."""

    def __init__(self, parent, engine, profiles, label, user_path, on_saved, current_game=lambda: None):
        super().__init__(parent)
        self.engine, self.profiles, self.label = engine, profiles, label
        self.user_path, self.on_saved, self.current_game = user_path, on_saved, current_game
        self.loaded_key = None
        pad = {"padx": 12, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Start from").pack(side="left")
        self.cmb_from = ttk.Combobox(top, state="readonly", width=34)
        self.cmb_from.pack(side="left", padx=6)
        self.cmb_from.bind("<<ComboboxSelected>>", lambda e: self.load(self._from_key()))
        self.refresh_list()

        self.var_live = tk.BooleanVar(value=False)
        live = ttk.Frame(self)
        live.pack(fill="x", padx=12)
        ttk.Checkbutton(live, text="Feel it on the controller now (live preview)", variable=self.var_live,
                        command=self.apply_preview).pack(side="left")
        self.lbl_note = ttk.Label(self, text="", foreground="#666", wraplength=470, justify="left")
        self.lbl_note.pack(anchor="w", padx=12)

        sides = ttk.Frame(self)
        sides.pack(fill="x", **pad)
        self.l2 = SidePanel(sides, "L2", self.apply_preview)
        self.l2.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.r2 = SidePanel(sides, "R2", self.apply_preview)
        self.r2.pack(side="left", fill="both", expand=True, padx=(4, 0))

        legend = ttk.Frame(self)
        legend.pack(anchor="w", padx=12)
        for kind, text in [("resist", "resistance"), ("vibrate", "vibration"), ("snap", "click / snap")]:
            tk.Label(legend, bg=COLORS[kind], width=2).pack(side="left", padx=(0, 3))
            ttk.Label(legend, text=text, foreground="#666").pack(side="left", padx=(0, 10))
        ttk.Label(legend, text="│ = where your trigger is", foreground="#666").pack(side="left")

        box = ttk.LabelFrame(self, text="Save")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(row, text="Name").pack(side="left")
        self.var_name = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_name, width=26).pack(side="left", padx=6)
        ttk.Button(row, text="Save as my profile", command=self.save).pack(side="left")
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Game .exe").pack(side="left")
        self.var_exe = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_exe, width=22).pack(side="left", padx=6)
        ttk.Button(row, text="Browse…", command=self.browse_exe).pack(side="left")
        ttk.Button(row, text="Game in front", command=self.use_current_game).pack(side="left", padx=6)
        ttk.Label(box, text="Optional. With the game's .exe, this profile switches on by itself when "
                            "the game starts (Xbox mode on).", foreground="#666", wraplength=460,
                  justify="left").pack(anchor="w", padx=8)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(2, 8))
        self.btn_delete = ttk.Button(row, text="Delete this profile", command=self.delete, state="disabled")
        self.btn_delete.pack(side="left")
        ttk.Button(row, text="Copy JSON (to share)", command=self.copy_json).pack(side="left", padx=6)
        self.lbl_status = ttk.Label(box, text="Your profiles are kept in your user folder, so updates "
                                              "do not overwrite them.", foreground="#666",
                                    wraplength=460, justify="left")
        self.lbl_status.pack(anchor="w", padx=8, pady=(0, 6))

    # ------------------------------------------------ list / load

    def refresh_list(self):
        p = self.profiles()
        self.keys = [k for k in p if not k.startswith("_")]
        self.keys.sort(key=lambda k: (not k.startswith(pe.USER_PREFIX), k != "off", self.label(k).lower()))
        self.cmb_from["values"] = [self.label(k) for k in self.keys]

    def _from_key(self):
        i = self.cmb_from.current()
        return self.keys[i] if 0 <= i < len(self.keys) else None

    def load(self, key):
        if key is None:
            return
        from bridge_profiles import resolve_profile
        try:
            r = resolve_profile(self.profiles(), key)
        except SystemExit as e:                 # unknown preset in a hand-edited profiles.json
            self.lbl_status.config(text=str(e))
            return
        self.loaded_key = key
        self.l2.set(r["L2"])
        self.r2.set(r["R2"])
        user = key.startswith(pe.USER_PREFIX)
        entry = self.profiles()[key]
        self.var_name.set(entry.get("_name", "") if user else
                          (self.label(key) + " (mine)" if key != "off" else ""))
        self.var_exe.set(", ".join(entry.get("_exe", [])))
        self.btn_delete.config(state="normal" if user else "disabled")
        if key in self.keys:
            self.cmb_from.current(self.keys.index(key))
        self.apply_preview()

    # ------------------------------------------------ preview

    def apply_preview(self):
        if self.var_live.get():
            self.engine.set_preview(pe.to_bytes(self.l2.value), pe.to_bytes(self.r2.value))
        else:
            self.engine.clear_preview()

    def stop_preview(self):
        if self.var_live.get():
            self.var_live.set(False)
        self.engine.clear_preview()

    def update_live(self, l2, r2, model, connected):
        self.l2.show_position(l2)
        self.r2.show_position(r2)
        if not connected:
            note = "Connect the controller to feel the effects. You can still build and save them."
        elif model == "ds4":
            note = "Adaptive triggers need a DualSense: a DualShock 4 cannot play these effects."
        elif self.var_live.get():
            note = ("Live: the controller plays these effects now, even with Xbox mode off. "
                    "They stop when you leave this tab.")
        else:
            note = "Turn on the live preview and press L2 / R2 to feel each change as you make it."
        if self.lbl_note.cget("text") != note:
            self.lbl_note.config(text=note)

    # ------------------------------------------------ save / delete / share

    def save(self):
        name = self.var_name.get().strip()
        if not name:
            self.lbl_status.config(text="Give the profile a name first.")
            return
        key = pe.slug(name)
        if key in self.profiles() and key != self.loaded_key and not messagebox.askyesno(
                "DualSense Bridge", f"You already have a profile called \"{name}\". Replace it?"):
            return
        exes = pe.exe_list(self.var_exe.get())
        try:
            key = pe.save_user(self.user_path, name, self.l2.value, self.r2.value, exes=exes)
        except OSError as e:
            self.lbl_status.config(text=f"Could not save: {e}")
            return
        self.on_saved(key)
        self.refresh_list()
        self.loaded_key = key
        self.btn_delete.config(state="normal")
        if key in self.keys:
            self.cmb_from.current(self.keys.index(key))
        self.var_exe.set(", ".join(exes))
        where = (f"It switches on by itself for {', '.join(exes)}." if exes else
                 "It is selected on the Controller tab; add the game's .exe to switch it on by itself.")
        self.lbl_status.config(text=f"Saved \"{name}\". {where}")

    def delete(self):
        key = self.loaded_key
        if not key or not key.startswith(pe.USER_PREFIX):
            return
        name = self.profiles()[key].get("_name", key)
        if not messagebox.askyesno("DualSense Bridge", f"Delete your profile \"{name}\"?"):
            return
        pe.delete_user(self.user_path, key)
        self.loaded_key = None
        self.btn_delete.config(state="disabled")
        self.on_saved(None)
        self.refresh_list()
        self.cmb_from.set("")
        self.lbl_status.config(text=f"Deleted \"{name}\".")

    def browse_exe(self):
        path = filedialog.askopenfilename(title="The game's .exe", filetypes=[("Programs", "*.exe")])
        if path:
            self.add_exe(path)

    def use_current_game(self):
        exe = self.current_game()
        if exe:
            self.add_exe(exe)
        else:
            self.lbl_status.config(text="No game seen yet: start the game, switch back here and press again.")

    def add_exe(self, exe):
        exes = pe.exe_list(self.var_exe.get()) + pe.exe_list([exe])
        self.var_exe.set(", ".join(pe.exe_list(exes)))
        if not self.var_name.get().strip():
            self.var_name.set(pe.exe_list([exe])[0][:-4].replace("_", " ").title())

    def copy_json(self):
        text = pe.share_json(self.var_name.get() or "my_profile", self.l2.value, self.r2.value,
                             pe.exe_list(self.var_exe.get()))
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_status.config(text="Copied. Paste it into a GitHub issue to share it, "
                                    "or into profiles.json.")
